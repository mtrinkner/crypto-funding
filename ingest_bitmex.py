#!/usr/bin/env python3
"""BitMEX funding and daily prices, 2016 on: the bear markets the rest lacks.

    python3 ingest_bitmex.py

Hyperliquid's history starts in May 2023, after the 2018 and 2022 crashes.
BitMEX ran the first perpetual swaps and still serves their full funding
history publicly, with no key: XBTUSD since May 2016 and ETHUSD since August
2018, plus its spot indices .BXBT and .BETH since 2017.

Writes data/bitmex_funding.parquet and data/bitmex_daily.parquet.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parent / "data"
BASE = "https://www.bitmex.com/api/v1"
PERPS = {"BTC": ("XBTUSD", ".BXBT"), "ETH": ("ETHUSD", ".BETH")}


def get(path: str, q: dict, retries: int = 6):
    url = f"{BASE}{path}?{urllib.parse.urlencode(q)}"
    for a in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=60) as f:
                return json.loads(f.read().decode())
        except Exception as e:
            err = e
            time.sleep(3.0 * 2 ** a)
    raise RuntimeError(f"BitMEX request failed after {retries} tries: {url}: {err}")


def paged(path: str, q: dict, page: int) -> list[dict]:
    out, start = [], 0
    while True:
        rows = get(path, {**q, "count": page, "start": start, "reverse": "false"})
        out.extend(rows)
        if len(rows) < page:
            return out
        start += page
        time.sleep(1.1)        # unauthenticated limit is about 60 requests a minute


def main() -> int:
    F, P = [], []
    for coin, (perp, index) in PERPS.items():
        f = pd.DataFrame(paged("/funding", {"symbol": perp}, 500))
        f["ts"] = pd.to_datetime(f["timestamp"], utc=True)
        f["rate"] = f["fundingRate"].astype(float)
        f["coin"] = coin
        F.append(f[["coin", "ts", "rate"]])
        for kind, sym in (("perp", perp), ("spot", index)):
            b = pd.DataFrame(paged("/trade/bucketed", {"symbol": sym, "binSize": "1d"}, 1000))
            # BitMEX stamps a daily bucket with its CLOSE time; shift to the open.
            b["day"] = pd.to_datetime(b["timestamp"], utc=True) - pd.Timedelta(days=1)
            b = b[["day", "close", "high", "low"]].add_prefix(f"{kind}_").rename(
                columns={f"{kind}_day": "day"})
            P.append((coin, kind, b))
        print(f"  {coin}: {len(f):,} funding prints from {f.ts.min().date()}", flush=True)

    fund = pd.concat(F, ignore_index=True)
    daily = []
    for coin in PERPS:
        parts = [b for c, k, b in P if c == coin]
        m = parts[0].merge(parts[1], on="day", how="inner")
        m["coin"] = coin
        daily.append(m)
    daily = pd.concat(daily, ignore_index=True)
    fund.to_parquet(DATA / "bitmex_funding.parquet", index=False)
    daily.to_parquet(DATA / "bitmex_daily.parquet", index=False)
    print(f"funding {len(fund):,} prints; daily {len(daily):,} coin-days with perp and spot, "
          f"{daily.day.min().date()} to {daily.day.max().date()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
