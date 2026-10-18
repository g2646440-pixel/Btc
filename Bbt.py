import os
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID        = os.environ.get("CHAT_ID")

SYMBOL          = "BTCUSDT"
INTERVAL        = "5m"
LOOKBACK        = 25
BODY_MULT       = 2.2
VOL_MULT        = 1.8
RANGE_BREAK_LEN = 10
EMA_LEN         = 50
RSI_MAX_BUY     = 74
RSI_MIN_SELL    = 26

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    r = requests.post(url, json=payload, timeout=10).json()
    if not r.get("ok") and not str(CHAT_ID).startswith("-"):
        payload["chat_id"] = f"-{CHAT_ID}"
        requests.post(url, json=payload, timeout=10)

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -1 * delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

url = f"https://data-api.binance.vision/api/v3/klines?symbol={SYMBOL}&interval={INTERVAL}&limit=100"
resp = requests.get(url, timeout=10).json()

df = pd.DataFrame(resp, columns=[
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "qav", "num_trades", "taker_base", "taker_quote", "ignore"
])
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

# Check current and just-closed 5m candle
for idx in [-1, -2]:
    curr = df.iloc[idx]
    vol_spike = curr["volume"] >= (curr["avg_vol"] * VOL_MULT)
    body_exp  = curr["body"] >= (curr["avg_body"] * BODY_MULT)
    solid_bar = curr["ratio"] >= 0.60

    bull = (curr["close"] > curr["open"]) and body_exp and vol_spike and solid_bar and (curr["close"] > curr["high_10"]) and (curr["close"] > curr["ema50"]) and (curr["rsi14"] < RSI_MAX_BUY)
    bear = (curr["close"] < curr["open"]) and body_exp and vol_spike and solid_bar and (curr["close"] < curr["low_10"]) and (curr["close"] < curr["ema50"]) and (curr["rsi14"] > RSI_MIN_SELL)

    ist_now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    expiry_choice = "D2 (Tomorrow 5:30 PM)" if (13 <= ist_now.hour < 17) else "D1 (Current Daily 5:30 PM)"
    atm_strike = int(round(curr["close"] / 200.0) * 200)

    if bull:
        send_telegram(f"🚀 <b>DELTA BTC CALL SIGNAL (5m)</b>\n<b>Spot:</b> ${curr['close']:,.1f} | <b>RSI:</b> {curr['rsi14']:.1f}\n🎯 <b>Buy:</b> C-BTC-{atm_strike}\n📅 <b>Expiry:</b> {expiry_choice}")
        break
    elif bear:
        send_telegram(f"🩸 <b>DELTA BTC PUT SIGNAL (5m)</b>\n<b>Spot:</b> ${curr['close']:,.1f} | <b>RSI:</b> {curr['rsi14']:.1f}\n🎯 <b>Buy:</b> P-BTC-{atm_strike}\n📅 <b>Expiry:</b> {expiry_choice}")
        break
