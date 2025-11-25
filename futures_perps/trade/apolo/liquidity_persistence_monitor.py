import re
import requests
import time

def get_cex_futures_data(symbol: str):
    """
    Fetch real-time futures data from Binance, Bybit, OKX.
    symbol: e.g., 'BTCUSDT' (will map to exchange-specific formats)
    Returns dict with price, volume_1h, funding_rate for each exchange.
    """
    data = {}
    
    # --- BINANCE ---
    try:
        # Price + 1h volume
        ticker = requests.get(f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={symbol}").json()
        # Funding rate (last)
        funding = requests.get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&limit=1").json()
        data['binance'] = {
            'price': float(ticker['lastPrice']),
            'volume_1h': float(ticker['volume']) / 24,  # rough 1h est
            'funding_rate': float(funding[0]['fundingRate']) if funding else 0.0
        }
    except Exception as e:
        data['binance'] = None

    # --- BYBIT ---
    try:
        # Normalize symbol: BTCUSDT -> BTCUSDT (Bybit uses same)
        bybit_symbol = symbol
        # Get tickers
        ticker_url = f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={bybit_symbol}"
        ticker = requests.get(ticker_url).json()
        if ticker['result']['list']:
            t = ticker['result']['list'][0]
            # Get funding
            fund_url = f"https://api.bybit.com/v5/market/funding/history?category=linear&symbol={bybit_symbol}&limit=1"
            fund = requests.get(fund_url).json()
            funding = float(fund['result']['list'][0]['fundingRate']) if fund['result']['list'] else 0.0
            data['bybit'] = {
                'price': float(t['lastPrice']),
                'volume_1h': float(t['turnover24h']) / 24,  # USDT volume
                'funding_rate': funding
            }
    except Exception as e:
        data['bybit'] = None

    # --- OKX ---
    try:
        # OKX uses BTC-USDT-SWAP for futures
        okx_symbol = symbol.replace('USDT', '-USDT-SWAP')
        # Get ticker
        ticker = requests.get(f"https://www.okx.com/api/v5/market/ticker?instId={okx_symbol}").json()
        # Get funding
        funding = requests.get(f"https://www.okx.com/api/v5/public/funding-rate?instId={okx_symbol}").json()
        if ticker['code'] == '0' and funding['code'] == '0':
            t = ticker['data'][0]
            f = funding['data'][0]
            data['okx'] = {
                'price': float(t['last']),
                'volume_1h': float(t['volCcy24h']) / 24,  # USDT volume
                'funding_rate': float(f['fundingRate'])
            }
    except Exception as e:
        data['okx'] = None

    return data

def cross_cex_consensus(symbol: str, tolerance_pct=0.3):
    """
    Returns: 'HIGH', 'MEDIUM', or 'LOW' consensus
    tolerance_pct: max allowed price deviation (e.g., 0.3%)
    """
    data = get_cex_futures_data(symbol)
    
    # Filter out failed exchanges
    valid = {k: v for k, v in data.items() if v is not None}
    if len(valid) < 2:
        return "LOW", data  # not enough data
    
    prices = [v['price'] for v in valid.values()]
    fundings = [v['funding_rate'] for v in valid.values()]
    volumes = [v['volume_1h'] for v in valid.values()]
    
    avg_price = sum(prices) / len(prices)
    max_deviation = max(abs(p - avg_price) / avg_price * 100 for p in prices)
    
    # Check for outlier volume (e.g., one CEX 3x others)
    avg_vol = sum(volumes) / len(volumes)
    vol_ratio = max(volumes) / avg_vol if avg_vol > 0 else 1
    volume_suspicious = vol_ratio > 2.5
    
    # Funding divergence (>0.01 = 1%)
    funding_divergence = (max(fundings) - min(fundings)) > 0.0001  # 0.01% = typical threshold

    if max_deviation <= tolerance_pct and not volume_suspicious and not funding_divergence:
        return "HIGH", data
    elif max_deviation <= 0.6:  # up to 0.6%
        return "MEDIUM", data
    else:
        return "LOW", data

def get_cex_futures_data(symbol: str):
    data = {}
    errors = {}  # ← NEW: track why each exchange failed

    # --- BINANCE ---
    try:
        ticker = requests.get(f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={symbol}", timeout=5).json()
        if "code" in ticker and "msg" in ticker:
            errors['binance'] = f"API error: {ticker['msg']}"
        else:
            funding = requests.get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&limit=1", timeout=5).json()
            data['binance'] = {
                'price': float(ticker['lastPrice']),
                'volume_1h': float(ticker['quoteVolume']) / 24,
                'funding_rate': float(funding[0]['fundingRate']) if funding else 0.0
            }
    except requests.exceptions.Timeout:
        errors['binance'] = "Timeout (exchange slow or down)"
    except requests.exceptions.ConnectionError:
        errors['binance'] = "Connection failed (network or firewall)"
    except KeyError:
        errors['binance'] = "Symbol not found or malformed response"
    except Exception as e:
        errors['binance'] = f"Unexpected error: {str(e)[:50]}"

    # --- BYBIT ---
    try:
        bybit_symbol = symbol
        ticker_url = f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={bybit_symbol}"
        ticker = requests.get(ticker_url, timeout=5).json()
        if ticker.get('retCode') != 0:
            errors['bybit'] = f"API error: {ticker.get('retMsg', 'Unknown')}"
        elif not ticker['result']['list']:
            errors['bybit'] = "Symbol not found"
        else:
            t = ticker['result']['list'][0]
            fund_url = f"https://api.bybit.com/v5/market/funding/history?category=linear&symbol={bybit_symbol}&limit=1"
            fund = requests.get(fund_url, timeout=5).json()
            funding = float(fund['result']['list'][0]['fundingRate']) if fund['result']['list'] else 0.0
            data['bybit'] = {
                'price': float(t['lastPrice']),
                'volume_1h': float(t['turnover24h']) / 24,
                'funding_rate': funding
            }
    except requests.exceptions.Timeout:
        errors['bybit'] = "Timeout (exchange slow or down)"
    except requests.exceptions.ConnectionError:
        errors['bybit'] = "Connection failed (network or firewall)"
    except Exception as e:
        errors['bybit'] = f"Unexpected error: {str(e)[:50]}"

    # --- OKX ---
    try:
        okx_symbol = symbol.replace('USDT', '-USDT-SWAP')
        ticker = requests.get(f"https://www.okx.com/api/v5/market/ticker?instId={okx_symbol}", timeout=5).json()
        if ticker['code'] != '0':
            errors['okx'] = f"API error: {ticker.get('msg', 'Unknown')}"
        else:
            t = ticker['data'][0]
            funding = requests.get(f"https://www.okx.com/api/v5/public/funding-rate?instId={okx_symbol}", timeout=5).json()
            f = funding['data'][0] if funding['code'] == '0' and funding['data'] else {'fundingRate': '0'}
            data['okx'] = {
                'price': float(t['last']),
                'volume_1h': float(t['volCcy24h']) / 24,
                'funding_rate': float(f['fundingRate'])
            }
    except requests.exceptions.Timeout:
        errors['okx'] = "Timeout (exchange slow or down)"
    except requests.exceptions.ConnectionError:
        errors['okx'] = "Connection failed (network or firewall)"
    except Exception as e:
        errors['okx'] = f"Unexpected error: {str(e)[:50]}"

    return data, errors  # ← Return both data AND errors    


def validate_cex_consensus_for_dex_asset(dex_symbol: str, tolerance_pct: float = 0.3) -> dict:
    """
    Validates CEX consensus for a DEX asset (e.g., 'PERP_BTC_USDC').

    Converts: PERP_XYZ_USDC → XYZUSDT

    Returns:
    {
        "consensus": "HIGH" | "MEDIUM" | "LOW" | "NO_CEX_PAIR",
        "reason": str,
        "cex_symbol": str | None,
        "data": dict | None,
        "errors": dict | None
    }
    """
    # --- STEP 1: Convert PERP_BTC_USDC → BTCUSDT generically
    if not isinstance(dex_symbol, str):
        return {
            "consensus": "NO_CEX_PAIR",
            "reason": f"Invalid input type for asset: {type(dex_symbol)}",
            "cex_symbol": None,
            "data": None,
            "errors": None
        }

    # Remove 'PERP_' prefix and '_USDC' suffix in one go
    if dex_symbol.startswith("PERP_") and dex_symbol.endswith("_USDC"):
        base = dex_symbol[5:-5]  # strip "PERP_" and "_USDC"
        if not base or not base.isalpha():
            cex_symbol = None
        else:
            cex_symbol = base + "USDT"
    else:
        cex_symbol = None

    if cex_symbol is None:
        return {
            "consensus": "NO_CEX_PAIR",
            "reason": f"Unrecognized DEX symbol format: '{dex_symbol}'. Expected PERP_XXX_USDC.",
            "cex_symbol": None,
            "data": None,
            "errors": None
        }

    # --- STEP 2: Fetch CEX data
    try:
        cex_data, cex_errors = get_cex_futures_data(cex_symbol)
    except Exception as e:
        return {
            "consensus": "LOW",
            "reason": f"Unexpected error during CEX fetch: {str(e)[:80]}",
            "cex_symbol": cex_symbol,
            "data": None,
            "errors": {"all": str(e)}
        }

    # --- STEP 3: Check responses
    all_exchanges = ['binance', 'bybit', 'okx']
    succeeded = [ex for ex in all_exchanges if ex in cex_data]

    # If no exchange responded
    if len(succeeded) == 0:
        # Heuristic: likely symbol not listed
        symbol_err_keywords = ["symbol", "instrument", "not found", "invalid"]
        not_found_count = sum(
            any(kw in err.lower() for kw in symbol_err_keywords)
            for err in cex_errors.values()
        )
        if not_found_count == len(cex_errors):
            return {
                "consensus": "NO_CEX_PAIR",
                "reason": f"Asset {cex_symbol} not listed on major CEX futures markets",
                "cex_symbol": cex_symbol,
                "data": cex_data,
                "errors": cex_errors
            }
        else:
            return {
                "consensus": "LOW",
                "reason": "No CEX responded (network/API issue)",
                "cex_symbol": cex_symbol,
                "data": cex_data,
                "errors": cex_errors
            }

    if len(succeeded) < 2:
        return {
            "consensus": "LOW",
            "reason": f"Insufficient CEX responses ({len(succeeded)}/3). Requires ≥2 for validation.",
            "cex_symbol": cex_symbol,
            "data": cex_data,
            "errors": cex_errors
        }

    # --- STEP 4: Consensus logic
    valid = {k: v for k, v in cex_data.items() if v is not None}
    prices = [v['price'] for v in valid.values()]
    fundings = [v['funding_rate'] for v in valid.values()]
    volumes = [v['volume_1h'] for v in valid.values()]

    avg_price = sum(prices) / len(prices)
    max_deviation = max(abs(p - avg_price) / avg_price * 100 for p in prices)

    avg_vol = sum(volumes) / len(volumes)
    vol_ratio = max(volumes) / avg_vol if avg_vol > 0 else 1
    volume_suspicious = vol_ratio > 2.5

    funding_divergence = (max(fundings) - min(fundings)) > 0.0001

    if max_deviation <= tolerance_pct and not volume_suspicious and not funding_divergence:
        consensus = "HIGH"
        reason = "Strong price, volume, and funding alignment across CEXs"
    elif max_deviation <= 0.6:
        consensus = "MEDIUM"
        reason = "Moderate price alignment; proceed with caution"
    else:
        consensus = "LOW"
        reason = f"High price divergence ({max_deviation:.2f}%) or suspicious volume/funding"

    return {
        "consensus": consensus,
        "reason": reason,
        "cex_symbol": cex_symbol,
        "data": cex_data,
        "errors": cex_errors
    }
# ===========================================
# MAIN EXECUTION
# ===========================================
if __name__ == "__main__":
    asset = "PERP_DOGE_USDC"  # 🔁 CHANGE THIS TO YOUR ASSET (e.g., "BTCUSDT", "ETHUSDT", "DOGEUSDT")

    # # Fetch data and errors
    # cex_data, cex_errors = get_cex_futures_data(symbol)

    # # Determine success/failure
    # all_exchanges = ['binance', 'bybit', 'okx']
    # succeeded = [ex for ex in all_exchanges if ex in cex_data]
    # failed = [ex for ex in all_exchanges if ex not in succeeded]

    # # Print connectivity report
    # print("📡 Exchange Connectivity Report:")
    # for ex in all_exchanges:
    #     if ex in succeeded:
    #         d = cex_data[ex]
    #         vol_m = d['volume_1h'] / 1_000_000
    #         funding_pct = d['funding_rate'] * 100
    #         print(f"  {ex.upper()}: ✅ OK | Price: ${d['price']:.2f} | Vol(1h): ${vol_m:.1f}M | Funding: {funding_pct:.3f}%")
    #     else:
    #         reason = cex_errors.get(ex, "Unknown error")
    #         print(f"  {ex.upper()}: ❌ FAILED | Reason: {reason}")

    # # Decision logic
    # if len(succeeded) < 2:
    #     print()
    #     if len(succeeded) == 0:
    #         print("💥 CRITICAL: No exchanges responded.")
    #         print("   → Possible causes: network issue, symbol error, or all APIs down.")
    #         print("   → Cannot validate signal. Abort trade.")
    #     else:
    #         only_ex = succeeded[0].upper()
    #         print(f"❌ Skip trade: Only {only_ex} responded — insufficient for cross-validation.")
    #         print("   Why this matters:")
    #         print("   • A single exchange can be manipulated via spoofing, wash trading, or stop hunts.")
    #         print("   • Smart money often pumps one venue to liquidate retail stops, then reverses.")
    #         print("   → Always require confirmation from ≥2 major CEXs before trading.")
    # else:
    #     # Optional: Add consensus analysis here (price alignment, etc.)
    #     print(f"\n✅ {len(succeeded)} exchanges responded. Ready for deeper consensus analysis.")
    #     # You can now call your price divergence logic here if desired.
    cex_check = validate_cex_consensus_for_dex_asset(asset)
    print(f"🔍 CEX Consensus for {asset}: {cex_check['consensus']} | Reason: {cex_check['reason']}")
    