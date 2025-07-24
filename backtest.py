import ccxt
import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange
from ta.trend import MACD
import matplotlib.pyplot as plt
import csv

# --- Settings ---
symbol = 'BTC/USDT'
timeframe = '15m'  # longer timeframe for smoother signals
balance_start = 100  # Starting capital in USDT
trade_fee = 0.001  # 0.1% trading fee
csv_filename = "trade_log.csv"
max_risk_pct = 0.03  # 3% risk per trade, adjustable
max_holding_period = 20  # max holding period in bars (15m per bar => 5 hours)

# --- Helper Functions ---
def timestamp_to_str(ts):
    return pd.to_datetime(ts, unit='ms').strftime('%Y-%m-%d %H:%M')

def max_drawdown(equity_curve):
    peak = equity_curve[0]
    max_dd = 0
    for x in equity_curve:
        if x > peak:
            peak = x
        dd = (peak - x) / peak
        if dd > max_dd:
            max_dd = dd
    return max_dd * 100  # %

def get_position_size(atr_value, balance_usdt, price, max_risk_pct=max_risk_pct):
    dollar_risk = balance_usdt * max_risk_pct
    stop_loss_distance = 2 * atr_value
    if stop_loss_distance == 0:
        return 0
    position_size = dollar_risk / stop_loss_distance
    max_position_size = balance_usdt / price
    return min(position_size, max_position_size)

# --- Fetch Historical Data ---
exchange = ccxt.binance()
all_bars = []
limit = 1000
since = None

for _ in range(5):  # fetch ~5000 bars max
    bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=limit)
    if not bars:
        break
    all_bars.extend(bars)
    if len(bars) < limit:
        break
    since = bars[-1][0] + 1

df = pd.DataFrame(all_bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
df = df.sort_values('timestamp').reset_index(drop=True)

# --- Calculate Indicators ---
df['rsi'] = RSIIndicator(df['close'], window=14).rsi()
df['atr'] = AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()

macd_indicator = MACD(df['close'])
df['macd'] = macd_indicator.macd()
df['macd_signal'] = macd_indicator.macd_signal()

# --- Backtest with Trailing Stop, Max Holding Period, and MACD filter ---
def run_backtest_trailing(
    rsi_buy, rsi_sell,
    use_rsi=True,
    verbose=False,
    trailing_stop=True,
    max_holding_period=max_holding_period
):
    balance_usdt = balance_start
    balance_btc = 0
    trades = []
    buy_price = None
    stop_loss_price = None
    take_profit_price = None
    max_price_since_buy = None
    entry_bar_index = None
    equity_curve = []

    for i in range(len(df)):
        price = df['close'].iloc[i]
        rsi_now = df['rsi'].iloc[i]
        atr_now = df['atr'].iloc[i]
        macd_now = df['macd'].iloc[i]
        macd_signal_now = df['macd_signal'].iloc[i]

        if any(pd.isna(x) for x in [rsi_now, atr_now, macd_now, macd_signal_now]):
            equity_curve.append(balance_usdt + balance_btc * price)
            continue

        cond_rsi = (rsi_now < rsi_buy) if use_rsi else True
        cond_no_pos = (balance_btc == 0)
        cond_macd = macd_now > macd_signal_now  # MACD bullish crossover condition

        if verbose and i % 50 == 0:
            print(f"{i}: Price={price:.2f}, RSI={rsi_now:.2f}, MACD={macd_now:.4f}, Signal={macd_signal_now:.4f}")
            print(f"Conditions -> RSI<{rsi_buy}: {cond_rsi}, No Position: {cond_no_pos}, MACD Bullish: {cond_macd}")

        # Entry
        if cond_no_pos and cond_rsi and cond_macd:
            position_size = get_position_size(atr_now, balance_usdt, price)
            if position_size <= 0:
                equity_curve.append(balance_usdt + balance_btc * price)
                continue

            amount = position_size * price
            fee = amount * trade_fee
            total_cost = amount + fee

            if total_cost > balance_usdt:
                amount = balance_usdt / (1 + trade_fee)
                position_size = amount / price
                total_cost = amount * (1 + trade_fee)

            balance_btc += position_size
            balance_usdt -= total_cost
            trades.append([df['timestamp'].iloc[i], 'BUY', price, position_size])

            buy_price = price
            stop_loss_price = price - 3 * atr_now
            take_profit_price = price + 6 * atr_now
            max_price_since_buy = price
            entry_bar_index = i

            if verbose:
                print(f"BUY @ {price:.2f}, position_size={position_size:.6f}")

        # Manage position
        elif balance_btc > 0:
            # Update trailing stop
            if trailing_stop and price > max_price_since_buy:
                max_price_since_buy = price
                new_stop = max_price_since_buy - 3 * atr_now
                if new_stop > stop_loss_price:
                    if verbose:
                        print(f"Updating trailing stop from {stop_loss_price:.2f} to {new_stop:.2f}")
                    stop_loss_price = new_stop

            sell_cond_rsi = (rsi_now > rsi_sell) if use_rsi else False
            sell_cond_sl = (price <= stop_loss_price) if stop_loss_price else False
            sell_cond_tp = (price >= take_profit_price) if take_profit_price else False
            sell_cond_time = (i - entry_bar_index) >= max_holding_period

            if sell_cond_rsi or sell_cond_sl or sell_cond_tp or sell_cond_time:
                proceeds = balance_btc * price
                fee = proceeds * trade_fee
                proceeds_after_fee = proceeds - fee
                trades.append([df['timestamp'].iloc[i], 'SELL', price, balance_btc])
                balance_usdt += proceeds_after_fee
                balance_btc = 0
                buy_price = stop_loss_price = take_profit_price = max_price_since_buy = None
                entry_bar_index = None

                if verbose:
                    reason = 'RSI Sell' if sell_cond_rsi else ('Stop Loss' if sell_cond_sl else ('Take Profit' if sell_cond_tp else 'Max Holding Period'))
                    print(f"SELL @ {price:.2f} due to {reason}")

        equity_curve.append(balance_usdt + balance_btc * price)

    final_value = balance_usdt + balance_btc * df['close'].iloc[-1]
    profit_pct = (final_value - balance_start) / balance_start * 100
    max_dd = max_drawdown(equity_curve)

    # Write trades log to CSV
    with open(csv_filename, mode="a", newline="") as file:
        writer = csv.writer(file)
        for t in trades:
            timestamp_str = timestamp_to_str(t[0])
            writer.writerow([timestamp_str, t[1], f"{t[2]:.2f}", f"{t[3]:.6f}"])

    return {
        'rsi_buy': rsi_buy,
        'rsi_sell': rsi_sell,
        'final_balance': final_value,
        'profit_pct': profit_pct,
        'max_drawdown_pct': max_dd,
        'trades_count': len([t for t in trades if t[1] in ('BUY', 'SELL')]),
        'equity_curve': equity_curve,
    }

# --- Clear CSV Before Start ---
with open(csv_filename, mode="w", newline="") as file:
    writer = csv.writer(file)
    writer.writerow(['Timestamp', 'Trade_Type', 'Price', 'Amount'])

# --- Run Grid Search (RSI + MACD filter) ---
results = []

for rsi_buy in range(30, 50, 5):
    for rsi_sell in range(50, 75, 5):
        result = run_backtest_trailing(
            rsi_buy=rsi_buy,
            rsi_sell=rsi_sell,
            use_rsi=True,
            verbose=True,
            trailing_stop=True,
            max_holding_period=max_holding_period
        )

        print(f"RSI Buy {rsi_buy}, RSI Sell {rsi_sell} | "
              f"Final {result['final_balance']:.2f} USDT | Profit {result['profit_pct']:.2f}% | "
              f"Max DD {result['max_drawdown_pct']:.2f}% | Trades {result['trades_count']}")
        results.append(result)

# --- Show Best Result ---
best = max(results, key=lambda x: x['profit_pct'])
print("\nBest Result:")
print(f"RSI Buy: {best['rsi_buy']}, RSI Sell: {best['rsi_sell']}, Final Balance: {best['final_balance']:.2f} USDT, "
      f"Profit: {best['profit_pct']:.2f}%, Max Drawdown: {best['max_drawdown_pct']:.2f}%, Trades: {best['trades_count']}")

# --- Plot Equity Curve ---
plt.figure(figsize=(12, 6))
plt.plot(best['equity_curve'], label='Equity Curve')
plt.title('Equity Curve of Best RSI+MACD Strategy')
plt.xlabel('Time Steps')
plt.ylabel('Balance (USDT)')
plt.grid(True)
plt.legend()
plt.show()
