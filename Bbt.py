import os
import time
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta

# Works both on GitHub Secrets AND directly if you run it live
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8751722509:AAEgEjzF2NzBitge_iqhsDUuM35y9FLBF04")
CHAT_ID        = os.environ.get("CHAT_ID", "7298363079")

LOOKBACK        = 25
BODY_MULT       = 1.9   # Slightly tuned so you don't miss valid TradingView signals
VOL_MULT        = 1.5   # Catches early volume expansion before the candle finishes
RANGE_BREAK_LEN = 10
EMA_LEN         = 50
RSI_MAX_BUY     = 76
RSI_MIN_SELL    = 24

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=10).json()
        if not r.get("ok") and not str(CHAT_ID).startswith("-"):
            payload["chat_id"] = f"-{CHAT_ID}"
            requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -1 * delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def scan_once(last_alerted_time=None):
    # Fetch directly from Delta Exchange India BTCUSD Perpetual 5m Candles
    end_ts = int(time.time())
    start_ts = end_ts - (100 * 5 * 60)
    url = f"https://api.india.delta.exchange/v2/history/candles?resolution=5m&symbol=BTCUSD&start={start_ts}&end={end_ts}"
    
    resp = requests.get(url, timeout=10).json()
    candles = resp.get("result", [])
    if not candles:
        return last_alerted_time

    df = pd.DataFrame(candles)
    df = df.sort_values("time").reset_index(drop=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    df["body"]     = (df["close"] - df["open"]).abs()
    df["range"]    = df["high"] - df["low"]
    df["ratio"]    = df.apply(lambda r: r["body"] / r["range"] if r["range"] > 0 else 0, axis=1)
    df["avg_body"] = df["body"].shift(1).rolling(LOOKBACK).mean()
    df["avg_vol"]  = df["volume"].shift(1).rolling(LOOKBACK).mean()
    df["high_10"]  = df["high"].shift(1).rolling(RANGE_BREAK_LEN).max()
    df["low_10"]   = df["low"].shift(1).rolling(RANGE_BREAK_LEN).min()
    df["ema50"]    = df["close"].ewm(span=EMA_LEN, adjust=False).mean()
    df["rsi14"]    = calculate_rsi(df["close"], 14)

    curr = df.iloc[-1]
    c_time = curr["time"]

    if c_time == last_alerted_time:
        return last_alerted_time

    vol_spike = curr["volume"] >= (curr["avg_vol"] * VOL_MULT)
    body_exp  = curr["body"] >= (curr["avg_body"] * BODY_MULT)
    solid_bar = curr["ratio"] >= 0.55

    bull = (curr["close"] > curr["open"]) and body_exp and vol_spike and solid_bar and (curr["close"] > curr["high_10"]) and (curr["close"] > curr["ema50"]) and (curr["rsi14"] < RSI_MAX_BUY)
    bear = (curr["close"] < curr["open"]) and body_exp and vol_spike and solid_bar and (curr["close"] < curr["low_10"]) and (curr["close"] < curr["ema50"]) and (curr["rsi14"] > RSI_MIN_SELL)

    ist_now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    time_str = ist_now.strftime("%I:%M:%S %p")
    expiry_choice = "D2 (Tomorrow 5:30 PM)" if (13 <= ist_now.hour < 17) else "D1 (Current Daily 5:30 PM)"
    atm_strike = int(round(curr["close"] / 200.0) * 200)

    if bull:
        send_telegram(
            f"🚀 <b>DELTA BTC CALL SIGNAL (5m)</b>\n"
            f"🕒 <b>Trigger Time:</b> {time_str} IST\n"
            f"<b>Delta BTC Price:</b> ${curr['close']:,.1f} | <b>RSI:</b> {curr['rsi14']:.1f}\n"
            f"🎯 <b>Buy:</b> C-BTC-{atm_strike}\n"
            f"📅 <b>Expiry:</b> {expiry_choice}"
        )
        return c_time
    elif bear:
        send_telegram(
            f"🩸 <b>DELTA BTC PUT SIGNAL (5m)</b>\n"
            f"🕒 <b>Trigger Time:</b> {time_str} IST\n"
            f"<b>Delta BTC Price:</b> ${curr['close']:,.1f} | <b>RSI:</b> {curr['rsi14']:.1f}\n"
            f"🎯 <b>Buy:</b> P-BTC-{atm_strike}\n"
            f"📅 <b>Expiry:</b> {expiry_choice}"
        )
        return c_time

    return last_alerted_time

# Runs continuously for 4.5 minutes (checking every 5 seconds!) so zero signals are missed
start_run = time.time()
last_alert = None
while time.time() - start_run < 270:
    try:
        last_alert = scan_once(last_alert)
    except Exception as e:
        print(f"Error: {e}")
    time.sleep(5)
    
