# Porky Choppy

An automated futures trading system: a live trading bot plus the backtesting research
that informed its strategy. Built for trading on [TopstepX](https://www.topstepx.com/)
using real-time market data and a REST order API.

## How it works

The bot watches 1-minute candles for a contract and looks for a simple breakout/reversion
pattern:

1. Wait for two consecutive candles in the same direction (a short "streak").
2. Wait for the first candle that breaks that direction (a reversal).
3. Enter at the breaking candle's mid-price, with a bracket take-profit order set back
   toward the price where the streak started.

`live/trade.py` implements this end-to-end: it authenticates with TopstepX, opens a
SignalR connection for real-time trade ticks, builds 1-minute bars from the tick stream,
evaluates the signal on every new bar, and places a bracket limit order when a valid
setup appears. `live/order_monitor_clearing.py` runs alongside it as a safety net —
it polls for open positions and force-flattens them (cancelling any resting orders)
once a configured UTC cutoff time is reached, so nothing gets held into a session it
shouldn't be.

## Repo layout

```
live/
  trade.py                   # Live trading bot (signal detection + order placement)
  order_monitor_clearing.py  # Force-exit/cancel positions at a cutoff time

research/
  pig/                        # Lean hogs (HE) futures research
    pig_strategy_v2.py         # Backtest of the candle-streak breakout/reversion signal
    gap_reversion_backtest.py  # Backtest of an overnight-gap mid-price reversion signal
    PIGS_2016-05-01_to_2026-05-01.parquet   # Historical 1-min OHLCV data
    le_strategy_results.csv                 # Output of pig_strategy_v2.py
    pig_mid_reversion_strategy.xlsx         # Output of gap_reversion_backtest.py

  gold/                        # Gold (GC) futures research
    gold_strategy_rth.py       # Same signal, restricted to the RTH session
    gold_strategy_eth.py       # Same signal, parameterized across sessions (Asia/London/RTH/post-RTH/full ETH)
    ema_gap_analyzer.py        # EMA gap/slope feature exploration
    download_gold_data.py      # Pulls historical 1-min OHLCV from Databento
    GC-futures-ohlcv-01-01-2021-to-14-05-2026.parquet
    gc_strategy_results_*.csv  # One result set per session, produced by gold_strategy_eth.py
```

The `research/` scripts were how the live signal got validated before it was wired up
to real order placement — each one backtests a variant of the breakout/reversion idea
against historical data and reports win rate, profit factor, and P&L in ticks.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your TopstepX and Databento credentials
```

Required environment variables (see `.env.example`):

| Variable | Purpose |
|---|---|
| `PROJECT_X_API_KEY` | TopstepX API key |
| `PROJECT_X_USERNAME` | TopstepX username |
| `PROJECT_X_ACCOUNT_ID` | TopstepX account ID to trade/monitor |
| `DATABENTO_API_KEY` | Databento API key, only needed to re-download historical data |

Run the bot:

```bash
python live/trade.py
python live/order_monitor_clearing.py   # in a separate process
```

Run a backtest (from inside its folder, since results are written to the current
directory):

```bash
cd research/pig
python pig_strategy_v2.py
```

## Disclaimer

This places real orders against a live brokerage account when run. It's shared as a
portfolio project to show the strategy research and trading infrastructure, not as
financial advice or a ready-to-run product.
