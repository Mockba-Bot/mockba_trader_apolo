from decimal import ROUND_UP, Decimal
import os
import math
import json
import threading
import time
from dotenv import load_dotenv
import redis
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests
import websockets
from trading_bot.send_bot_message import send_bot_message
from base58 import b58decode
from base64 import urlsafe_b64encode
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


from logs.log_config import apolo_trader_logger as logger

load_dotenv()

# ✅ Orderly API Config
BASE_URL = os.getenv("ORDERLY_BASE_URL")
ORDERLY_ACCOUNT_ID = os.getenv("ORDERLY_ACCOUNT_ID")
ORDERLY_SECRET = os.getenv("ORDERLY_SECRET")
ORDERLY_PUBLIC_KEY = os.getenv("ORDERLY_PUBLIC_KEY")
MAX_WORKERS = int(os.getenv("MAX_WORKERS", 10))
DEEP_SEEK_API_KEY = os.getenv("DEEP_SEEK_API_KEY")
WSS_BASE = "wss://ws-private-evm.orderly.org/v2/ws/private/stream"

if not ORDERLY_SECRET or not ORDERLY_PUBLIC_KEY:
    raise ValueError("❌ ORDERLY_SECRET or ORDERLY_PUBLIC_KEY environment variables are not set!")

# ✅ Remove "ed25519:" prefix if present in private key
if ORDERLY_SECRET.startswith("ed25519:"):
    ORDERLY_SECRET = ORDERLY_SECRET.replace("ed25519:", "")

# ✅ Decode Base58 Private Key
private_key = Ed25519PrivateKey.from_private_bytes(b58decode(ORDERLY_SECRET))


# ✅ Rate limiter (Ensures max 8 API requests per second globally)
class RateLimiter:
    def __init__(self, max_calls, period):
        self.max_calls = max_calls
        self.period = period
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self):
        with self.lock:
            now = time.time()
            self.calls = [call for call in self.calls if call > now - self.period]
            if len(self.calls) >= self.max_calls:
                sleep_time = self.period - (now - self.calls[0])
                print(f"⏳ Rate limit reached! Sleeping for {sleep_time:.2f} seconds...")
                time.sleep(sleep_time)
            self.calls.append(time.time())
            
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

# Risk parameters - SAFER VALUES
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "0.3"))  # Reduced to 0.3%

# Helpers
def round_down_to_tick(value: float, tick: float) -> float:
    return float((Decimal(value) // Decimal(str(tick))) * Decimal(str(tick)))

def round_up_to_tick(value: float, tick: float) -> float:
    return float((Decimal(value) / Decimal(str(tick))).to_integral_value(rounding=ROUND_UP) * Decimal(str(tick)))


def get_confidence_level(confidence: float) -> str:
    if confidence >= 3.0:  # STRONGER thresholds
        return "🚀 VERY STRONG"
    elif confidence >= 2.0:
        return "💪 STRONG"
    elif confidence >= 1.8:
        return "👍 MODERATE"
    else:
        return "⚠️ WEAK"

def get_close_price(wallet_address: str, symbol: str = "PERP_NEAR_USDC"):
    url = f"wss://ws-evm.orderly.org/ws/stream/{wallet_address}"
    topic = f"{symbol}@ticker"

    try:
        with websockets.connect(url, ping_interval=15) as ws:
            # Subscribe to ticker topic
                ws.send(json.dumps({
                "id": "clientID4",
                "topic": topic,
                "event": "subscribe"
            }))

            # print(f"📡 Subscribed to {topic}. Waiting for ticker data...")

        while True:
            raw = ws.recv()
            msg = json.loads(raw)

            if msg.get("topic") == topic and "data" in msg:
                close_price = msg["data"].get("close")
                # print(f"✅ Close price for {symbol}: {close_price}")
                return close_price  # or process/send elsewhere

    except Exception as e:
        print(f"❌ Error: {e}")
        return None
    
def get_futures_exchange_info(symbol: str):
    """
    Fetch asset info from Orderly API including quantity precision, margin, and liquidation parameters.
    Does NOT use Redis for caching.
    """
    path = f"/v1/public/info/{symbol}"  # Include query string
    url = f"{BASE_URL}{path}"

    try:
        response = requests.get(url, timeout=10)
    except requests.exceptions.RequestException as e:
        print(f"❌ Request error: {e}")
        return None

    if response.status_code == 200:
        data = response.json().get("data", {})
        return {
            "base_mmr": data.get("base_mmr", 0.05),
            "base_imr": data.get("base_imr", 0.1),
            "imr_factor": data.get("imr_factor", 0.00000208),
            "funding_period": data.get("funding_period", 8),
            "cap_funding": data.get("cap_funding", 0.0075),
            "std_liquidation_fee": data.get("std_liquidation_fee", 0.024),
            "liquidator_fee": data.get("liquidator_fee", 0.012),
            "min_notional": data.get("min_notional", 10),
            "quote_max": data.get("quote_max", 100000),

            # ✅ Precision-relevant fields
            "base_tick": data.get("base_tick", 0.01),
            "base_min": data.get("base_min", 0.0),
            "base_max": data.get("base_max", float("inf")),
            "quote_tick": data.get("quote_tick", 0.01),
        }
    else:
        raise Exception(f"Failed to fetch asset info for {symbol} - Status code: {response.status_code}")

def get_available_balance(orderly_secret, orderly_account_id, orderly_public_key) -> float:
    # Convert the orderly_secret string to Ed25519PrivateKey object
    if orderly_secret.startswith("ed25519:"):
        orderly_secret = orderly_secret.replace("ed25519:", "")
    private_key = Ed25519PrivateKey.from_private_bytes(b58decode(orderly_secret))

    timestamp = str(int(time.time() * 1000))
    path = "/v1/positions"

    # Get first and last day of current month
    # first_day_of_month = time.strftime("%Y-%m-01")
    # last_day_of_month = time.strftime("%Y-%m-%d")

    # params = {
    #     "page": 1,
    #     "page_size": 1,
    #     "start_date": first_day_of_month,
    #     "end_date": last_day_of_month
    # }

    message = f"{timestamp}GET{path}"
    signature = urlsafe_b64encode(private_key.sign(message.encode())).decode()

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "orderly-timestamp": timestamp,
        "orderly-account-id": orderly_account_id,
        "orderly-key": orderly_public_key,
        "orderly-signature": signature,
    }

    url = f"{BASE_URL}{path}"

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        # get from data free_collateral
        if data.get("success") and "data" in data:
            free_collateral = data["data"].get("free_collateral", 0.0)
            # print(f"✅ Free collateral: {free_collateral}")

            return free_collateral
        else:
            print("⚠️ No data rows found.")
            return None

    except requests.exceptions.HTTPError as err:
        print(f"❌ HTTP error: {err.response.status_code} - {err.response.text}")
    except Exception as e:
        print(f"❌ General error: {e}")
    return None


def round_step_size(quantity: float, step_size: float) -> float:
    if step_size <= 0:
        return quantity
    precision = max(0, int(round(-math.log(step_size, 10), 0)))
    return round(quantity - (quantity % step_size), precision)

def calculate_position_size_with_margin_cap(
    signal: dict,
    available_balance: float,
    leverage: int,
    asset_info: dict  # renamed from symbol_info for clarity
) -> float:
    """
    Calculate position size with margin cap using asset_info fields:
    - base_tick → step size
    - min_notional → minimum trade notional
    - base_imr → implied max leverage = 1 / base_imr
    """
    entry = float(signal['entry'])
    sl = float(signal['stop_loss'])
    # side = signal['side'].upper()

    # Validate leverage against asset's IMR
    max_allowed_leverage = int(1 / asset_info['base_imr']) if asset_info['base_imr'] > 0 else 1
    if leverage > max_allowed_leverage:
        logger.warning(f"Leverage {leverage}x exceeds max allowed {max_allowed_leverage}x. Capping.")
        leverage = max_allowed_leverage

    risk_amount = available_balance * (RISK_PER_TRADE_PCT / 100)
    risk_per_unit = abs(entry - sl)

    if risk_per_unit <= 0:
        logger.warning("Invalid stop loss placement")
        return 0.0

    if risk_per_unit < 1e-10:
        logger.warning("Risk per unit too small, skipping trade")
        return 0.0

    qty_by_risk = risk_amount / risk_per_unit

    # Margin cap: use only a portion of available buying power (50% for safety)
    max_notional = available_balance * leverage * 0.5
    if entry <= 0:
        logger.warning("Invalid entry price")
        return 0.0
    qty_by_margin = max_notional / entry

    qty = min(qty_by_risk, qty_by_margin)

    # Round to base_tick (step size)
    step_size = asset_info['base_tick']
    qty = round_step_size(qty, step_size)

    # Enforce min base quantity
    if qty < asset_info['base_min']:
        logger.warning(f"Qty {qty} below min base quantity {asset_info['base_min']}")
        return 0.0

    # Enforce min notional value
    notional = qty * entry
    if notional < asset_info['min_notional']:
        logger.warning(f"Notional ${notional:.2f} below min ${asset_info['min_notional']}")
        return 0.0

    # Optional: enforce max notional (quote_max)
    if notional > asset_info['quote_max']:
        logger.warning(f"Notional ${notional:.2f} exceeds max ${asset_info['quote_max']}")
        # Optionally cap or reject
        return 0.0

    return qty

rate_limiter = RateLimiter(max_calls=10, period=1)
def place_futures_order(signal: dict):
    """
    Creates and submits a BRACKET order with TAKE_PROFIT and STOP_LOSS child orders.
    """
    rate_limiter()  # ✅ global rate limit

    symbol = signal['symbol']
    side = signal['side'].upper()

    asset_info = get_futures_exchange_info(symbol)
    if not asset_info:
        logger.error(f"❌ Failed to fetch asset info for {symbol}")
        return
    
    quote_tick = float(asset_info["quote_tick"] or 0.0)
    base_tick  = float(asset_info["base_tick"]  or 0.0)
    min_notional = float(asset_info.get("min_notional", 10.0))

    if quote_tick <= 0 or base_tick <= 0:
        logger.error(f"❌ Invalid tick sizes for {symbol}: quote_tick={quote_tick}, base_tick={base_tick}")
        return

    # FIX: Calculate decimal precision from tick size
    def get_precision_from_tick(tick_size: float) -> int:
        """Convert tick size to decimal precision for rounding"""
        if tick_size <= 0:
            return 2
        tick_str = f"{tick_size:.10f}"
        if '.' in tick_str:
            # Count decimal places, ignoring trailing zeros
            return len(tick_str.split('.')[1].rstrip('0'))
        return 0

    quote_precision = get_precision_from_tick(quote_tick)
    base_precision = get_precision_from_tick(base_tick)

    # FIX: Use proper precision for rounding
    tp_price = round(float(signal['take_profit']), quote_precision)
    sl_price = round(float(signal['stop_loss']), quote_precision)

    leverage = signal.get('leverage')
    if leverage is None or leverage <= 0:
        logger.error(f"Invalid leverage in signal: {leverage}")
        return None

    orderly_account_id = ORDERLY_ACCOUNT_ID
    orderly_secret     = ORDERLY_SECRET
    orderly_public_key = ORDERLY_PUBLIC_KEY

    balance = get_available_balance(orderly_secret, orderly_account_id, orderly_public_key)
    if balance is None or balance < 5.0:
        logger.error(f"❌ Insufficient balance. Balance: {balance}")

    # Key
    raw_key = b58decode(orderly_secret.replace("ed25519:", ""))
    if len(raw_key) == 64:
        raw_key = raw_key[:32]
    private_key = Ed25519PrivateKey.from_private_bytes(raw_key)

    # --- Current price ---
    live_price = float(get_close_price(orderly_account_id, symbol))
    if live_price <= 0:
        logger.error(f"❌ Invalid live price for {symbol}: {live_price}")

    # --- Normalize side ---
    if isinstance(side, int):
        signal_val = int(side)
        side_str = "BUY" if signal_val == 1 else "SELL"
    else:
        side_str = side.upper()
        signal_val = 1 if side_str == "BUY" else -1

    # FIX: Use tick-based rounding functions
    def nudge_up(px):   # ensures '>' current price
        return round_up_to_tick(px + quote_tick, quote_tick)
    def nudge_down(px): # ensures '<' current price
        return round_down_to_tick(px - quote_tick, quote_tick)

    # --- Compute TP/SL triggers ---
    if signal_val == 1:
        # LONG entry (BUY). Exit side is SELL.
        opposite_side = "SELL"
        sl_trigger = sl_price
        tp_trigger = tp_price
        # ensure strict inequalities:
        if sl_trigger >= live_price:
            sl_trigger = nudge_down(live_price)
        if tp_trigger <= live_price:
            tp_trigger = nudge_up(live_price)
    else:
        # SHORT entry (SELL). Exit side is BUY.
        opposite_side = "BUY"
        sl_trigger = sl_price
        tp_trigger = tp_price
        # ensure strict inequalities:
        if sl_trigger <= live_price:
            sl_trigger = nudge_up(live_price)
        if tp_trigger >= live_price:
            tp_trigger = nudge_down(live_price)

    # --- Position sizing ---
    qty = calculate_position_size_with_margin_cap(signal, balance, leverage, asset_info)
    if qty <= 0:
        logger.warning(f"Position size calculation failed for {symbol}")
        return None

    # FIX: Use proper precision for quantity rounding
    qty = round(qty, base_precision)

    # FIRST: Check if the raw quantity would meet minimum notional
    raw_notional = live_price * qty
    if raw_notional < min_notional:
        # Calculate the minimum quantity needed to meet min_notional
        min_qty = min_notional / live_price
        qty = round(min_qty, base_precision)
        logger.info(f"🔄 Adjusted quantity to meet minimum notional: {qty:.6f}")

    # THEN: Round to the base tick
    qty = round_down_to_tick(qty, base_tick)

    # FINAL: Check if the rounded quantity still meets minimum
    order_notional = live_price * qty
    if order_notional < min_notional:
        # If rounding made it too small, round UP instead
        qty = round_up_to_tick(qty, base_tick)
        order_notional = live_price * qty
        logger.info(f"🔄 Rounded up to meet minimum: qty={qty:.6f}, notional={order_notional:.2f}")

    # Final safety check
    if qty <= 0 or order_notional < min_notional:
        logger.error(
            f"❌ Cannot meet minimum notional after adjustments (need ≥ {min_notional}, got {order_notional:.2f}). "
            f"(price={live_price:.6f}, qty={qty}, lev={leverage}, balance={balance})"
        )
        return None

    payload = {
        "symbol": symbol,
        "algo_type": "BRACKET",
        "quantity": qty,
        "side": side_str,
        "type": "MARKET",
        "child_orders": [
            {
                "symbol": symbol,
                "algo_type": "POSITIONAL_TP_SL",
                "child_orders": [
                    {
                        "symbol": symbol,
                        "algo_type": "TAKE_PROFIT",
                        "side": opposite_side,
                        "type": "CLOSE_POSITION",
                        "trigger_price": tp_trigger,
                        "trigger_price_type": "MARK_PRICE",
                        "reduce_only": True
                    },
                    {
                        "symbol": symbol,
                        "algo_type": "STOP_LOSS",
                        "side": opposite_side,
                        "type": "CLOSE_POSITION",
                        "trigger_price": sl_trigger,
                        "trigger_price_type": "MARK_PRICE",
                        "reduce_only": True
                    }
                ]
            }
        ]
    }

    # --- Sign & send ---
    timestamp = str(int(time.time() * 1000))
    path = "/v1/algo/order"
    body = json.dumps(payload, separators=(",", ":"))  # compact
    message = f"{timestamp}POST{path}{body}"
    signature = urlsafe_b64encode(private_key.sign(message.encode())).decode()

    headers = {
        "Content-Type": "application/json",
        "orderly-timestamp": timestamp,
        "orderly-account-id": orderly_account_id,
        "orderly-key": orderly_public_key,
        "orderly-signature": signature,
        "Accept": "application/json"
    }

    url = f"{BASE_URL}{path}"
    max_retries = 2
    for attempt in range(max_retries):
        try:
            response = requests.post(url, data=body, headers=headers, timeout=10)
            if response.status_code == 200:
                break
            elif "trigger price" in response.text.lower():
                # Price moved - refresh and retry
                logger.info(f"🔄 Price changed, retrying {attempt+1}/{max_retries}")
                live_price = float(get_close_price(orderly_account_id, symbol))
                # Recalculate TP/SL and retry
                continue
        except Exception as e:
            logger.error(f"❌ Request error: {e}")

    if response.status_code != 200:
        # Log full error (often includes the -1103 details)
        try:
            logger.error(f"❌ Error creating order: {response.json()}")
        except Exception:
            logger.error(f"❌ Error creating order: status={response.status_code}, text={response.text}")

    # Success: mark open + store order id
    rows = response.json().get("data", {}).get("rows", [])
    positional_tp_sl = next((row for row in rows if row.get("algo_type") == "POSITIONAL_TP_SL"), {})
    order_id = positional_tp_sl.get("order_id", "0")

    msg = (
        f"✅ Order created: {symbol}\n"
        f"Side: {side_str}\n"
        f"Lev: {round(leverage, 2)}x\n"
        f"Qty: {round(qty, 4)}\n"
        f"Price: {round(live_price, 4)}\n"
        f"TP trigger: {round(tp_trigger, 4)}\n"
        f"SL trigger: {round(sl_trigger, 4)}\n"
        f"Notional: {round(order_notional, 2)}\n"
        f"Order ID: {order_id}"
    )
    send_bot_message(int(os.getenv("TELEGRAM_CHAT_ID")), msg)
    logger.info(f"✅ Order created for {symbol} | {side_str} lev={leverage} qty={qty} @~{live_price} | TP={tp_trigger} SL={sl_trigger}")


def get_user_statistics():
    orderly_account_id = ORDERLY_ACCOUNT_ID
    orderly_secret     = ORDERLY_SECRET
    orderly_public_key = ORDERLY_PUBLIC_KEY

    if orderly_secret.startswith("ed25519:"):
        orderly_secret = orderly_secret.replace("ed25519:", "")
    private_key = Ed25519PrivateKey.from_private_bytes(b58decode(orderly_secret))

    timestamp = str(int(time.time() * 1000))
    path = "/v1/positions"
    message = f"{timestamp}GET{path}"
    signature = urlsafe_b64encode(private_key.sign(message.encode())).decode()

    headers = {
        "orderly-timestamp": timestamp,
        "orderly-account-id": orderly_account_id,
        "orderly-key": orderly_public_key,
        "orderly-signature": signature,
    }

    url = f"{BASE_URL}{path}"

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("success") and "data" in data:
            positions = data["data"].get("rows", [])
            open_positions = [p for p in positions if p.get("position_qty", 0) != 0]
            count = len(open_positions)
            return count
        else:
            print("⚠️ No position data returned.")
            return 0

    except Exception as e:
        print(f"❌ Error fetching positions: {e}")
        return 0

# if __name__ == "__main__":
#     asset_info = get_user_statistics()
#     print(asset_info)    