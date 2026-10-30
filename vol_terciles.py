#!/usr/bin/env python3
"""Strategy 27's momentum book, split by its own trailing volatility. A retraction.

    python3 vol_terciles.py

The README once reported that crypto momentum earns everything in its most
volatile third of days (Sharpe 1.41) and nothing otherwise. That table came
from pd.qcut over the FULL sample: the tercile cutoffs used volatility levels
that hadn't happened yet, so no trader could have sorted days that way. The
script behind it was never committed (audit 2026-10-29, finding A3). This is
it, printed both ways.

POINT IN TIME: each day's trailing volatility is ranked only against the
volatility seen up to and including that day, and no day is ranked until 180
days of history exist. That's the version a trader could have used.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from daily_momentum import book
from pit_rerun import daily

WINDOW = 30
MIN_HISTORY = 180
LABELS = ["calm", "middle", "volatile"]


def table(x: pd.DataFrame, col: str) -> pd.DataFrame:
    g = x.dropna(subset=[col]).groupby(col, observed=True)["r"]
    t = pd.DataFrame({"days": g.size(), "ann_return": g.mean() * 365,
                      "ann_vol": g.std() * np.sqrt(365)})
    t["sharpe"] = t["ann_return"] / t["ann_vol"]
    return t


def main() -> int:
    r = book(daily(), "xs", 21)["net"]
    # Trailing volatility through yesterday: known when today's position is set.
    vol = r.rolling(WINDOW, min_periods=WINDOW).std().shift(1) * np.sqrt(365)
    x = pd.DataFrame({"r": r, "vol": vol}).dropna()

    x["full_sample"] = pd.qcut(x["vol"], 3, labels=LABELS)
    # Percentile of today's value within its own history so far.
    pct = x["vol"].expanding(min_periods=MIN_HISTORY).rank(pct=True)
    x["point_in_time"] = pd.cut(pct, [0, 1 / 3, 2 / 3, 1], labels=LABELS)

    fmt = {"ann_return": "{:.0%}".format, "ann_vol": "{:.0%}".format,
           "sharpe": "{:.2f}".format}
    print("FULL-SAMPLE terciles (look-ahead: the table the README printed)")
    print(table(x, "full_sample").to_string(formatters=fmt))
    print(f"\nPOINT-IN-TIME terciles (expanding rank, at least {MIN_HISTORY} days)")
    print(table(x, "point_in_time").to_string(formatters=fmt))

    print(f"\nthe 10 best days carry {r.nlargest(10).sum() / r.sum():.0%} of the book's total P&L")
    return 0


if __name__ == "__main__":
    sys.exit(main())
