#!/usr/bin/env python3
"""dYdX v4 hourly funding for the coins in the Hyperliquid universe.

    python3 ingest_dydx.py

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


def main() -> int:
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
