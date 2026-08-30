import databento as db
import os
from dotenv import load_dotenv

DATASET    = "GLBX.MDP3"           # CME Globex
SYMBOL     = "GC.v.0"              # Front-adjusted continuous NQ
SCHEMA     = "ohlcv-1m"            # 1-minute OHLCV
SYM_TYPE   = "continuous"          # Databento symbology type
START_TIME = "2021-01-01T00:00:00"
END_TIME = "2026-05-14T00:00:00"

load_dotenv()

api_key = os.getenv("DATABENTO_API_KEY")
client   = db.Historical(api_key)
symbol = "GC"

data = client.timeseries.get_range(
    dataset="GLBX.MDP3",
    symbols=f"{symbol}.v.0",
    stype_in="continuous",
    start=START_TIME,
    end=END_TIME,
    schema="ohlcv-1m",
)

data.to_parquet(
    f"{symbol}-futures-ohlcv-01-01-2021-to-14-05-2026.parquet",
    pretty_ts=True,
    map_symbols=True,
)