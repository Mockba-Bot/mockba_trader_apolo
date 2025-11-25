import os
import math
import json
from dotenv import load_dotenv
from binance.client import Client
from binance.enums import SIDE_BUY, SIDE_SELL, ORDER_TYPE_MARKET
from binance.exceptions import BinanceAPIException
import redis
import sys
from trading_bot.send_bot_message import send_bot_message

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logs.log_config import binance_trader_logger as logger

load_dotenv()

# Initialize Binance Futures client
client = Client(
    api_key=os.getenv("BINANCE_API_KEY"),
    api_secret=os.getenv("BINANCE_SECRET_KEY"),
    testnet=False
)

# Redis
# Initialize Redis connection
try:
    redis_client = redis.from_url(os.getenv("REDIS_URL"))
    redis_client.ping()
except redis.ConnectionError as e:
    print(f"Redis connection error: {e}")
    redis_client = None

# Risk parameters - SAFER VALUES
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "0.3"))  # Reduced to 0.3%
LEVERAGE_MAP = {
    "🚀 VERY STRONG": int(os.getenv("MAX_LEVERAGE_VERY_STRONG", "3")),  # Reduced to 3x
    "💪 STRONG": int(os.getenv("MAX_LEVERAGE_STRONG", "2")),            # Reduced to 2x
    "👍 MODERATE": int(os.getenv("MAX_LEVERAGE_MODERATE", "1")),        # Reduced to 1x
    "⚠️ WEAK": 0,
    "❌ VERY WEAK": 0
}

def get_confidence_level(confidence: float) -> str:
    if confidence >= 3.0:  # STRONGER thresholds
        return "🚀 VERY STRONG"
    elif confidence >= 2.0:
        return "💪 STRONG"
    elif confidence >= 1.8:
        return "👍 MODERATE"
    else:
        return "⚠️ WEAK"

def get_futures_exchange_info(symbol: str):
    cache_key = f"futures_info_{symbol}"
    if redis_client:
        cached = redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

    try:
        info = client.futures_exchange_info()
        for s in info['symbols']:
            if s['symbol'] == symbol:
                filters = {f['filterType']: f for f in s['filters']}
                result = {
                    'pricePrecision': s['pricePrecision'],
                    'quantityPrecision': s['quantityPrecision'],
                    'stepSize': float(filters['LOT_SIZE']['stepSize']),
                    'minQty': float(filters['LOT_SIZE']['minQty']),
                    'maxQty': float(filters['LOT_SIZE']['maxQty']),
                    'minNotional': float(filters.get('MIN_NOTIONAL', {}).get('notional', 0)) or 5.0
                }
                if redis_client:
                    redis_client.setex(cache_key, 3600, json.dumps(result))
                return result
    except Exception as e:
        logger.error(f"Failed to get futures info for {symbol}: {e}")
    return None

def get_available_balance(asset: str = "USDT") -> float:
    try:
        account = client.futures_account()
        if 'assets' not in account:
            logger.error("Invalid futures account response")
            return 0.0
        for asset_info in account['assets']:
            if asset_info['asset'] == asset:
                balance = float(asset_info.get('availableBalance', 0))
                logger.info(f"Available {asset} balance: {balance}")
                return balance
        logger.warning(f"Asset {asset} not found in futures account")
    except Exception as e:
        logger.error(f"Failed to get balance: {e}")
    return 0.0

def set_leverage(symbol: str, leverage: int):
    try:
        client.futures_change_leverage(symbol=symbol, leverage=leverage)
        logger.info(f"Set leverage for {symbol} to {leverage}x")
    except Exception as e:
        logger.error(f"Failed to set leverage for {symbol}: {e}")

def round_step_size(quantity: float, step_size: float) -> float:
    if step_size <= 0:
        return quantity
    precision = max(0, int(round(-math.log(step_size, 10), 0)))
    return round(quantity - (quantity % step_size), precision)

def calculate_position_size_with_margin_cap(signal: dict, available_balance: float, leverage: int, symbol_info: dict) -> float:
    """
    Calculate position size based on:
    1. Risk amount = balance * RISK_PER_TRADE_PCT / |entry - SL|
    2. Cap by max affordable notional = balance * leverage * 0.95
    """
    entry = float(signal['entry'])
    sl = float(signal['stop_loss'])
    side = signal['side'].upper()

    risk_amount = available_balance * (RISK_PER_TRADE_PCT / 100)
    risk_per_unit = abs(entry - sl)

    if risk_per_unit <= 0:
        logger.warning("Invalid stop loss placement")
        return 0.0

    # Prevent division by zero
    if risk_per_unit < 1e-10:  # Very small risk per unit
        logger.warning("Risk per unit too small, skipping trade")
        return 0.0

    qty_by_risk = risk_amount / risk_per_unit

    # Margin-based cap - SAFER
    max_notional = available_balance * leverage * 0.5  # 50% of available margin (was 75%)
    
    # Prevent division by zero for entry price
    if entry <= 0:
        logger.warning("Invalid entry price")
        return 0.0
        
    qty_by_margin = max_notional / entry

    qty = min(qty_by_risk, qty_by_margin)

    # Round and validate
    qty = round_step_size(qty, symbol_info['stepSize'])
    if qty < symbol_info['minQty']:
        logger.warning(f"Qty {qty} below minQty {symbol_info['minQty']}")
        return 0.0

    notional = qty * entry
    if notional < symbol_info['minNotional']:
        logger.warning(f"Notional ${notional:.2f} below min ${symbol_info['minNotional']}")
        return 0.0

    return qty

def place_futures_order(signal: dict):
    symbol = signal['symbol']
    side = signal['side'].upper()
    
    leverage = signal.get('leverage')
    if leverage is None or leverage <= 0:
        logger.error(f"Invalid leverage in signal: {leverage}")
        return None
   
    info = get_futures_exchange_info(symbol)
    if not info:
        logger.error(f"Could not get symbol info for {symbol}")
        return None

    available_balance = get_available_balance()
    if available_balance <= 15.0:  # Minimum $15 balance required (was $10)
        logger.error(f"Insufficient balance: ${available_balance:.2f}")
        return None

    # ✅ Use margin-aware position sizing
    qty = calculate_position_size_with_margin_cap(signal, available_balance, leverage, info)
    if qty <= 0:
        logger.warning(f"Position size calculation failed for {symbol}")
        return None

    entry_price = float(signal['entry'])
    notional = qty * entry_price

    # Check if notional is reasonable for scalping
    if notional < 15 or notional > available_balance * 0.2:  # Min $15, Max 20% of balance (was 30%)
        logger.warning(f"Notional ${notional:.2f} outside safe range for {symbol}")
        return None

    set_leverage(symbol, leverage)

    order_side = SIDE_BUY if side == 'BUY' else SIDE_SELL
    close_side = SIDE_SELL if side == 'BUY' else SIDE_BUY

    # Round prices
    entry_price = round(entry_price, info['pricePrecision'])
    tp_price = round(float(signal['take_profit']), info['pricePrecision'])
    sl_price = round(float(signal['stop_loss']), info['pricePrecision'])

    # SAFETY CHECK: Ensure TP and SL are valid
    if side == 'BUY':
        if tp_price <= entry_price or sl_price >= entry_price:
            logger.warning(f"Invalid TP/SL for BUY: TP={tp_price}, Entry={entry_price}, SL={sl_price}")
            return None
    else:  # SELL
        if tp_price >= entry_price or sl_price <= entry_price:
            logger.warning(f"Invalid TP/SL for SELL: TP={tp_price}, Entry={entry_price}, SL={sl_price}")
            return None

    try:
        # ✅ Use MARKET order for immediate execution - BUT with safety
        logger.info(f"Placing MARKET {side} for {symbol} | Qty: {qty} | Leverage: {leverage}x | Notional: ${notional:.2f}")
        
        # First, check if position already exists (safety check)
        try:
            position_info = client.futures_position_information(symbol=symbol)
            for pos in position_info:
                if float(pos['positionAmt']) != 0:
                    logger.warning(f"Position already exists for {symbol}, skipping order")
                    return None
        except:
            pass  # Continue if we can't check existing positions

        # Place entry order (MARKET for immediate execution)
        entry_order = client.futures_create_order(
            symbol=symbol,
            type=ORDER_TYPE_MARKET,
            side=order_side,
            quantity=qty,
            positionSide='BOTH'
        )
        entry_id = entry_order['orderId']
        logger.info(f"Entry market order filled: {entry_id} @ {entry_order['avgPrice']}")

        # Take Profit (MARKET)
        tp_order = client.futures_create_order(
            symbol=symbol,
            type='TAKE_PROFIT_MARKET',
            side=close_side,
            stopPrice=tp_price,
            quantity=qty,
            positionSide='BOTH',
            reduceOnly=True
        )
        tp_id = tp_order['orderId']
        logger.info(f"Take-profit market order placed: {tp_id} @ {tp_price}")

        # Stop Loss (MARKET)
        sl_order = client.futures_create_order(
            symbol=symbol,
            type='STOP_MARKET',
            side=close_side,
            stopPrice=sl_price,
            quantity=qty,
            positionSide='BOTH',
            reduceOnly=True
        )
        sl_id = sl_order['orderId']
        logger.info(f"Stop-loss market order placed: {sl_id} @ {sl_price}")

        logger.info(f"✅ FULL POSITION OPENED: {symbol} | {side} | Qty: {qty} | Notional: ${notional:.2f}")

        # Build the message for the bot
        confirmation_msg = (
            f"🚨 BINANCE - Scalp Signal Detected!\n"
            f"✅ POSITION OPENED\n"
            f"Symbol: {symbol}\n"
            f"Side: {signal['side'].upper()}\n"
            f"Qty: {qty:.6f}\n"
            f"Entry: {signal['entry']:.4f}\n"
            f"TP: {signal['take_profit']:.4f} (MARKET)\n"
            f"SL: {signal['stop_loss']:.4f} (MARKET)\n"
            f"⚠️ Auto-closing on TP/SL hit"
        )
        send_bot_message(int(os.getenv("TELEGRAM_CHAT_ID")), confirmation_msg)

        return {
            'entry_order_id': entry_id,
            'tp_order_id': tp_id,
            'sl_order_id': sl_id,
            'quantity': qty,
            'notional': notional,
            'symbol': symbol,
            'side': side
        }

    except BinanceAPIException as e:
        err_msg = str(e)
        logger.error(f"Error placing orders for {symbol}: {err_msg}")
        if e.code == -2019:
            logger.warning(f"Margin insufficient. Balance=${available_balance:.2f}, Notional=${notional:.2f}, Leverage={leverage}x")
        elif e.code == -1111:
            logger.warning(f"Precision error for {symbol}")
        elif e.code == -2022:
            logger.warning(f"Reduce only error for {symbol}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error placing orders for {symbol}: {e}")
        return None