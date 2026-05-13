# "PIGS_2016-05-01_to_2026-05-01.parquet"
import pandas as pd
import numpy as np


# =========================
# Config
# =========================

FILE_PATH = "PIGS_2016-05-01_to_2026-05-01.parquet"

START_DATE = "2025-05-01"
END_DATE = "2026-05-01"

TIMEZONE = "America/New_York"

# Used only when reverted_to_open == 0
SESSION_END_TIME = "17:59"

OUTPUT_FILE = "open_gap_breaks_clean.csv"


# =========================
# Helpers
# =========================

def get_close_at_or_before(day_df, target_time="17:59"):
    """
    Gets the last close at or before target_time within the same day/session.
    """
    target_time = pd.Timestamp(target_time).time()

    eligible = day_df[day_df.index.time <= target_time]

    if eligible.empty:
        return np.nan, pd.NaT

    end_time = eligible.index[-1]
    end_close = eligible["close"].iloc[-1]

    return end_close, end_time


# =========================
# Load data
# =========================

df = pd.read_parquet(FILE_PATH)

df.index = pd.to_datetime(df.index)
df = df.sort_index()

# Convert UTC index to NY time for RTH session dates
if df.index.tz is None:
    df.index = df.index.tz_localize("UTC").tz_convert(TIMEZONE)
else:
    df.index = df.index.tz_convert(TIMEZONE)

df = df.loc[START_DATE:END_DATE].copy()

# RTH only, so calendar date is fine
df["session_date"] = df.index.date


# =========================
# Build daily rows
# =========================

daily_rows = []

for session_date, day_df in df.groupby("session_date"):
    day_df = day_df.sort_index()

    if day_df.empty:
        continue

    daily_rows.append({
        "session_date": session_date,
        "session_open": day_df["open"].iloc[0],
        "session_close": day_df["close"].iloc[-1],
        "open_time": day_df.index[0],
        "day_df": day_df
    })

daily = pd.DataFrame(daily_rows)

# Previous RTH session close
daily["prev_session_close"] = daily["session_close"].shift(1)


# =========================
# Analyze break + reversion
# =========================

results = []

for _, row in daily.iterrows():
    day_df = row["day_df"]

    session_date = row["session_date"]
    session_open = row["session_open"]
    prev_close = row["prev_session_close"]
    open_time = row["open_time"]

    session_end_close, session_end_time = get_close_at_or_before(
        day_df,
        SESSION_END_TIME
    )

    open_gap = np.nan
    open_gap_pct = np.nan

    break_direction = None
    break_time = pd.NaT
    minutes_until_break = np.nan
    break_close = np.nan

    # Move from session_open to break_close
    break_move = np.nan
    break_move_pct = np.nan

    # Cumulative move from first close/open area until break
    cumulative_move_until_break = np.nan
    cumulative_move_until_break_pct = np.nan

    reverted_to_open = 0
    reversion_time = pd.NaT
    reversion_close = np.nan
    minutes_from_break_to_reversion = np.nan

    move_from_break_to_reversion = np.nan
    move_from_break_to_reversion_pct = np.nan

    move_from_break_to_session_end = np.nan
    move_from_break_to_session_end_pct = np.nan

    if pd.notna(prev_close):
        open_gap = session_open - prev_close
        open_gap_pct = open_gap / prev_close * 100

        closes = day_df["close"]
        prev_minute_close = closes.shift(1)

        if session_open > prev_close:
            # Gap up.
            # Break = first minute close lower than previous minute close.
            break_direction = "down"
            break_mask = closes < prev_minute_close

        elif session_open < prev_close:
            # Gap down.
            # Break = first minute close higher than previous minute close.
            break_direction = "up"
            break_mask = closes > prev_minute_close

        else:
            break_direction = "none"
            break_mask = pd.Series(False, index=closes.index)

        # First bar has no previous minute close inside the session
        if len(break_mask) > 0:
            break_mask.iloc[0] = False

        if break_mask.any():
            break_time = break_mask[break_mask].index[0]
            break_close = closes.loc[break_time]

            minutes_until_break = int(
                (break_time - open_time).total_seconds() / 60
            )

            # Move from session open to break close
            break_move = break_close - session_open
            break_move_pct = break_move / session_open * 100

            # Cumulative move until break:
            # sum of minute-to-minute close changes from open until break.
            #
            # Mathematically this equals:
            # break_close - first_close
            #
            # But this keeps the "cumulative" interpretation explicit.
            closes_until_break = closes.loc[:break_time]
            close_diffs_until_break = closes_until_break.diff().dropna()

            cumulative_move_until_break = close_diffs_until_break.sum()

            first_close = closes_until_break.iloc[0]
            cumulative_move_until_break_pct = (
                cumulative_move_until_break / first_close * 100
                if first_close != 0
                else np.nan
            )

            # Only check same day/session after break_time
            break_idx = day_df.index.get_loc(break_time)
            after_break = day_df.iloc[break_idx + 1:]

            if break_direction == "down":
                # Close-only reversion back to session open
                reversion_mask = after_break["close"] >= session_open

            elif break_direction == "up":
                # Close-only reversion back to session open
                reversion_mask = after_break["close"] <= session_open

            else:
                reversion_mask = pd.Series(False, index=after_break.index)

            if reversion_mask.any():
                reverted_to_open = 1
                reversion_time = reversion_mask[reversion_mask].index[0]
                reversion_close = after_break.loc[reversion_time, "close"]

                minutes_from_break_to_reversion = int(
                    (reversion_time - break_time).total_seconds() / 60
                )

                move_from_break_to_reversion = reversion_close - break_close
                move_from_break_to_reversion_pct = (
                    move_from_break_to_reversion / break_close * 100
                    if break_close != 0
                    else np.nan
                )

            # If it did not revert within the same day,
            # measure from break close to 17:59 close.
            if reverted_to_open == 0 and pd.notna(session_end_close):
                move_from_break_to_session_end = session_end_close - break_close
                move_from_break_to_session_end_pct = (
                    move_from_break_to_session_end / break_close * 100
                    if break_close != 0
                    else np.nan
                )

    results.append({
        "session_date": session_date,
        "session_open": session_open,
        "prev_session_close": prev_close,
        "open_gap": open_gap,
        "open_gap_pct": open_gap_pct,

        "break_direction": break_direction,
        "break_time": break_time,
        "minutes_until_break": minutes_until_break,
        "break_close": break_close,

        "break_move": break_move,
        "break_move_pct": break_move_pct,

        "cumulative_move_until_break": cumulative_move_until_break,
        "cumulative_move_until_break_pct": cumulative_move_until_break_pct,

        "reverted_to_open": reverted_to_open,
        "reversion_time": reversion_time,
        "reversion_close": reversion_close,
        "minutes_from_break_to_reversion": minutes_from_break_to_reversion,

        "move_from_break_to_reversion": move_from_break_to_reversion,
        "move_from_break_to_reversion_pct": move_from_break_to_reversion_pct,

        "session_end_time": session_end_time,
        "session_end_close": session_end_close,
        "move_from_break_to_session_end": move_from_break_to_session_end,
        "move_from_break_to_session_end_pct": move_from_break_to_session_end_pct,
    })




# =========================
# Output
# =========================

summary = pd.DataFrame(results)

# =========================
# Cumulative absolute move stats
# =========================

summary["cum_abs_break_move_reverted"] = (
    summary["break_move"]
    .where(summary["reverted_to_open"] == 1, 0)
    .abs()
    .cumsum()
)

summary["cum_abs_session_end_move_not_reverted"] = (
    summary["move_from_break_to_session_end"]
    .where(summary["reverted_to_open"] == 0, 0)
    .abs()
    .cumsum()
)

print(summary.head(30))

summary.to_csv(OUTPUT_FILE, index=False)

print(f"\nSaved to: {OUTPUT_FILE}")