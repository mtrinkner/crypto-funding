#!/usr/bin/env python3
"""Strategy 27: daily momentum and reversal on Hyperliquid perps.

    python3 daily_momentum.py

A different mechanism from funding carry, at a frequency where the signal
actually changes every day. Crypto returns show momentum at 1-4 week horizons
(Liu, Tsyvinski and Wu, JF 2022) and reversal at very short ones.

Everything was fixed in the registry before this ran: the universe (point-in-
time weekly top 20 by volume, delisted coins included), the six variants, the
primary (cross-sectional 21-day), costs of 8bp per side on traded notional,
funding paid or received on every position, and the pass criteria.

Positions are set at each daily close from closes through that day and earn
the next day's return. Collateral earns T-bills, so a self-financed long/short
return is already an excess return.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from funding_carry import HERE
from pit_rerun import daily
from validate import monthly, psr, sharpe_m
from deflated_sharpe import deflated_sharpe_ratio, expected_max_sharpe
import registry

COST = 0.0008                    # per side, on traded notional
MIN_COINS = 6
VARIANTS = [("xs", 21, True), ("xs", 7, False), ("xs", 1, False),
            ("ts", 21, False), ("ts", 7, False), ("ts", 1, False)]


def signals(d: pd.DataFrame, lookback: int) -> pd.Series:
    """Trailing return through yesterday's close. Reversal sign at one day."""
    s = d.groupby("coin")["close"].transform(lambda c: c.shift(1) / c.shift(1 + lookback) - 1)
    return -s if lookback == 1 else s


def weights(d: pd.DataFrame, kind: str, lookback: int) -> pd.Series:
    s = signals(d, lookback).where(d["member"] > 0)
    if kind == "xs":
        n = s.groupby(d["day"]).transform("count")
        r = s.groupby(d["day"]).rank(pct=True)
        long_ = (r > 2 / 3) & (n >= MIN_COINS)
        short = (r <= 1 / 3) & (n >= MIN_COINS)
        nl = long_.groupby(d["day"]).transform("sum").replace(0, np.nan)
        ns = short.groupby(d["day"]).transform("sum").replace(0, np.nan)
        w = long_ / nl - short / ns                    # $1 long, $1 short
    else:
        n = s.groupby(d["day"]).transform("count").replace(0, np.nan)
        w = np.sign(s) / n                             # $1 gross
    return w.fillna(0.0)


def book(d: pd.DataFrame, kind: str, lookback: int) -> pd.DataFrame:
    d = d.copy()
    d["w"] = weights(d, kind, lookback)
    prev = d.groupby("coin")["w"].shift(1).fillna(0.0)
    d["price"] = d["w"] * d["ret"].fillna(0.0)
    d["fund"] = -d["w"] * d["rate"]                   # a long pays positive funding
    d["cost"] = (d["w"] - prev).abs() * COST
    b = d.groupby("day")[["price", "fund", "cost"]].sum()
    b["net"] = b["price"] + b["fund"] - b["cost"]
    b["turnover"] = (d["w"] - prev).abs().groupby(d["day"]).sum()
    return b[d.groupby("day")["w"].apply(lambda w: w.abs().sum() > 0)]


def bitmex_ts(lookback: int) -> pd.Series:
    """Time-series variant on BitMEX BTC and ETH, 2017-03 to 2023-04."""
    from out_of_time import END, panel
    d = panel()
    btc = d[d.coin == "BTC"].set_index("day")["ret"]
    eth = d["coin"] == "ETH"
    # ETHUSD is a quanto: a long earns r_eth (1 + r_btc) in USD terms.
    d.loc[eth, "ret"] = d.loc[eth, "ret"] * (1 + d.loc[eth, "day"].map(btc).fillna(0).values)
    d = d[d.day <= END].rename(columns={"perp_close": "close"})
    return book(d, "ts", lookback)["net"]


def main() -> int:
    d = daily()
    n_all = registry.trials()["n_trials"]
    live = d[d.member > 0]
    print(f"{live.coin.nunique()} coins over {live.day.nunique():,} days, "
          f"{live.day.min().date()} to {live.day.max().date()}; trials to date {n_all}")
    btc = d[d.coin == "BTC"].set_index("day")["ret"]
    mid = live.day.min() + (live.day.max() - live.day.min()) / 2

    print(f"\n{'variant':<26}{'gross':>8}{'fund':>7}{'cost':>8}{'net':>8}{'SR':>7}{'PSR>0':>7}"
          f"{'DSR':>7}{'1st half':>9}{'2nd half':>9}{'turn/d':>8}{'BTC corr':>9}")
    rows = []
    for kind, lb, primary in VARIANTS:
        b = book(d, kind, lb)
        net = b["net"]
        sr = sharpe_m(net)
        n_m = len(monthly(net))
        name = f"{'cross-sectional' if kind == 'xs' else 'time-series'} {lb}d" + \
               ("  PRIMARY" if primary else "")
        h1, h2 = net[net.index < mid], net[net.index >= mid]
        print(f"{name:<26}{(b.price.mean()) * 365:8.1%}{b.fund.mean() * 365:7.1%}"
              f"{-b.cost.mean() * 365:8.1%}{net.mean() * 365:8.1%}{sr:7.2f}{psr(net, 0):7.2f}"
              f"{deflated_sharpe_ratio(sr, n_all, n_m, periods_per_year=12):7.3f}{sharpe_m(h1):9.2f}{sharpe_m(h2):9.2f}"
              f"{b.turnover.mean():8.2f}{net.corr(btc.reindex(net.index)):9.2f}")
        rows.append({"variant": name, "net": net.mean() * 365, "sharpe": sr,
                     "first_half": sharpe_m(h1), "second_half": sharpe_m(h2)})
        if primary:
            prim, pb = net, b
    print(f"\nluck bar at {n_all} trials and {len(monthly(prim))} months: "
          f"{expected_max_sharpe(n_all, len(monthly(prim)), periods_per_year=12):.2f}")

    yr = prim.groupby(prim.index.year).mean() * 365
    print("primary net by year: " + ", ".join(f"{y} {v:+.1%}" for y, v in yr.items()))
    m = monthly(prim)
    eq = prim.cumsum()
    print(f"primary: months positive {(m > 0).mean():.0%}, worst month {m.min():.1%}, "
          f"max drawdown {(eq.cummax() - eq).max():.1%}")

    print("\nBitMEX BTC/ETH 2017-03 to 2023-04, time-series variants (out of time)")
    for lb in (21, 7, 1):
        b = bitmex_ts(lb)
        yb = b.groupby(b.index.year).mean() * 365
        print(f"  time-series {lb}d: net {b.mean() * 365:6.1%}  Sharpe {sharpe_m(b):5.2f}  "
              f"2018 {yb.get(2018, np.nan):+.0%}  2022 {yb.get(2022, np.nan):+.0%}")

    crit = {
        "Sharpe after costs >= 1.5": sharpe_m(prim) >= 1.5,
        "PSR(SR > 0) >= 0.95": psr(prim, 0) >= 0.95,
        "positive Sharpe in both halves": min(sharpe_m(prim[prim.index < mid]),
                                              sharpe_m(prim[prim.index >= mid])) > 0,
    }
    print("\npass criteria for the primary (declared in advance)")
    for k, v in crit.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")

    out = HERE / "reports"
    out.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(out / "daily_momentum.csv", index=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
