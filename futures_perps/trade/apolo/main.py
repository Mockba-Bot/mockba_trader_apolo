import json
import requests
import os
import threading
import time
import sys
import re
import redis
from pydantic import BaseModel
# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from db.db_ops import get_open_positions, update_position_pnl, initialize_database_tables, get_bot_status
from logs.log_config import binance_trader_logger as logger
from binance.client import Client as BinanceClient
from trading_bot.send_bot_message import send_bot_message
from historical_data import get_historical_data_limit_binance, get_orderbook

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Initialize Redis connection
redis_url = os.getenv("REDIS_URL")
if redis_url:
    try:
        redis_client = redis.from_url(redis_url)
        redis_client.ping()
        logger.info("Connected to Redis successfully")
    except redis.ConnectionError as e:
        logger.warning(f"Redis not available (optional caching disabled): {e}")
        redis_client = None
else:
    logger.info("Redis not configured (optional caching disabled)")
    redis_client = None


# Import your executor
from trading_bot.futures_executor_binance import place_futures_order, get_confidence_level as executor_get_confidence_level

# Import your liquidity persistence monitor
import liquidity_persistence_monitor as lpm

RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "1.5"))
MAX_LEVERAGE_HIGH = int(os.getenv("MAX_LEVERAGE_HIGH", "5"))
MAX_LEVERAGE_MEDIUM = int(os.getenv("MAX_LEVERAGE_MEDIUM", "4"))
MAX_LEVERAGE_SMALL = int(os.getenv("MAX_LEVERAGE_SMALL", "3"))
MICRO_BACKTEST_MIN_EXPECTANCY = float(os.getenv("MICRO_BACKTEST_MIN_EXPECTANCY", "0.0025"))

# Request model for your signal
class TradingSignal(BaseModel):
    asset: str
    signal: str  # "LONG" or "SHORT"
    confidence: float  # 0-100%
    timeframe: str  # "4h", "1h", etc.
    current_price: float
    liquidity_score: float
    volume_1h: float
    volatility_1h: float

def get_confidence_level(confidence: float) -> str:
    """Map confidence score to human-readable level for ML signals (0-100 scale)"""
    if confidence >= 80:  # Updated for your 100% scale
        return "🚀 VERY STRONG"
    elif confidence >= 70:
        return "💪 STRONG"
    elif confidence >= 60:
        return "👍 MODERATE"
    else:
        return "❌ WEAK"

def get_leverage_by_confidence(confidence: float) -> int:
    """Get leverage based on confidence level"""
    if confidence >= 80:
        return MAX_LEVERAGE_HIGH  # High confidence = max leverage
    elif confidence >= 70:
        return MAX_LEVERAGE_MEDIUM   # Medium confidence = moderate leverage
    elif confidence >= 60:
        return MAX_LEVERAGE_SMALL   # Low confidence = low leverage
    else:
        return 1   # Very low confidence = minimal leverage

def load_prompt_template():
    """Load LLM prompt from file"""
    try:
        with open("futures_perps/trade/binance/llm_prompt_template.txt", "r") as f:
            return f.read()
    except FileNotFoundError:
        raise FileNotFoundError("llm_prompt_template.txt not found. Please create the prompt file.")

def get_current_balance():
    """Get current account balance from Binance"""
    from binance.client import Client as BinanceClient
    import os
    
    client = BinanceClient(
        api_key=os.getenv("BINANCE_API_KEY"),
        api_secret=os.getenv("BINANCE_SECRET_KEY"),
        testnet=False
    )
    
    try:
        account = client.futures_account()
        for asset_info in account['assets']:
            if asset_info['asset'] == 'USDT':
                return float(asset_info['marginBalance'])
    except Exception as e:
        # Default to 20 if API call fails
        return 20.0

# Helper: Format orderbook as text (not CSV!)
def format_orderbook_as_text(ob: dict) -> str:
    lines = ["Top Bids (price, quantity):"]
    for price, qty in ob.get('bids', [])[:15]:
        lines.append(f"{price},{qty}")
    
    lines.append("\nTop Asks (price, quantity):")
    for price, qty in ob.get('asks', [])[:15]:
        lines.append(f"{price},{qty}")
    
    return "\n".join(lines)


def analyze_with_llm(signal_dict: dict) -> dict:
    """Send to LLM for detailed analysis using fixed prompt structure."""
    
    # ✅ Get DataFrame with ALL indicators (your function handles timeframe logic)
    df = get_historical_data_limit_binance(
        pair=signal_dict['asset'],
        timeframe=signal_dict['interval'],
        limit=80
    )
    csv_content = df.to_csv(index=False)  # ← Preserves all columns automatically
    # get the latest close price from the dataframe
    latest_close_price = df['close'].iloc[-1]

    # ✅ Get orderbook as TEXT (not CSV!)
    orderbook = get_orderbook(signal_dict['asset'], limit=20)
    orderbook_content = format_orderbook_as_text(orderbook)  # ← See helper below

    # --- Rest of your prompt logic (unchanged) ---
    intro = (
        "You are an experienced retail crypto trader with 10 years of experience.\n"
        "Analyze the attached CSV (80 candles) and orderbook for the given signal.\n\n"
        "DEFAULT: 'DO NOT EXECUTE' unless ALL strict conditions below are met.\n\n"
        f"• Asset: {signal_dict['asset']}\n"
        f"• Signal: {signal_dict['signal']}\n"
        f"• Confidence: {signal_dict['confidence']}%\n"
        f"• Timeframe: {signal_dict['interval']}\n"
        f"• Current Price: ${latest_close_price}\n"
        f"• Liquidity Score: {signal_dict['liquidity_score']}\n"
        f"• Volume (1h): ${signal_dict['volume_1h']}\n"
        f"• Volatility (1h): {signal_dict['volatility_1h']}%\n\n"
    )

     # Get leverage based on confidence
    leverage = get_leverage_by_confidence(signal_dict['confidence_percent'])
            

    analysis_logic = load_prompt_template()

    response_format = (
        f"\nRETURN ONLY JSON with keys: symbol, side, entry, take_profit, stop_loss, confidence: {signal_dict['confidence_percent']}, leverage: {leverage}\n"
    )

    prompt = intro + analysis_logic + response_format

    # --- Send to DeepSeek ---
    response = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.getenv('DEEP_SEEK_API_KEY')}"},
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "user", "content": prompt},
                {"role": "user", "content": f"Candles (CSV format):\n{csv_content}"},
                {"role": "user", "content": f"Orderbook:\n{orderbook_content}"}
            ],
            "temperature": 0.0,
            "max_tokens": 500
        }
    )
    
    if response.status_code == 200:
        content = response.json()['choices'][0]['message']['content']
        # Check if LLM approves the trade
        approved = "DO NOT EXECUTE" not in content.upper()
        return {"analysis": content, "approved": approved}
    return {"analysis": "LLM analysis failed", "approved": False}


def process_signal():
    while True:
        """Process incoming signal from Api bot with combined CSV + orderbook file"""
        # Only proceed if bot is running
        if not get_bot_status():
            logger.info("Bot is paused. Waiting to resume...")
            time.sleep(30)
            continue

        # Get signal from Mockba ML
        URL = "https://signal.globaldv.net/api/v1/signals/active?venue=CEX"
        # The API is free, get no post
        response = requests.get(URL)
        if response.status_code != 200:
            logger.error(f"Failed to fetch signals: {response.status_code}")
            time.sleep(30)
            continue

        # If the ressponse if a empty list, skip
        if response.json() == []:
            logger.info("No active signals received.")
            time.sleep(30)
            continue
        
        signals = response.json()  # List of signal dicts
        # Emulate json
        # signals = [
        # {
        #     "asset": "LTCUSDT",
        #     "signal": 1,
        #     "confidence": 1,
        #     "confidence_percent": 100,
        #     "interval": "4h",
        #     "venue": "CEX",
        #     "score": 1,
        #     "regime": "HIGH VOLATILITY",
        #     "timestamp": "2025-11-23T22:19:30.249249+00:00",
        #     "expires_at": 1763939970.249278,
        #     "signal_id": "CEX_20251123_221930",
        #     "liquidity_tier": "Unknown",
        #     "liquidity_score": 7.28,
        #     "volume_1h": 2483583.05,
        #     "volatility_1h": 1.24,
        #     "backtest": {
        #     "trades": 131,
        #     "winrate": 0.802,
        #     "avg_ret": 0.0016,
        #     "exp": 0.0032,
        #     "max_dd": -0.0652
        #     }
        # }
        # ]

        # Compare with Redis to avoid duplicates
        if redis_client:
            current_id = signals[0].get('signal_id') if signals else None
            stored_id = redis_client.get("latest_signal_id")
            
            if stored_id and current_id == stored_id.decode('utf-8'):
                logger.info(f"Signal {current_id} already processed. Skipping.")
                time.sleep(30)
                continue
            elif current_id:
                redis_client.setex("latest_signal_id", 3600, current_id)
        else:
            logger.warning("Redis not available, skipping deduplication")

        # Process the single signal (API always returns one)
        if signals:
            signal = signals[0]
            # Get confidence level
            confidence_level = get_confidence_level(signal['confidence_percent'])
            
            # Only proceed if confidence is moderate or higher
            if confidence_level == "❌ WEAK":
                logger.info(f"Skipping weak signal for {signal['asset']}")
                time.sleep(30)
                continue
            
            # --- MICRO BACKTEST CHECK ---
            bt = signal.get('backtest', {})
            
            # Must have positive expectancy and enough trades
            if bt.get("trades", 0) < 15 or bt.get("exp", 0.0) <= MICRO_BACKTEST_MIN_EXPECTANCY:
                logger.info(f"❌ {signal['asset']} micro-backtest failed: {bt}")
                time.sleep(30)
                continue
            
            logger.info(f"✅ {signal['asset']} micro-backtest passed: {bt}")
            
           
            # --- LIQUIDITY PERSISTENCE CHECK ---
            cex_check = lpm.validate_cex_consensus_for_dex_asset(signal['asset'])
            if cex_check["consensus"] == "NO_CEX_PAIR":
                logger.info(f"🛑 {signal['asset']} CEX consensus check failed: {cex_check['reason']}")
                time.sleep(30)
                continue
            elif cex_check["consensus"] == "LOW":
                logger.info(f"❌ Skipping {signal['asset']}: LOW CEX consensus ({cex_check['reason']})")
                time.sleep(30)
                continue
            else:
                logger.info(f"✅ {signal['asset']} passed CEX consensus: {cex_check['reason']}")
            
            # Analyze with LLM
            llm_result = analyze_with_llm(signal)
            print(llm_result["approved"])
            if not bool(llm_result["approved"]):
                logger.info(f"LLM rejected signal for {signal['asset']}: {llm_result['analysis'][:200]}...")
                time.sleep(30)
                continue
            
            # Parse the JSON from LLM analysis
            try:
                # Extract JSON from code blocks if present
                analysis = llm_result["analysis"]
                if '```json' in analysis:
                    json_start = analysis.find('```json') + 7
                    json_end = analysis.find('```', json_start)
                    if json_end == -1:
                        json_end = len(analysis)
                    json_str = analysis[json_start:json_end].strip()
                else:
                    json_str = analysis.strip()
                
                parsed_signal = json.loads(json_str)
                
                # Ensure required fields are present
                required_fields = ['symbol', 'side', 'entry', 'stop_loss', 'take_profit', 'confidence']
                if not all(field in parsed_signal for field in required_fields):
                    raise ValueError("Missing required fields")
                    
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning(f"Failed to parse LLM JSON response for {signal['asset']}: {e}")
                time.sleep(30)
                continue
            
            
            # Execute position using your existing executor
            execution_result = place_futures_order(parsed_signal)
            
            logger.info(f"Execution result for {signal['asset']}: {execution_result}")

        # Sleep for 30 seconds before next fetch
        time.sleep(30)



if __name__ == "__main__":
    # Check for tables
    initialize_database_tables()

    # Start signal processing
    process_signal()