#!/usr/bin/env python3
"""The carry rules on BitMEX, 2017 to 2023: time the strategies never saw.

    python3 out_of_time.py

Every carry result here was found on Hyperliquid from May 2023, a sample with no
bear market in it. BitMEX's history covers the 2018 crash and 2022's Luna, 3AC
and FTX collapses. This runs the rules already declared, with their parameters
unchanged, through validate.py's own engine (same costs, same liquidation
model) on BTC and ETH perps against their spot indices.

The window was fixed in the registry before any BitMEX data was pulled: from
the first day with both funding and a spot index through 2023-04-30, strictly
before the Hyperliquid sample. Later dates are shown for continuity only.

BitMEX's XBTUSD is an inverse contract, which a linear USD model handles well.
ETHUSD is a QUANTO contract, settled in BTC, and the precommitment's choice to
model it as linear was a mistake. A daily-rebalanced short quanto hedged with
spot ETH carries a cross-term of minus (ETH return x BTC return), and over
2018-2023 that cost 57.8% a year against 57.3% of funding: the funding was the
price of the quanto risk, not a carry. Both versions are printed, the
precommitted one first, so the error is on the record.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from funding_carry import DATA, HERE
from validate import book, monthly, psr, sharpe_m, MAINT
from deflated_sharpe import deflated_sharpe_ratio
import registry

END = pd.Timestamp("2023-04-30 23:59", tz="UTC")
SPECS = [
    ("20 always on, 3x", dict(lookback=None, lev=3.0)),
    ("21 switched 30d, 3x", dict(lookback=30, lev=3.0)),
    ("24 equal, 2x", dict(lookback=30, lev=2.0)),
    ("24 inverse-vol, 2x (primary)", dict(lookback=30, lev=2.0, sizing="invvol")),
]


def with_quanto(d: pd.DataFrame) -> pd.DataFrame:
    """Charge ETH's quanto cross-term: short quanto + long spot, rebalanced daily."""
    d = d.copy()
    btc = d[d.coin == "BTC"].set_index("day")["ret"]
    eth = d["coin"] == "ETH"
    d.loc[eth, "basis_pnl"] -= d.loc[eth, "ret"] * d.loc[eth, "day"].map(btc).fillna(0).values
    return d


def panel() -> pd.DataFrame:
    f = pd.read_parquet(DATA / "bitmex_funding.parquet")
    f["day"] = f["ts"].dt.floor("D")
    fd = f.groupby(["coin", "day"])["rate"].sum().reset_index()
    p = pd.read_parquet(DATA / "bitmex_daily.parquet")
    d = p.merge(fd, on=["coin", "day"], how="inner").sort_values(["coin", "day"])
    d = d.reset_index(drop=True)
    g = d.groupby("coin")
    d["ret"] = g["perp_close"].pct_change()
    d["basis_pnl"] = g["spot_close"].pct_change() - d["ret"]    # long spot, short perp
    d["rally"] = d["perp_high"] / g["perp_close"].shift(1) - 1
    d["vol30"] = g["ret"].transform(lambda r: r.shift(1).rolling(30, min_periods=20).std())
    for lb in (7, 14, 30, 60):
        d[f"trail{lb}"] = g["rate"].transform(
            lambda s, lb=lb: s.shift(1).rolling(lb).sum()) * 365 / lb
    tb = pd.read_parquet(DATA / "tbill.parquet").set_index("date")["yld"]
    d["tbill"] = tb.reindex(d["day"].dt.tz_localize(None).dt.normalize(), method="ffill").values
    d["sc_growth"] = 1.0                      # the stablecoin gate is off in every spec here
    d["week"] = d["day"].dt.tz_localize(None).dt.to_period("W")
    d["member"] = 1.0
    d["interest"] = 0.0001 * 3                # BitMEX's interest leg: 0.01% per 8h
    return d.dropna(subset=["basis_pnl", "tbill"])


def run(d: pd.DataFrame, lookback, lev, sizing="equal") -> pd.Series:
    if lookback is None:
        # Always on: a trailing signal that always clears the hurdle.
        x = d.copy()
        x["trail30"] = 1e9
        return book(x, lev=lev, sizing=sizing, liq_penalty=0.05)
    return book(d, lookback=lookback, lev=lev, sizing=sizing, liq_penalty=0.05)


def main() -> int:
    d = panel()
    n_all = registry.trials()["n_trials"]
    oot = d[d.day <= END]
    print(f"BitMEX: {d.coin.nunique()} coins, {oot.day.min().date()} to {END.date()} "
          f"out of time ({len(oot):,} coin-days); continuity to {d.day.max().date()}\n")

    yr = oot.groupby([oot.day.dt.year, "coin"])["rate"].sum().unstack()
    days = oot.groupby([oot.day.dt.year, "coin"])["rate"].size().unstack()
    print("annualized funding by year (short perp receives)")
    print((yr / days * 365).to_string(float_format=lambda v: f"{v:8.1%}"))
    at_floor = (np.isclose(oot["rate"], 0.0003, atol=1e-7)).mean()
    print(f"days paying exactly the 0.01%/8h interest constant: {at_floor:.0%}\n")

    for lev in (2, 3):
        ev = (oot["rally"] >= 1 / lev - MAINT).sum()
        print(f"liquidation days at {lev}x: {ev} ({ev / (len(oot) / 365):.2f} per coin-year)")

    e = oot[oot.coin == "ETH"].merge(oot[oot.coin == "BTC"][["day", "ret"]], on="day",
                                     suffixes=("", "_btc"))
    q = (-e["ret"] * e["ret_btc"]).mean() * 365
    print(f"\nETH quanto: funding {e['rate'].mean() * 365:.1%} a year, cross-term {q:.1%}")

    for label, frame in (("AS PRECOMMITTED (ETH quanto modeled as linear)", d),
                         ("CORRECTED (ETH quanto cross-term charged)", with_quanto(d))):
        print(f"\n{label}")
        print(f"{'spec':<32}{'excess':>8}{'SR':>7}{'PSR>0':>7}{'DSR':>7}"
              f"{'2018':>8}{'2022':>8}{'  23-05 on SR':>14}")
        rows = []
        for name, kw in SPECS:
            b = run(frame, **kw)
            o = b[b.index <= END]
            later = b[b.index > END]
            y = o.groupby(o.index.year).mean() * 365
            sr = sharpe_m(o)
            print(f"{name:<32}{o.mean() * 365:8.1%}{sr:7.2f}{psr(o, 0):7.2f}"
                  f"{deflated_sharpe_ratio(sr, n_all, len(monthly(o))):7.3f}"
                  f"{y.get(2018, np.nan):8.1%}{y.get(2022, np.nan):8.1%}{sharpe_m(later):14.2f}")
            rows.append({"spec": name, "excess": o.mean() * 365, "sharpe": sr,
                         **{str(k): v for k, v in y.items()}})

    print("\nBTC alone, the clean contract")
    for name, kw in SPECS:
        b = run(d[d.coin == "BTC"], **kw)
        o = b[b.index <= END]
        print(f"  {name:<30} excess {o.mean() * 365:6.1%}  Sharpe {sharpe_m(o):5.2f}")
    r = pd.DataFrame(rows).set_index("spec")
    print("\ncorrected excess over T-bills by year, out of time")
    print(r[[c for c in r.columns if c.isdigit()]].to_string(float_format=lambda v: f"{v:7.1%}"))

    out = HERE / "reports"
    out.mkdir(exist_ok=True)
    r.to_csv(out / "out_of_time.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
