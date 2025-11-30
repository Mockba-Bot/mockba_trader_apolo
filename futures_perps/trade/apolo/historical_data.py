import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
import threading
import time
from typing import Dict, Optional, List
import requests
import pandas as pd
import numpy as np
from base58 import b58decode
from base64 import urlsafe_b64encode
import urllib.parse
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from logs.log_config import apolo_trader_logger as logger
from dotenv import load_dotenv

load_dotenv()

# ✅ Orderly API Config
BASE_URL = os.getenv("ORDERLY_BASE_URL")
ORDERLY_ACCOUNT_ID = os.getenv("ORDERLY_ACCOUNT_ID")
ORDERLY_SECRET = os.getenv("ORDERLY_SECRET")
ORDERLY_PUBLIC_KEY = os.getenv("ORDERLY_PUBLIC_KEY")

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

# ✅ Initialize Global Rate Limiter
rate_limiter = RateLimiter(max_calls=10, period=1)

base_features = ["close", "high", "low", "volume"]

strategy_features = {
    "5m": {
        "Trend-Following": {"features": base_features + ["ema_12", "ema_26", "macd", "macd_signal", "adx", "vwap"], "force_features": True},
        "Volatility Breakout": {"features": base_features + ["atr_14", "bollinger_hband", "bollinger_lband", "std_20", "vwap"], "force_features": True},
        "Momentum Reversal": {"features": base_features + ["rsi_14", "stoch_k_14", "stoch_d_14", "roc_10", "momentum_10", "vwap"], "force_features": True},
        "Momentum + Volatility": {"features": base_features + ["rsi_14", "atr_14", "bollinger_hband", "bollinger_lband", "roc_10", "momentum_10", "vwap"], "force_features": True},
        "Hybrid": {"features": base_features + ["ema_12", "ema_26", "atr_14", "bollinger_hband", "rsi_14", "macd", "vwap"], "force_features": True},
        "Advanced": {"features": base_features + ["tenkan_sen_9", "kijun_sen_26", "senkou_span_a", "senkou_span_b", "sar", "vwap"], "force_features": True},
        "Router": {"features": ["ema_12", "ema_26", "macd", "macd_signal", "adx", "atr_14", "bollinger_hband", "bollinger_lband", "std_20", "rsi_14", "stoch_k_14", "stoch_d_14", "roc_10", "momentum_10", "tenkan_sen_9", "kijun_sen_26", "senkou_span_a", "senkou_span_b", "sar", "vwap"], "force_features": False}
    },
    "15m": {
        "Trend-Following": {"features": base_features + ["ema_20", "ema_40", "macd", "macd_signal", "adx", "vwap"], "force_features": True},
        "Volatility Breakout": {"features": base_features + ["atr_14", "bollinger_hband", "bollinger_lband", "std_20", "vwap"], "force_features": True},
        "Momentum Reversal": {"features": base_features + ["rsi_14", "stoch_k_14", "stoch_d_14", "roc_14", "momentum_14", "vwap"], "force_features": True},
        "Momentum + Volatility": {"features": base_features + ["rsi_14", "atr_14", "bollinger_hband", "bollinger_lband", "roc_14", "momentum_14", "vwap"], "force_features": True},
        "Hybrid": {"features": base_features + ["ema_20", "ema_40", "atr_14", "bollinger_hband", "rsi_14", "macd", "vwap"], "force_features": True},
        "Advanced": {"features": base_features + ["tenkan_sen_9", "kijun_sen_26", "senkou_span_a", "senkou_span_b", "sar", "vwap"], "force_features": True},
        "Router": {"features": ["ema_20", "ema_40", "macd", "macd_signal", "adx", "atr_14", "bollinger_hband", "bollinger_lband", "std_20", "rsi_14", "stoch_k_14", "stoch_d_14", "roc_14", "momentum_14", "tenkan_sen_9", "kijun_sen_26", "senkou_span_a", "senkou_span_b", "sar", "vwap"], "force_features": False}
    },
    "30m": {
        "Trend-Following": {"features": base_features + ["ema_30", "ema_60", "macd", "macd_signal", "adx", "vwap"], "force_features": True},
        "Volatility Breakout": {"features": base_features + ["atr_14", "bollinger_hband", "bollinger_lband", "std_20", "vwap"], "force_features": True},
        "Momentum Reversal": {"features": base_features + ["rsi_14", "stoch_k_14", "stoch_d_14", "roc_20", "momentum_20", "vwap"], "force_features": True},
        "Momentum + Volatility": {"features": base_features + ["rsi_14", "atr_14", "bollinger_hband", "bollinger_lband", "roc_20", "momentum_20", "vwap"], "force_features": True},
        "Hybrid": {"features": base_features + ["ema_30", "ema_60", "atr_14", "bollinger_hband", "rsi_14", "macd", "vwap"], "force_features": True},
        "Advanced": {"features": base_features + ["tenkan_sen_9", "kijun_sen_26", "senkou_span_a", "senkou_span_b", "sar", "vwap"], "force_features": True},
        "Router": {"features": ["ema_30", "ema_60", "macd", "macd_signal", "adx", "atr_14", "bollinger_hband", "bollinger_lband", "std_20", "rsi_14", "stoch_k_14", "stoch_d_14", "roc_20", "momentum_20", "tenkan_sen_9", "kijun_sen_26", "senkou_span_a", "senkou_span_b", "sar", "vwap"], "force_features": False}
    },
    "1h": {
        "Trend-Following": {"features": base_features + ["ema_20", "ema_50", "macd", "macd_signal", "adx", "vwap"], "force_features": True},
        "Volatility Breakout": {"features": base_features + ["atr_14", "bollinger_hband", "bollinger_lband", "std_20", "vwap"], "force_features": True},
        "Momentum Reversal": {"features": base_features + ["rsi_14", "stoch_k_14", "stoch_d_14", "roc_10", "momentum_10", "vwap"], "force_features": True},
        "Momentum + Volatility": {"features": base_features + ["rsi_14", "atr_14", "bollinger_hband", "bollinger_lband", "roc_10", "momentum_10", "vwap"], "force_features": True},
        "Hybrid": {"features": base_features + ["ema_20", "ema_50", "atr_14", "bollinger_hband", "rsi_14", "macd", "vwap"], "force_features": True},
        "Advanced": {"features": base_features + ["tenkan_sen_9", "kijun_sen_26", "senkou_span_a", "senkou_span_b", "sar", "vwap"], "force_features": True},
        "Router": {"features": ["ema_12", "ema_26", "macd", "macd_signal", "adx", "atr_14", "bollinger_hband", "bollinger_lband", "std_20", "rsi_14", "stoch_k_14", "stoch_d_14", "roc_10", "momentum_10", "tenkan_sen_9", "kijun_sen_26", "senkou_span_a", "senkou_span_b", "sar", "vwap"], "force_features": False}
    },
    "4h": {
        "Trend-Following": {"features": base_features + ["ema_50", "ema_200", "macd", "macd_signal", "adx", "vwap"], "force_features": True},
        "Volatility Breakout": {"features": base_features + ["atr_14", "bollinger_hband", "bollinger_lband", "std_20", "vwap"], "force_features": True},
        "Momentum Reversal": {"features": base_features + ["rsi_14", "stoch_k_14", "stoch_d_14", "roc_10", "momentum_10", "vwap"], "force_features": True},
        "Momentum + Volatility": {"features": base_features + ["rsi_14", "atr_14", "bollinger_hband", "bollinger_lband", "roc_10", "momentum_10", "vwap"], "force_features": True},
        "Hybrid": {"features": base_features + ["ema_50", "ema_200", "atr_14", "bollinger_hband", "rsi_14", "macd", "vwap"], "force_features": True},
        "Advanced": {"features": base_features + ["tenkan_sen_9", "kijun_sen_26", "senkou_span_a", "senkou_span_b", "sar", "vwap"], "force_features": True},
        "Router": {"features": ["ema_12", "ema_26", "macd", "macd_signal", "adx", "atr_14", "bollinger_hband", "bollinger_lband", "std_20", "rsi_14", "stoch_k_14", "stoch_d_14", "roc_10", "momentum_10", "tenkan_sen_9", "kijun_sen_26", "senkou_span_a", "senkou_span_b", "sar", "vwap"], "force_features": False}
    },
    "1d": {
        "Trend-Following": {"features": base_features + ["ema_50", "ema_200", "macd", "macd_signal", "adx", "vwap"], "force_features": True},
        "Volatility Breakout": {"features": base_features + ["atr_14", "bollinger_hband", "bollinger_lband", "std_20", "vwap"], "force_features": True},
        "Momentum Reversal": {"features": base_features + ["rsi_14", "stoch_k_14", "stoch_d_14", "roc_10", "momentum_10", "vwap"], "force_features": True},
        "Momentum + Volatility": {"features": base_features + ["rsi_14", "atr_14", "bollinger_hband", "bollinger_lband", "roc_10", "momentum_10", "vwap"], "force_features": True},
        "Hybrid": {"features": base_features + ["ema_50", "ema_200", "atr_14", "bollinger_hband", "rsi_14", "macd", "vwap"], "force_features": True},
        "Advanced": {"features": base_features + ["tenkan_sen_9", "kijun_sen_26", "senkou_span_a", "senkou_span_b", "sar", "vwap"], "force_features": True},
        "Router": {"features": ["ema_12", "ema_26", "macd", "macd_signal", "adx", "atr_14", "bollinger_hband", "bollinger_lband", "std_20", "rsi_14", "stoch_k_14", "stoch_d_14", "roc_10", "momentum_10", "tenkan_sen_9", "kijun_sen_26", "senkou_span_a", "senkou_span_b", "sar", "vwap"], "force_features": False}
    }
}

def add_indicators(data, required_features):
    """
    Add only the necessary indicators to the data based on the requested features.
    """
    data[['close', 'high', 'low', 'volume']] = data[['close', 'high', 'low', 'volume']].apply(pd.to_numeric)

    # --- EMA ---
    for feature in required_features:
        if feature.startswith("ema_"):
            try:
                window = int(feature.split("_")[1])
                data[feature] = data['close'].ewm(span=window, adjust=False).mean()
            except (IndexError, ValueError):
                logger.warning(f"⚠️ Could not extract window for feature: {feature}")

    # --- MACD ---
    if any(x in required_features for x in ['macd', 'macd_signal']):
        data['ema_12'] = data['close'].ewm(span=12, adjust=False).mean()
        data['ema_26'] = data['close'].ewm(span=26, adjust=False).mean()
        data['macd'] = data['ema_12'] - data['ema_26']
        data['macd_signal'] = data['macd'].ewm(span=9, adjust=False).mean()

    # --- ATR ---
    for feature in required_features:
        if feature.startswith("atr_"):
            try:
                window = int(feature.split("_")[1])
                data['tr'] = pd.concat([
                    data['high'] - data['low'],
                    (data['high'] - data['close'].shift()).abs(),
                    (data['low'] - data['close'].shift()).abs()
                ], axis=1).max(axis=1)
                data[feature] = data['tr'].rolling(window=window).mean()
            except (IndexError, ValueError):
                logger.warning(f"⚠️ Could not extract window for feature: {feature}")

    # --- Bollinger Bands ---
    if any(f in required_features for f in ['bollinger_hband', 'bollinger_lband']):
        window = 20
        data['bollinger_mavg'] = data['close'].rolling(window=window).mean()
        data['bollinger_std'] = data['close'].rolling(window=window).std()
        data['bollinger_hband'] = data['bollinger_mavg'] + (data['bollinger_std'] * 2)
        data['bollinger_lband'] = data['bollinger_mavg'] - (data['bollinger_std'] * 2)

    # --- Standard Deviation ---
    for feature in required_features:
        if feature.startswith("std_"):
            try:
                window = int(feature.split("_")[1])
                data[feature] = data['close'].rolling(window=window).std()
            except (IndexError, ValueError):
                logger.warning(f"⚠️ Could not extract window for feature: {feature}")

    # --- RSI ---
    for feature in required_features:
        if feature.startswith("rsi_"):
            try:
                window = int(feature.split("_")[1])
                delta = data['close'].diff()
                gain = delta.where(delta > 0, 0).rolling(window=window).mean()
                loss = -delta.where(delta < 0, 0).rolling(window=window).mean()
                rs = gain / loss
                data[feature] = 100 - (100 / (1 + rs))
            except (IndexError, ValueError):
                logger.warning(f"⚠️ Could not extract window for feature: {feature}")

    # --- Stochastic Oscillator ---
    stoch_done = set()
    for feature in required_features:
        if feature.startswith("stoch_"):
            try:
                window = int(feature.split("_")[-1])
                if window in stoch_done:
                    continue
                stoch_k = ((data['close'] - data['low'].rolling(window).min()) /
                           (data['high'].rolling(window).max() - data['low'].rolling(window).min())) * 100
                stoch_d = stoch_k.rolling(3).mean()
                data[f'stoch_k_{window}'] = stoch_k
                data[f'stoch_d_{window}'] = stoch_d
                stoch_done.add(window)
            except (IndexError, ValueError):
                logger.warning(f"⚠️ Could not extract window for feature: {feature}")

    # --- Momentum ---
    for feature in required_features:
        if feature.startswith("momentum_"):
            try:
                window = int(feature.split("_")[1])
                data[feature] = data['close'].diff(periods=window)
            except (IndexError, ValueError):
                logger.warning(f"⚠️ Could not extract window for feature: {feature}")

    # --- Rate of Change (ROC) ---
    for feature in required_features:
        if feature.startswith("roc_"):
            try:
                window = int(feature.split("_")[1])
                data[feature] = data['close'].pct_change(periods=window) * 100
            except (IndexError, ValueError):
                logger.warning(f"⚠️ Could not extract window for feature: {feature}")

    # --- ADX ---
    for feature in required_features:
        if feature.startswith("adx"):
            try:
                window = int(feature.split("_")[1]) if "_" in feature else 14
                data['plus_dm'] = data['high'].diff().where(lambda x: x > 0, 0)
                data['minus_dm'] = -data['low'].diff().where(lambda x: x < 0, 0)
                data['tr'] = pd.concat([
                    data['high'] - data['low'],
                    (data['high'] - data['close'].shift()).abs(),
                    (data['low'] - data['close'].shift()).abs()
                ], axis=1).max(axis=1)
                data['plus_di'] = 100 * (data['plus_dm'].rolling(window=window).mean() / data['tr'].rolling(window=window).mean())
                data['minus_di'] = 100 * (data['minus_dm'].rolling(window=window).mean() / data['tr'].rolling(window=window).mean())
                data['dx'] = 100 * abs(data['plus_di'] - data['minus_di']) / (data['plus_di'] + data['minus_di'])
                data[feature] = data['dx'].rolling(window=window).mean()
            except (IndexError, ValueError) as e:
                logger.warning(f"⚠️ ADX error for {feature}: {e}")

    # --- Ichimoku Cloud ---
    for feature in required_features:
        if feature.startswith("tenkan_sen_"):
            try:
                window = int(feature.split("_")[-1])
                data[feature] = (data['high'].rolling(window=window).max() + data['low'].rolling(window=window).min()) / 2
            except (IndexError, ValueError):
                logger.warning(f"⚠️ Could not extract window for feature: {feature}")
        if feature.startswith("kijun_sen_"):
            try:
                window = int(feature.split("_")[-1])
                data[feature] = (data['high'].rolling(window=window).max() + data['low'].rolling(window=window).min()) / 2
            except (IndexError, ValueError):
                logger.warning(f"⚠️ Could not extract window for feature: {feature}")
        if feature.startswith("senkou_span_a"):
            data[feature] = ((data['tenkan_sen_9'] + data['kijun_sen_26']) / 2).shift(26)
        if feature.startswith("senkou_span_b"):
            data[feature] = ((data['high'].rolling(window=52).max() + data['low'].rolling(window=52).min()) / 2).shift(26)

    # --- Parabolic SAR ---
    if 'sar' in required_features:
        data['sar'] = np.nan
        af = 0.02
        max_af = 0.2
        ep = data['high'].iloc[0]
        sar = data['low'].iloc[0]
        trend = 1
        for i in range(1, len(data)):
            prev_sar = sar
            sar = prev_sar + af * (ep - prev_sar)
            if trend == 1:
                if data['low'].iloc[i] < sar:
                    trend = -1
                    sar = ep
                    ep = data['low'].iloc[i]
                    af = 0.02
            else:
                if data['high'].iloc[i] > sar:
                    trend = 1
                    sar = ep
                    ep = data['high'].iloc[i]
                    af = 0.02
            if af < max_af:
                af += 0.02
            data.loc[data.index[i], 'sar'] = sar

    # --- VWAP ---
    if 'vwap' in required_features:
        data['vwap'] = (data['volume'] * (data['high'] + data['low'] + data['close']) / 3).cumsum() / data['volume'].cumsum()

    # Clean NaNs safely (NO backfill to avoid leakage)
    data.replace([np.inf, -np.inf], np.nan, inplace=True)
    data.ffill(inplace=True)
    data.dropna(inplace=True)

    # --- RSI 14 (needed for entropy) ---
    if 'rsi_14' not in data.columns:
        delta = data['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = -delta.where(delta < 0, 0).rolling(14).mean()
        rs = gain / loss
        data['rsi_14'] = 100 - (100 / (1 + rs))


    return data


def get_features_for_strategy(interval, strategy):
    strategy_info = strategy_features.get(interval, {}).get(strategy, {})
    return {
        "interval": interval,
        "strategy": strategy,
        "features": strategy_info.get("features", []),
        "force_features": strategy_info.get("force_features", False)
    }


# ✅ Fetch historical Orderly data with global rate limiting
def get_historical_data_limit_apolo(symbol, interval, limit):
    rate_limiter()  # ✅ Apply global rate limit

    timestamp = str(int(time.time() * 1000))
    params = {"symbol": symbol, "type": interval, "limit": limit}
    path = "/v1/kline"
    query = f"?{urllib.parse.urlencode(params)}"
    message = f"{timestamp}GET{path}{query}"
    signature = urlsafe_b64encode(private_key.sign(message.encode())).decode()

    headers = {
        "orderly-timestamp": timestamp,
        "orderly-account-id": ORDERLY_ACCOUNT_ID,
        "orderly-key": ORDERLY_PUBLIC_KEY,
        "orderly-signature": signature,
    }

    url = f"{BASE_URL}{path}{query}"
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        print(f"❌ Error fetching data for {symbol} {interval}: {response.json()}")
        return None

    data = response.json().get("data", {})
    if not data or "rows" not in data:
        return None

    df = pd.DataFrame(data["rows"])
    required_columns = ["start_timestamp", "open", "high", "low", "close", "volume"]
    if set(required_columns).issubset(df.columns):
        # Convert start_timestamp from ms to datetime
        df["start_time"] = df["start_timestamp"]  # keep raw ms
        df["start_timestamp"] = pd.to_datetime(df["start_timestamp"], unit="ms", utc=True)
        

        # Optional: set index but still keep the columns
        df = df.set_index("start_timestamp", drop=False)

        # Remove duplicates
        df = df[~df.index.duplicated(keep="first")]

        # Keep column order nice
        df = df[["start_time", "start_timestamp", "open", "high", "low", "close", "volume"]]

        # ✅ SORT CHRONOLOGICALLY (OLDEST → NEWEST)
        df = df.reset_index(drop=True).sort_values('start_timestamp').reset_index(drop=True)

        return df
    return None



def get_orderbook(symbol: str, limit: int = 5) -> Dict[str, List[List[str]]]:
    """
    Fetch authenticated order book from Orderly (required for PERP_*_USDC).
    Returns: {"bids": [["price","qty"], ...], "asks": [["price","qty"], ...]}
    """
    rate_limiter()  # ✅ Apply global rate limit

    max_level = min(limit, 500)
    path = f"/v1/orderbook/{symbol}"
    query = f"?max_level={max_level}"

    # Sign the request
    timestamp = str(int(time.time() * 1000))
    message = f"{timestamp}GET{path}{query}"
    signature = urlsafe_b64encode(private_key.sign(message.encode())).decode()

    headers = {
        "orderly-timestamp": timestamp,
        "orderly-account-id": ORDERLY_ACCOUNT_ID,
        "orderly-key": ORDERLY_PUBLIC_KEY,
        "orderly-signature": signature,
    }

    url = f"{BASE_URL}{path}{query}"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return {"bids": [], "asks": []}

        payload = response.json()
        if not payload.get("success") or "data" not in payload:
            return {"bids": [], "asks": []}

        data = payload["data"]
        bids = [[str(b["price"]), str(b["quantity"])] for b in data.get("bids", [])]
        asks = [[str(a["price"]), str(a["quantity"])] for a in data.get("asks", [])]
        return {"bids": bids, "asks": asks}

    except Exception:
        return {"bids": [], "asks": []}

def get_funding_rate_history(symbol: str, limit: int = 1000):
    rate_limiter()
    url = f"{BASE_URL}/v1/public/funding_rate_history"
    r = requests.get(url, params={"symbol": symbol, "limit": limit}, timeout=10)
    r.raise_for_status()
    payload = r.json()
    data = payload.get("data", [])
    # Some endpoints use {'data': {'rows': [...]}}
    if isinstance(data, dict) and "rows" in data:
        return data["rows"]
    return data if isinstance(data, list) else []    

def get_public_liquidations(symbol: str = None, lookback_hours: int = 24):
    """
    Liquidations in a time window. Many APIs require start_t/end_t in ms.
    """
    rate_limiter()
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - int(lookback_hours * 3600 * 1000)
    params = {"start_t": start_ms, "end_t": end_ms}
    if symbol:
        params["symbol"] = symbol
    url = f"{BASE_URL}/v1/public/liquidated_positions"
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json().get("data")
    if isinstance(data, dict):
        # expected shape: {'rows': [...], 'meta': {...}}
        return data.get("rows", [])
    return data or []


# if __name__ == "__main__":
#   # data = fetch_historical_orderly("PERP_BTC_USDC", "30m", limit=80)
#   # current_price = float(data["close"].iloc[-1])
#   #print(current_price)
#   orderbook = get_orderbook("PERP_BTC_USDC", limit=5)
#   print(orderbook)
    # data = get_funding_rate_history("PERP_BTC_USDC", limit=50)
    # # print(data)
    # data =  get_public_liquidations("PERP_BTC_USDC", lookback_hours=24)
    # print(data)