import ccxt
import pandas as pd
import time
from ta.momentum import RSIIndicator

# Your Binance API keys here (DO NOT share)
import os

api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")

# Connect to Binance
exchange = ccxt.binance({
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True,
})

symbol = 'BTC/USDT'
timeframe = '5m'
rsi_period = 14
balance_pct = 0.1  # Use 10% of your balance per trade

def fetch_data():
    bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=100)
    df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    return df

def get_rsi(df):
    rsi = RSIIndicator(close=df['close'], window=rsi_period).rsi()
    return rsi.iloc[-1]

def get_balance(asset='USDT'):
    balance = exchange.fetch_balance()
    return balance[asset]['free']

def place_order(direction, amount):
    if direction == 'buy':
        order = exchange.create_market_buy_order(symbol, amount)
    elif direction == 'sell':
        order = exchange.create_market_sell_order(symbol, amount)
    print(order)

def trade():
    df = fetch_data()
    rsi = get_rsi(df)
    print(f'RSI: {rsi:.2f}')
    if rsi < 30:
        usdt_balance = get_balance('USDT')
        amount_to_spend = usdt_balance * balance_pct
        price = df['close'].iloc[-1]
        amount = amount_to_spend / price
        print(f'Buying {amount:.6f} BTC')
        place_order('buy', amount)
    elif rsi > 70:
        btc_balance = get_balance('BTC')
        amount_to_sell = btc_balance * balance_pct
        print(f'Selling {amount_to_sell:.6f} BTC')
        place_order('sell', amount_to_sell)

# Main loop
while True:
    try:
        trade()
        time.sleep(300)  # Wait 5 minutes
    except Exception as e:
        print(f'Error: {e}')
        time.sleep(60)
