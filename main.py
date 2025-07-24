import ccxt
import pandas as pd
import time
import os
import csv
from datetime import datetime
from ta.momentum import RSIIndicator

# Set this flag for paper trading mode
PAPER_TRADING = True

# Load API keys
api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")

# Safety check: confirm keys exist before live trading
if not PAPER_TRADING:
    if not api_key or not api_secret:
        raise ValueError("API keys not set! Please set BINANCE_API_KEY and BINANCE_API_SECRET environment variables.")

# Connect to Binance (even in paper trading mode for data fetching)
exchange = ccxt.binance({
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True,
})

symbol = 'BTC/USDT'
timeframe = '5m'
rsi_period = 14
balance_pct = 0.1  # 10% of balance per trade
min_trade_usdt = 10  # Minimum USDT value per trade to avoid dust orders

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

def log_trade(direction, amount, price, rsi, simulated=False):
    with open("trade_log.csv", mode="a", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([
            datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            direction,
            f"{amount:.6f}",
            f"{price:.2f}",
            f"{rsi:.2f}",
            "SIMULATED" if simulated else "REAL"
        ])

def place_order(direction, amount, rsi=None):
    price = None
    if PAPER_TRADING:
        # Just simulate the order
        df = fetch_data()
        price = df['close'].iloc[-1]
        print(f"SIMULATED {direction.upper()} {amount:.6f} BTC @ {price:.2f}")
        log_trade(direction, amount, price, rsi, simulated=True)
        return None
    else:
        # Live order placement
        try:
            if direction == 'buy':
                order = exchange.create_market_buy_order(symbol, amount)
            elif direction == 'sell':
                order = exchange.create_market_sell_order(symbol, amount)
            price = order.get('price') or fetch_data()['close'].iloc[-1]
            log_trade(direction, amount, price, rsi, simulated=False)
            print(f"EXECUTED {direction.upper()} {amount:.6f} BTC @ {price:.2f}")
            return order
        except Exception as e:
            print(f"Error placing order: {e}")
            return None

def trade():
    df = fetch_data()
    rsi = get_rsi(df)
    print(f'RSI: {rsi:.2f}')
    if rsi < 30:
        usdt_balance = get_balance('USDT')
        amount_to_spend = usdt_balance * balance_pct
        if amount_to_spend < min_trade_usdt:
            print(f"USDT balance too low to buy (need at least {min_trade_usdt} USDT).")
            return
        price = df['close'].iloc[-1]
        amount = amount_to_spend / price
        print(f'Buying {amount:.6f} BTC')
        place_order('buy', amount, rsi)
    elif rsi > 70:
        btc_balance = get_balance('BTC')
        amount_to_sell = btc_balance * balance_pct
        price = df['close'].iloc[-1]
        if amount_to_sell * price < min_trade_usdt:
            print(f"BTC balance too low to sell (need at least {min_trade_usdt} USDT worth).")
            return
        print(f'Selling {amount_to_sell:.6f} BTC')
        place_order('sell', amount_to_sell, rsi)

def confirm_live_trading():
    response = input("You are about to run live trading. Are you sure? (yes/no): ").strip().lower()
    if response != 'yes':
        print("Live trading cancelled.")
        exit()

if __name__ == "__main__":
    if not PAPER_TRADING:
        confirm_live_trading()
    while True:
        try:
            trade()
            time.sleep(300)  # 5 minutes
        except Exception as e:
            print(f'Error in main loop: {e}')
            time.sleep(60)
