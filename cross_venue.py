#!/usr/bin/env python3
"""Strategy 25: funding dispersion between Hyperliquid and dYdX v4.

    python3 cross_venue.py

The single-venue carry failed out of sample because its spot hedge leaves a
short perp exposed to squeezes, and because its excess decayed. This trade has
no spot leg. For each coin it shorts the perp on whichever venue pays more
funding and longs it on the one that pays less. The two perps track the same
index, so the position is delta-neutral and collects the funding spread.

Each leg posts 1/L margin, so a dollar of notional ties up 2/L of capital, and
both legs can be liquidated: the short on a rally, the long on a crash. Both
are modeled from Hyperliquid's daily high and low, since the two venues price
the same index.

Everything below was fixed in the strategy 25 declaration before any dYdX data
was pulled: the rule, the costs, the liquidation model, the January 2024 start,
the four variants, the primary, and the pass criteria.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from funding_carry import COST_PER_LEG, DATA, HERE
from pit_rerun import daily
from validate import (CRYPTO_FAMILY_INHERITED, MAINT, monthly, path_sharpes, psr,
                      sharpe_m, stationary_bootstrap)
from deflated_sharpe import deflated_sharpe_ratio, expected_max_sharpe
import registry

START = pd.Timestamp("2024-01-01", tz="UTC")
HALF_TRIP = 2 * COST_PER_LEG               # two legs, one direction
VARIANTS = [(2.0, 30, True), (2.0, 7, False), (3.0, 30, False), (3.0, 7, False)]


def panel() -> pd.DataFrame:
    hl = daily()
    dy = pd.read_parquet(DATA / "dydx_funding.parquet")
    # A handful of hours carry two prints; keep the last one for each hour.
    dy["hour"] = dy["ts"].dt.floor("h")
    dy = dy.sort_values("ts").drop_duplicates(["coin", "hour"], keep="last")
    dy["day"] = dy["hour"].dt.floor("D")
    dyd = dy.groupby(["coin", "day"])["rate"].sum().rename("dy_rate").reset_index()

    d = hl.merge(dyd, on=["coin", "day"], how="inner").sort_values(["coin", "day"])
    d = d.reset_index(drop=True)
    g = d.groupby("coin")
    d["spread"] = d["rate"] - d["dy_rate"]           # what short HL / long dYdX earns
    d["prev_close"] = g["close"].shift(1)
    d["rally"] = d["high"] / d["prev_close"] - 1
    d["drop"] = 1 - d["low"] / d["prev_close"]
    d["week"] = d["day"].dt.tz_localize(None).dt.to_period("W")
    for lb in (7, 30):
        d[f"trail{lb}"] = g["spread"].transform(
            lambda s, lb=lb: s.shift(1).rolling(lb).sum()) * 365 / lb
    return d


def book(d: pd.DataFrame, lev: float, lookback: int, liq_penalty: float = 0.05,
         detail: bool = False):
    x = d.copy()
    margin = 1 / lev
    cap = 2 * margin                                    # both legs post margin
    trail = x[f"trail{lookback}"]
    # Hold when the trailing spread, earned on capital, beats T-bills.
    on = (trail.abs() / cap > x["tbill"]) & trail.notna()
    want = (np.sign(trail) * on).astype(float)
    first = x["week"] != x.groupby("coin")["week"].shift(1)
    want = want.where(first).groupby(x["coin"]).ffill().fillna(0.0)
    expo = want * x["member"]                          # +1 short HL / long dYdX

    pnl = expo * x["spread"]
    # Cross-venue basis: Hyperliquid's side marked by its premium to the oracle.
    pnl = pnl - expo * x["premium"].groupby(x["coin"]).diff().fillna(0.0)
    # Daily collateral rebalancing between venues, charged like a trade.
    pnl = pnl - expo.abs() * 2 * COST_PER_LEG * x["ret"].abs().fillna(0.0)
    liq = ((x["rally"] >= margin - MAINT) | (x["drop"] >= margin - MAINT)).astype(float)
    pnl = pnl - expo.abs() * liq * (liq_penalty + 2 * HALF_TRIP)

    prev = expo.groupby(x["coin"]).shift(1).fillna(0.0)
    last = x.groupby("coin")["day"].transform("max") == x["day"]
    trades = (expo - prev).abs() + np.where(last, expo.abs(), 0.0)
    ex = expo.abs() * (-x["tbill"] / 365) + pnl / cap - trades * HALF_TRIP / cap

    keep = (x["member"] > 0) & (x["day"] >= START)
    b = ex[keep].groupby(x.loc[keep, "day"]).mean()
    if not detail:
        return b
    x["expo"], x["liq"] = expo, liq
    return b, x[keep]


def main() -> int:
    d = panel()
    rows = registry.entries()
    n_all = registry.trials()["n_trials"]
    n_fam = CRYPTO_FAMILY_INHERITED + sum(max(1, r.get("variants", 1)) for r in rows
                                          if r["kind"] == "declare")
    live = d[(d.member > 0) & (d.day >= START)]
    print(f"{live.coin.nunique()} coins on both venues while in the universe, "
          f"{live.day.min().date()} to {live.day.max().date()}, "
          f"{live.groupby('day').coin.size().mean():.1f} per day on average")
    print(f"trials: {n_all} total, {n_fam} in the crypto family "
          f"(bars {expected_max_sharpe(n_all, 33):.2f} / {expected_max_sharpe(n_fam, 33):.2f} "
          f"at 33 months)\n")

    # What the spread is made of: Hyperliquid's interest constant has no dYdX twin.
    sp = live.groupby(live.day.dt.year)
    print("the raw spread, short HL / long dYdX, equal weight, annualized")
    print(pd.DataFrame({
        "HL funding": sp["rate"].mean() * 365,
        "dYdX funding": sp["dy_rate"].mean() * 365,
        "spread": sp["spread"].mean() * 365,
        "HL interest leg": sp["interest"].mean() * 365,
        "spread ex-interest": (sp["spread"].mean() - sp["interest"].mean()) * 365,
    }).to_string(float_format=lambda v: f"{v:8.1%}"))

    print(f"\n{'variant':<22}{'excess':>8}{'SR':>7}{'PSR>0':>7}{'PSR>1.5':>8}"
          f"{'DSR fam':>8}{'DSR all':>8}{'SR 24':>7}{'SR 25-26':>9}{'liq/yr':>8}")
    for lev, lb, primary in VARIANTS:
        b, x = book(d, lev, lb, detail=True)
        sr = sharpe_m(b)
        n = len(monthly(b))
        early = b[b.index < "2025-01-01"]
        late = b[b.index >= "2025-01-01"]
        held = x[x.expo != 0]
        liq_rate = held["liq"].sum() / (len(held) / 365) if len(held) else 0
        name = f"{lev:.0f}x, {lb}d" + ("  PRIMARY" if primary else "")
        print(f"{name:<22}{b.mean() * 365:8.1%}{sr:7.2f}{psr(b, 0):7.2f}{psr(b, 1.5):8.2f}"
              f"{deflated_sharpe_ratio(sr, n_fam, n):8.3f}{deflated_sharpe_ratio(sr, n_all, n):8.3f}"
              f"{sharpe_m(early):7.2f}{sharpe_m(late):9.2f}{liq_rate:8.2f}")
        if primary:
            prim, px = b, x

    print("\nprimary, liquidation penalty sensitivity")
    for pen in (0.02, 0.05, 0.10):
        b = book(d, 2.0, 30, liq_penalty=pen)
        print(f"  {pen:4.0%}: excess {b.mean() * 365:6.1%}  Sharpe {sharpe_m(b):5.2f}")

    held = px[px.expo != 0]
    print(f"\nprimary: on {len(held) / len(px):.0%} of coin-days; "
          f"{(held.expo > 0).mean():.0%} of those short Hyperliquid / long dYdX")
    paths = stationary_bootstrap(prim, n_paths=3000)
    lo, mid, hi = np.percentile(path_sharpes(paths), [5, 50, 95])
    print(f"bootstrap Sharpe 5th / 50th / 95th: {lo:.2f} / {mid:.2f} / {hi:.2f}")
    yr = prim.groupby(prim.index.year).mean() * 365
    print("primary excess by year: " + ", ".join(f"{y} {v:+.1%}" for y, v in yr.items()))
    m = monthly(prim)
    print(f"months positive {(m > 0).mean():.0%}, worst month {m.min():.2%}")

    crit = {
        "Sharpe after 5% liquidations >= 1.5": sharpe_m(prim) >= 1.5,
        "PSR(SR > 0) >= 0.95": psr(prim, 0) >= 0.95,
        "Sharpe >= 1.5 in 2025-26 alone": sharpe_m(prim[prim.index >= "2025-01-01"]) >= 1.5,
    }
    print("\npass criteria (declared in advance)")
    for k, v in crit.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")

    out = HERE / "reports"
    out.mkdir(exist_ok=True)
    prim.rename("excess").to_csv(out / "cross_venue_primary_daily.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
