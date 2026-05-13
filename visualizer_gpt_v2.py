import pandas as pd
import numpy as np

# =========================
# CONFIG
# =========================

FILENAME = "PIGS_2016-05-01_to_2026-05-01.parquet"

START_DATE = "2025-05-01"
END_DATE = "2026-05-01"

TICK_SIZE = 0.0025

OUTPUT_FILE = "pig_mid_reversion_strategy.xlsx"

CONVERT_TO_NEW_YORK = True
TIMEZONE = "America/New_York"

# Mid-price definition:
# "hl" = (high + low) / 2
# "oc" = (open + close) / 2
MID_MODE = "oc"

# Require that TP is profitable if reached
# short requires entry > take_profit
# long requires entry < take_profit
SKIP_INVALID_TARGET_TRADES = True


# =========================
# LOAD DATA
# =========================

df = pd.read_parquet(FILENAME)

df.index = pd.to_datetime(df.index)
df = df.sort_index()

if CONVERT_TO_NEW_YORK:
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC").tz_convert(TIMEZONE)
    else:
        df.index = df.index.tz_convert(TIMEZONE)

df = df.loc[START_DATE:END_DATE].copy()

if MID_MODE == "hl":
    df["mid"] = (df["high"] + df["low"]) / 2
elif MID_MODE == "oc":
    df["mid"] = (df["open"] + df["close"]) / 2
else:
    raise ValueError("MID_MODE must be either 'hl' or 'oc'")

df["session_date"] = df.index.date


# =========================
# BUILD DAILY SESSION ROWS
# =========================

daily_rows = []

for session_date, day_df in df.groupby("session_date"):
    day_df = day_df.sort_index()

    if day_df.empty:
        continue

    daily_rows.append({
        "session_date": session_date,
        "session_open_close": day_df["close"].iloc[0],
        "session_open_open": day_df["open"].iloc[0],
        # Current session first mid price
        "session_open_mid": day_df["mid"].iloc[0],

        # Current session final mid price
        "session_close_mid": day_df["mid"].iloc[-1],

        "open_time": day_df.index[0],
        "session_end_time": day_df.index[-1],
        "bars": len(day_df),
        "day_df": day_df,
    })

daily = pd.DataFrame(daily_rows)

# Previous session final mid price
daily["prev_session_close_mid"] = daily["session_close_mid"].shift(1)


# =========================
# STRATEGY ANALYSIS
# =========================

results = []
cum_pnl_ticks = 0.0

for _, row in daily.iterrows():
    day_df = row["day_df"]

    session_date = row["session_date"]
    session_open_mid = row["session_open_mid"]
    session_open_close = row["session_open_close"]
    session_open_open = row["session_open_open"]
    session_close_mid = row["session_close_mid"]
    prev_session_close_mid = row["prev_session_close_mid"]
    open_time = row["open_time"]
    session_end_time = row["session_end_time"]
    bars = row["bars"]

    open_gap = np.nan
    open_gap_pct = np.nan

    gap_direction = None
    action = None

    break_time = pd.NaT
    break_mid = np.nan
    minutes_until_break = np.nan

    take_profit = session_open_close

    reverted_to_open = 0
    reversion_time = pd.NaT
    minutes_from_break_to_reversion = np.nan

    exit_time = pd.NaT
    exit_price = np.nan
    exit_reason = None

    pnl_price = np.nan
    pnl_ticks = 0.0

    is_trade = 0
    invalid_target_trade = 0

    # First row has no previous session close
    if pd.isna(prev_session_close_mid):
        results.append({
            "session_date": session_date,
            "session_open_mid": session_open_mid,
            "prev_session_close_mid": prev_session_close_mid,
            "open_gap": open_gap,
            "open_gap_pct": open_gap_pct,

            "gap_direction": gap_direction,
            "action": action,

            "break_time": break_time,
            "minutes_until_break": minutes_until_break,
            "break_mid": break_mid,

            "take_profit": take_profit,
            "reverted_to_open": reverted_to_open,
            "reversion_time": reversion_time,
            "minutes_from_break_to_reversion": minutes_from_break_to_reversion,

            "session_end_time": session_end_time,
            "session_end_mid": session_close_mid,

            "exit_time": exit_time,
            "exit_price": exit_price,
            "exit_reason": "no_prev_session_close",

            "pnl_price": pnl_price,
            "pnl_ticks": pnl_ticks,
            "cum_pnl_ticks": cum_pnl_ticks,

            "is_trade": is_trade,
            "invalid_target_trade": invalid_target_trade,
            "bars": bars,
        })
        continue

    # =========================
    # 1. CURRENT FIRST MID VS PREVIOUS SESSION FINAL MID
    # =========================

    open_gap = session_open_mid - prev_session_close_mid
    open_gap_pct = open_gap / prev_session_close_mid * 100

    mids = day_df["mid"]

    # =========================
    # 2. DECIDE TRADE DIRECTION + BREAK DIRECTION
    # =========================

    if session_open_mid > prev_session_close_mid:
        gap_direction = "higher"
        action = "short"

        # Current first mid is higher, so look for first downward mid break
        break_mask = mids < mids.shift(1)

    elif session_open_mid < prev_session_close_mid:
        gap_direction = "lower"
        action = "long"

        # Current first mid is lower, so look for first upward mid break
        break_mask = mids > mids.shift(1)

    else:
        gap_direction = "equal"
        action = None
        break_mask = pd.Series(False, index=mids.index)

    # First bar has no previous bar inside current session
    if len(break_mask) > 0:
        break_mask.iloc[0] = False

    # =========================
    # 3. NO BREAK = NO TRADE
    # =========================

    if not break_mask.any():
        results.append({
            "session_date": session_date,
            "session_open_mid": session_open_mid,
            "prev_session_close_mid": prev_session_close_mid,
            "open_gap": open_gap,
            "open_gap_pct": open_gap_pct,

            "gap_direction": gap_direction,
            "action": action,

            "break_time": break_time,
            "minutes_until_break": minutes_until_break,
            "break_mid": break_mid,

            "take_profit": take_profit,
            "reverted_to_open": reverted_to_open,
            "reversion_time": reversion_time,
            "minutes_from_break_to_reversion": minutes_from_break_to_reversion,

            "session_end_time": session_end_time,
            "session_end_mid": session_close_mid,

            "exit_time": exit_time,
            "exit_price": exit_price,
            "exit_reason": "no_break",

            "pnl_price": pnl_price,
            "pnl_ticks": pnl_ticks,
            "cum_pnl_ticks": cum_pnl_ticks,

            "is_trade": is_trade,
            "invalid_target_trade": invalid_target_trade,
            "bars": bars,
        })
        continue

    # =========================
    # 4. ENTRY AT BREAK MID PRICE
    # =========================

    break_time = break_mask[break_mask].index[0]
    break_idx = day_df.index.get_loc(break_time)
    break_mid = mids.loc[break_time]

    minutes_until_break = int((break_time - open_time).total_seconds() / 60)

    # Take profit is current session first mid
    take_profit = session_open_close

    # =========================
    # 5. OPTIONAL FILTER:
    #    TARGET MUST BE PROFITABLE IF REACHED
    # =========================

    if SKIP_INVALID_TARGET_TRADES:
        if action == "short" and break_mid <= take_profit:
            invalid_target_trade = 1
            exit_reason = "invalid_short_target_not_below_entry"

            results.append({
                "session_date": session_date,
                "session_open_mid": session_open_mid,
                "prev_session_close_mid": prev_session_close_mid,
                "open_gap": open_gap,
                "open_gap_pct": open_gap_pct,

                "gap_direction": gap_direction,
                "action": action,

                "break_time": break_time,
                "minutes_until_break": minutes_until_break,
                "break_mid": break_mid,

                "take_profit": take_profit,
                "reverted_to_open": reverted_to_open,
                "reversion_time": reversion_time,
                "minutes_from_break_to_reversion": minutes_from_break_to_reversion,

                "session_end_time": session_end_time,
                "session_end_mid": session_close_mid,

                "exit_time": exit_time,
                "exit_price": exit_price,
                "exit_reason": exit_reason,

                "pnl_price": pnl_price,
                "pnl_ticks": pnl_ticks,
                "cum_pnl_ticks": cum_pnl_ticks,

                "is_trade": is_trade,
                "invalid_target_trade": invalid_target_trade,
                "bars": bars,
            })
            continue

        if action == "long" and break_mid >= take_profit:
            invalid_target_trade = 1
            exit_reason = "invalid_long_target_not_above_entry"

            results.append({
                "session_date": session_date,
                "session_open_mid": session_open_mid,
                "prev_session_close_mid": prev_session_close_mid,
                "open_gap": open_gap,
                "open_gap_pct": open_gap_pct,

                "gap_direction": gap_direction,
                "action": action,

                "break_time": break_time,
                "minutes_until_break": minutes_until_break,
                "break_mid": break_mid,

                "take_profit": take_profit,
                "reverted_to_open": reverted_to_open,
                "reversion_time": reversion_time,
                "minutes_from_break_to_reversion": minutes_from_break_to_reversion,

                "session_end_time": session_end_time,
                "session_end_mid": session_close_mid,

                "exit_time": exit_time,
                "exit_price": exit_price,
                "exit_reason": exit_reason,

                "pnl_price": pnl_price,
                "pnl_ticks": pnl_ticks,
                "cum_pnl_ticks": cum_pnl_ticks,

                "is_trade": is_trade,
                "invalid_target_trade": invalid_target_trade,
                "bars": bars,
            })
            continue

    # =========================
    # 6. CHECK REVERSION AFTER ENTRY BAR ONLY
    # =========================

    is_trade = 1
    after_entry = day_df.iloc[break_idx + 1:]

    if not after_entry.empty:
        # Touch-based reversion:
        # Did the minute's high/low trade through the take-profit mid level?
        reversion_mask = (
            (after_entry["low"] <= take_profit) &
            (take_profit <= after_entry["high"])
        )

        if reversion_mask.any():
            reverted_to_open = 1

            reversion_time = reversion_mask[reversion_mask].index[0]
            minutes_from_break_to_reversion = int(
                (reversion_time - break_time).total_seconds() / 60
            )

            exit_time = reversion_time
            exit_price = take_profit
            exit_reason = "reverted_to_open"

        else:
            reverted_to_open = 0

            exit_time = session_end_time
            exit_price = session_close_mid
            exit_reason = "session_end_no_reversion"

    else:
        # Entry happened on the last bar
        reverted_to_open = 0

        exit_time = session_end_time
        exit_price = session_close_mid
        exit_reason = "session_end_no_bars_after_entry"

    # =========================
    # 7. SIGNED P&L
    # =========================
    #
    # Important:
    # If no reversion, it can still be a win or loss.
    # P&L depends on action and actual exit price.

    if action == "long":
        pnl_price = exit_price - break_mid

    elif action == "short":
        pnl_price = break_mid - exit_price

    else:
        pnl_price = np.nan

    pnl_ticks = pnl_price / TICK_SIZE if pd.notna(pnl_price) else 0.0
    cum_pnl_ticks += pnl_ticks

    results.append({
        "session_date": session_date,
        "session_open_mid": session_open_mid,
        "prev_session_close_mid": prev_session_close_mid,
        "open_gap": open_gap,
        "open_gap_pct": open_gap_pct,

        "gap_direction": gap_direction,
        "action": action,

        "break_time": break_time,
        "minutes_until_break": minutes_until_break,
        "break_mid": break_mid,

        "take_profit": take_profit,
        "reverted_to_open": reverted_to_open,
        "reversion_time": reversion_time,
        "minutes_from_break_to_reversion": minutes_from_break_to_reversion,

        "session_end_time": session_end_time,
        "session_end_mid": session_close_mid,

        "exit_time": exit_time,
        "exit_price": exit_price,
        "exit_reason": exit_reason,

        "pnl_price": pnl_price,
        "pnl_ticks": pnl_ticks,
        "cum_pnl_ticks": cum_pnl_ticks,

        "is_trade": is_trade,
        "invalid_target_trade": invalid_target_trade,
        "bars": bars,
    })


# =========================
# OUTPUT
# =========================

summary = pd.DataFrame(results)

summary["is_win"] = ((summary["is_trade"] == 1) & (summary["pnl_ticks"] > 0)).astype(int)
summary["is_loss"] = ((summary["is_trade"] == 1) & (summary["pnl_ticks"] < 0)).astype(int)
summary["is_flat"] = ((summary["is_trade"] == 1) & (summary["pnl_ticks"] == 0)).astype(int)

summary["gross_profit_ticks"] = summary["pnl_ticks"].where(summary["pnl_ticks"] > 0, 0)
summary["gross_loss_ticks"] = summary["pnl_ticks"].where(summary["pnl_ticks"] < 0, 0).abs()

summary["cum_gross_profit_ticks"] = summary["gross_profit_ticks"].cumsum()
summary["cum_gross_loss_ticks"] = summary["gross_loss_ticks"].cumsum()


# =========================
# TOTALS
# =========================

trades = summary[summary["is_trade"] == 1]

total_trades = len(trades)
winning_trades = int((trades["pnl_ticks"] > 0).sum())
losing_trades = int((trades["pnl_ticks"] < 0).sum())
flat_trades = int((trades["pnl_ticks"] == 0).sum())

reverted_trades = int((trades["reverted_to_open"] == 1).sum())
not_reverted_trades = int((trades["reverted_to_open"] == 0).sum())

invalid_target_trades = int((summary["invalid_target_trade"] == 1).sum())

gross_profit_ticks = trades.loc[trades["pnl_ticks"] > 0, "pnl_ticks"].sum()
gross_loss_ticks = trades.loc[trades["pnl_ticks"] < 0, "pnl_ticks"].abs().sum()
net_pnl_ticks = trades["pnl_ticks"].sum()

win_rate = winning_trades / total_trades * 100 if total_trades > 0 else np.nan
reversion_rate = reverted_trades / total_trades * 100 if total_trades > 0 else np.nan

profit_factor = (
    gross_profit_ticks / gross_loss_ticks
    if gross_loss_ticks != 0
    else np.nan
)

totals = pd.DataFrame({
    "metric": [
        "mid_mode",
        "total_trades",
        "winning_trades",
        "losing_trades",
        "flat_trades",
        "reverted_trades",
        "not_reverted_trades",
        "invalid_target_trades_skipped",
        "win_rate_pct",
        "reversion_rate_pct",
        "gross_profit_ticks",
        "gross_loss_ticks",
        "net_pnl_ticks",
        "profit_factor",
    ],
    "value": [
        MID_MODE,
        total_trades,
        winning_trades,
        losing_trades,
        flat_trades,
        reverted_trades,
        not_reverted_trades,
        invalid_target_trades,
        win_rate,
        reversion_rate,
        gross_profit_ticks,
        gross_loss_ticks,
        net_pnl_ticks,
        profit_factor,
    ]
})


# =========================
# EXCEL DATETIME FIX
# =========================

def remove_timezone_for_excel(x):
    if isinstance(x, pd.Timestamp) and x.tzinfo is not None:
        return x.tz_localize(None)
    return x

summary = summary.map(remove_timezone_for_excel)
totals = totals.map(remove_timezone_for_excel)


# =========================
# WRITE TO EXCEL
# =========================

with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
    summary.to_excel(writer, sheet_name="summary", index=False)
    totals.to_excel(writer, sheet_name="totals", index=False)

print(summary.head(50))
print()
print(totals)
print(f"\nSaved to: {OUTPUT_FILE}")