#!/usr/bin/env python3
"""dYdX v4 hourly funding for the coins in the Hyperliquid universe.

    python3 ingest_dydx.py
    python3 ingest_dydx.py --candles   # daily volume and open interest: capacity
    python3 ingest_dydx.py --status    # which markets stopped trading, and when

The second venue for strategy 25. dYdX v4 is a decentralised perp exchange
whose indexer serves funding history publicly, with no key, back to its launch
in late October 2023, 1,000 hourly prints per request.

Coins are matched by ticker. Hyperliquid quotes some small-priced coins per
thousand (kPEPE, kSHIB); the funding rate is a fraction of notional and does
not depend on the contract size, so kPEPE matches dYdX's PEPE-USD directly.
Each coin is cached as it finishes, so a killed run resumes.
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
CACHE = DATA / "dydx_funding_cache"
BASE = "https://indexer.dydx.trade/v4"
START = pd.Timestamp("2023-10-01", tz="UTC")


def get(path: str, retries: int = 6):
    # Raise rather than return nothing: a silent empty page is how the
    # Hyperliquid ingest once truncated 9 of 16 coins.
    for a in range(retries):
        try:
            with urllib.request.urlopen(BASE + path, timeout=60) as f:
                return json.loads(f.read().decode())
        except Exception as e:
            err = e
            time.sleep(2.0 * 2 ** a)
    raise RuntimeError(f"dYdX request failed after {retries} tries: {path}: {err}")


def markets() -> set[str]:
    return set(get("/perpetualMarkets")["markets"].keys())


def history(ticker: str) -> pd.DataFrame:
    out, before = [], None
    while True:
        q = {"limit": 1000}
        if before:
            q["effectiveBeforeOrAt"] = before
        page = get(f"/historicalFunding/{ticker}?" + urllib.parse.urlencode(q))
        rows = page.get("historicalFunding", [])
        if not rows:
            break
        out.extend(rows)
        oldest = pd.Timestamp(rows[-1]["effectiveAt"])
        if len(rows) < 1000 or oldest <= START:
            break
        before = (oldest - pd.Timedelta(milliseconds=1)).isoformat().replace("+00:00", "Z")
        time.sleep(0.1)
    if not out:
        return pd.DataFrame()
    d = pd.DataFrame(out).drop_duplicates("effectiveAt")
    d["ts"] = pd.to_datetime(d["effectiveAt"], utc=True)
    d["rate"] = d["rate"].astype(float)
    return d[["ts", "rate"]].sort_values("ts")


def candles(ticker: str) -> pd.DataFrame:
    """Daily candles: dYdX's own record of how much each market actually traded."""
    out, to = [], None
    while True:
        q = {"resolution": "1DAY", "limit": 1000}
        if to:
            q["toISO"] = to
        rows = get(f"/candles/perpetualMarkets/{ticker}?" + urllib.parse.urlencode(q))["candles"]
        if not rows:
            break
        out.extend(rows)
        oldest = pd.Timestamp(rows[-1]["startedAt"])
        if len(rows) < 1000 or oldest <= START:
            break
        to = (oldest - pd.Timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        time.sleep(0.1)
    if not out:
        return pd.DataFrame()
    d = pd.DataFrame(out).drop_duplicates("startedAt")
    d["day"] = pd.to_datetime(d["startedAt"], utc=True)
    d["usd_volume"] = d["usdVolume"].astype(float)
    d["oi_usd"] = d["startingOpenInterest"].astype(float) * d["close"].astype(float)
    d["trades"] = d["trades"].astype(int)
    return d[["day", "usd_volume", "oi_usd", "trades"]]


def pairs() -> list[tuple[str, str]]:
    # SURVIVORSHIP AND RENAMES: coins are matched by name against TODAY's dYdX
    # market list, so 15 of the 110 universe coins have no match (as of
    # 2026-10-29): BIGTIME, CASHCAT, CFX, CHIP, CYBER, FARTCOIN, FTT, INIT,
    # LAUNCHCOIN, LOOM, MANTA, OGN, PONS, RNDR, YGG. Some are renames that this
    # exact-name match misses: Hyperliquid's RNDR trades on dYdX as RENDER-USD.
    # Others (FTT, FARTCOIN) have no dYdX market at all. Settled markets ARE
    # matched, because the list still includes them; see --status
    # (audit 2026-10-29).
    universe = pd.read_parquet(DATA / "hl_universe.parquet")["coin"].unique()
    listed = markets()
    out = []
    for c in sorted(universe):
        t = (c[1:] if c.startswith("k") and c[1:].isupper() else c) + "-USD"
        if t in listed:
            out.append((c, t))
    return out


def main_candles() -> int:
    frames = []
    for i, (c, t) in enumerate(pairs(), 1):
        d = candles(t)
        d["coin"] = c
        frames.append(d)
        print(f"\r  candles {i} {c:<10}", end="", flush=True)
    print()
    f = pd.concat(frames, ignore_index=True)
    f.to_parquet(DATA / "dydx_candles.parquet", index=False)
    print(f"dydx candles: {len(f):,} coin-days, {f.coin.nunique()} coins, "
          f"{f.day.min().date()} to {f.day.max().date()}")
    return 0


def stop_time(rates: pd.Series, ts: pd.Series, trade_days: pd.Series):
    """When a settled market stopped, from the data alone, or None.

    After final settlement the indexer keeps printing rate = 0, so the spread
    becomes pure Hyperliquid funding (audit 2026-10-29, finding A2). But live
    dYdX markets print exactly zero about half the time, so a zero run alone
    proves nothing. A market counts as stopped once BOTH hold: its funding has
    been zero ever since, and it has had no trades. Only applied to markets
    that are not ACTIVE today."""
    x = pd.DataFrame({"ts": ts, "rate": rates}).sort_values("ts")
    nonzero = x.loc[x["rate"] != 0, "ts"]
    later = x.loc[x["ts"] > nonzero.max(), "ts"] if len(nonzero) else x["ts"]
    zero_from = later.min() if len(later) else None          # start of the final zero run
    end = x["ts"].max()
    after_trades = (trade_days.max() + pd.Timedelta(days=1)) if len(trade_days) else None
    if zero_from is None:                    # still printing nonzero funding at the end
        return after_trades if after_trades is not None and after_trades <= end else None
    if after_trades is None:
        return zero_from
    stop = max(zero_from, after_trades)
    return stop if stop <= end else None


def main_status() -> int:
    """Market status today, plus the inferred stop for every non-ACTIVE market."""
    m = get("/perpetualMarkets")["markets"]
    f = pd.read_parquet(DATA / "dydx_funding.parquet")
    k = pd.read_parquet(DATA / "dydx_candles.parquet")
    rows = []
    for c, t in sorted(f.groupby("coin")["ticker"].first().items()):
        status = m.get(t, {}).get("status", "NOT LISTED")
        stop = None
        if status != "ACTIVE":
            x = f[f.coin == c]
            days = k.loc[(k.coin == c) & (k.trades > 0), "day"]
            stop = stop_time(x["rate"], x["ts"], days)
        rows.append({"coin": c, "ticker": t, "status": status, "stopped": stop})
    d = pd.DataFrame(rows)
    d["as_of"] = pd.Timestamp.now(tz="UTC").floor("s")
    d.to_parquet(DATA / "dydx_status.parquet", index=False)
    dead = d[d.stopped.notna()].sort_values("stopped")
    print(f"{len(d)} markets; {(d.status != 'ACTIVE').sum()} not ACTIVE today; "
          f"{len(dead)} stopped inside the data:")
    for _, r in dead.iterrows():
        print(f"  {r.coin:<8}{r.ticker:<12}{r.status:<18} stopped {r.stopped:%Y-%m-%d}")
    return 0


def main() -> int:
    if "--candles" in sys.argv:
        return main_candles()
    if "--status" in sys.argv:
        return main_status()
    universe = pd.read_parquet(DATA / "hl_universe.parquet")["coin"].unique()
    listed = markets()
    pairs = []
    for c in sorted(universe):
        t = (c[1:] if c.startswith("k") and c[1:].isupper() else c) + "-USD"
        if t in listed:
            pairs.append((c, t))
    print(f"{len(pairs)} of {len(universe)} universe coins have a dYdX market")

    CACHE.mkdir(exist_ok=True)
    frames = []
    for i, (c, t) in enumerate(pairs, 1):
        path = CACHE / f"{c}.parquet"
        if path.exists():
            d = pd.read_parquet(path)
        else:
            d = history(t)
            d["coin"], d["ticker"] = c, t
            d.to_parquet(path, index=False)
        frames.append(d)
        print(f"  {i}/{len(pairs)} {c:<10}{t:<14} rows={sum(len(x) for x in frames):,}", flush=True)
    f = pd.concat([x for x in frames if not x.empty], ignore_index=True)
    f.to_parquet(DATA / "dydx_funding.parquet", index=False)
    print(f"dydx funding: {len(f):,} prints, {f.coin.nunique()} coins, "
          f"{f.ts.min().date()} to {f.ts.max().date()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
