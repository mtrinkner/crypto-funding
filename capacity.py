#!/usr/bin/env python3
"""Where did strategy 25's gross edge come from: markets you could trade, or not?

    python3 capacity.py

Descriptive, not a trading rule. It takes strategy 25's primary positions with
nothing charged and buckets every held coin-day by dYdX's trailing 30-day
average daily volume for that coin, which was known at the time. No threshold
is chosen or optimised, so it adds no trials.

Needs data/dydx_candles.parquet (python3 ingest_dydx.py --candles).
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import cross_venue as cv
from funding_carry import DATA, HERE

BINS = [0, 1e5, 1e6, 1e7, np.inf]
LABELS = ["under $0.1m", "$0.1-1m", "$1-10m", "over $10m"]


def main() -> int:
    d = cv.panel()
    _, x = cv.book(d, 2.0, 30, detail=True)
    c = pd.read_parquet(DATA / "dydx_candles.parquet").sort_values(["coin", "day"])
    g = c.groupby("coin")
    # Through yesterday only: the liquidity a trader could have seen.
    c["vol30"] = g["usd_volume"].transform(lambda s: s.shift(1).rolling(30, min_periods=10).mean())
    c["oi30"] = g["oi_usd"].transform(lambda s: s.shift(1).rolling(30, min_periods=10).mean())
    x = x.merge(c[["coin", "day", "vol30", "oi30"]], on=["coin", "day"], how="left")

    h = x[x.expo != 0].copy()
    h["gross"] = h["expo"] * h["spread"]
    h["bucket"] = pd.cut(h["vol30"], BINS, labels=LABELS)
    t = h.groupby("bucket", observed=False).agg(days=("gross", "size"), total=("gross", "sum"),
                                                per_day=("gross", "mean"))
    t["share of held days"] = t["days"] / t["days"].sum()
    t["share of gross"] = t["total"] / h["gross"].sum()
    t["gross a year"] = t["per_day"] * 365
    print("strategy 25 primary, nothing charged, by dYdX trailing 30-day daily volume")
    print(t[["share of held days", "share of gross", "gross a year"]].to_string(
        float_format=lambda v: f"{v:8.1%}"))

    print("\nshare of the gross from coin-days trading over $1m a day on dYdX")
    for y in (2024, 2025, 2026):
        s = h[h.day.dt.year == y]
        print(f"  {y}: {s.loc[s.vol30 > 1e6, 'gross'].sum() / s['gross'].sum():.0%} "
              f"of gross, {(s.vol30 > 1e6).mean():.0%} of held days")

    u = x[x.member > 0]
    q = u.groupby(u.day.dt.tz_localize(None).dt.to_period("Q"))[["vol30", "oi30"]].median() / 1e6
    q.columns = ["daily volume $m", "open interest $m"]
    print("\nthe median universe coin on dYdX, by quarter")
    print(q.round(2).T.to_string())

    out = HERE / "reports"
    out.mkdir(exist_ok=True)
    t.to_csv(out / "capacity_buckets.csv")
    q.to_csv(out / "dydx_liquidity_by_quarter.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
