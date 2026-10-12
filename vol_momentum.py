#!/usr/bin/env python3
"""Strategy 28: strategy 27's momentum, sized by its own recent volatility.

    python3 vol_momentum.py

Strategy 27's three-week cross-sectional momentum earned 30% a year net with an
85% drawdown. Momentum crashes cluster in volatile stretches, and a strategy's
recent volatility forecasts its future volatility much better than its recent
returns forecast future returns (Barroso and Santa-Clara 2015; Moreira and Muir
2017). So each day the book is scaled by target / trailing realized volatility
of the unscaled book, measured through yesterday, capped at 2x.

Declared before running, but tried because strategy 27 was this volatile, on the
same data: post-hoc, so this backtest is weak evidence by construction.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from daily_momentum import COST, book, weights
from funding_carry import HERE
from pit_rerun import daily
from validate import monthly, psr, sharpe_m
from deflated_sharpe import deflated_sharpe_ratio, expected_max_sharpe
import registry

TARGET = 0.30
CAP = 2.0
VARIANTS = [(30, True), (90, False)]


def scaled_book(d: pd.DataFrame, window: int) -> tuple[pd.DataFrame, pd.Series]:
    base = book(d, "xs", 21)["net"]
    # Realized vol of the unscaled book through yesterday: today's return is
    # not known when today's size is set.
    vol = base.rolling(window, min_periods=window).std().shift(1) * np.sqrt(365)
    k = (TARGET / vol).clip(upper=CAP)

    x = d.copy()
    x["w"] = weights(x, "xs", 21) * x["day"].map(k).fillna(0.0)
    prev = x.groupby("coin")["w"].shift(1).fillna(0.0)
    x["price"] = x["w"] * x["ret"].fillna(0.0)
    x["fund"] = -x["w"] * x["rate"]
    x["cost"] = (x["w"] - prev).abs() * COST
    b = x.groupby("day")[["price", "fund", "cost"]].sum()
    b["net"] = b["price"] + b["fund"] - b["cost"]
    b["turnover"] = (x["w"] - prev).abs().groupby(x["day"]).sum()
    keep = x.groupby("day")["w"].apply(lambda w: w.abs().sum() > 0)
    return b[keep], k


def drawdown(r: pd.Series) -> float:
    eq = r.cumsum()
    return float((eq.cummax() - eq).max())


def main() -> int:
    d = daily()
    n_all = registry.trials()["n_trials"]
    unscaled = book(d, "xs", 21)

    print(f"trials to date {n_all}; target {TARGET:.0%} a year, scale capped at {CAP:.0f}x\n")
    print(f"{'book':<28}{'net':>8}{'vol':>8}{'SR':>7}{'PSR>0':>7}{'DSR':>7}"
          f"{'1st half':>9}{'2nd half':>9}{'max DD':>8}{'cost':>8}")

    def line(name, b):
        net = b["net"]
        mid = net.index.min() + (net.index.max() - net.index.min()) / 2
        sr = sharpe_m(net)
        print(f"{name:<28}{net.mean() * 365:8.1%}{net.std() * np.sqrt(365):8.1%}{sr:7.2f}"
              f"{psr(net, 0):7.2f}{deflated_sharpe_ratio(sr, n_all, len(monthly(net))):7.3f}"
              f"{sharpe_m(net[net.index < mid]):9.2f}{sharpe_m(net[net.index >= mid]):9.2f}"
              f"{drawdown(net):8.1%}{-b['cost'].mean() * 365:8.1%}")
        return net, mid

    line("27 unscaled (reference)", unscaled)
    for window, primary in VARIANTS:
        b, k = scaled_book(d, window)
        net, mid = line(f"28 scaled, {window}d vol" + ("  PRIMARY" if primary else ""), b)
        if primary:
            prim, pk, pmid = net, k, mid
    print(f"\nluck bar at {n_all} trials and {len(monthly(prim))} months: "
          f"{expected_max_sharpe(n_all, len(monthly(prim))):.2f}")

    yr = prim.groupby(prim.index.year).mean() * 365
    print("primary net by year: " + ", ".join(f"{y} {v:+.1%}" for y, v in yr.items()))
    print(f"primary scale: median {pk.median():.2f}, at the {CAP:.0f}x cap {(pk >= CAP).mean():.0%} "
          f"of days, below 0.5x {(pk < 0.5).mean():.0%}")
    m = monthly(prim)
    print(f"primary: months positive {(m > 0).mean():.0%}, worst month {m.min():.1%}")

    crit = {
        "Sharpe after costs >= 1.5": sharpe_m(prim) >= 1.5,
        "PSR(SR > 0) >= 0.95": psr(prim, 0) >= 0.95,
        "positive Sharpe in both halves": min(sharpe_m(prim[prim.index < pmid]),
                                              sharpe_m(prim[prim.index >= pmid])) > 0,
        "max drawdown under 30%": drawdown(prim) < 0.30,
    }
    print("\npass criteria for the primary (declared in advance)")
    for c, v in crit.items():
        print(f"  {'PASS' if v else 'FAIL'}  {c}")

    out = HERE / "reports"
    out.mkdir(exist_ok=True)
    prim.rename("net").to_csv(out / "vol_momentum_primary_daily.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
