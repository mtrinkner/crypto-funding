#!/usr/bin/env python3
"""What would the forward test's trades actually cost? Measured, not assumed.

    python3 exec_costs.py snapshot   # record both order books for every coin held
    python3 exec_costs.py summary    # measured cost vs the 3bp per leg xv_v1 assumes

Strategy 25 showed the Hyperliquid-dYdX dispersion is real before costs and
that costs decide the trade. xv_v1 assumes 3bp per leg, i.e. resting orders
that mostly get filled. That is an assumption, and the forward test cannot
check it, because it never trades.

This can, partly. For each coin xv_v1 currently holds, it reads both live order
books and works out what entering the position would cost right now:
  - the half-spread on each venue
  - the slippage to fill $10k and $100k on the side the position needs
    (short Hyperliquid = sell into its bids, long dYdX = buy from its asks)
  - plus each venue's published base-tier taker fee
Snapshots go to a hash-chained ledger (data/exec_costs.jsonl), several a day,
so the summary is a distribution rather than one lucky moment.

It also records 24-hour volume and open interest on both venues, because a
funding rate set in a market nobody trades is a rate nobody can collect at size.

What it still cannot measure: whether a resting order gets filled, and what
happens to price after it does (adverse selection). Those need real orders.

Deliberately separate from forward_xv.py, which is frozen. This changes nothing
about how the forward test is scored.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import ledger

ROOT = Path(__file__).resolve().parent
POSITIONS = ROOT / "data" / "forward_xv.jsonl"
LEDGER = ROOT / "data" / "exec_costs.jsonl"
SIZES = (10_000, 100_000)
ASSUMED_BPS = 3.0                       # xv_v1's cost_per_leg
# Published base-tier fees, as of October 2026. Higher volume tiers pay less.
FEES_BPS = {"hyperliquid": {"taker": 4.5, "maker": 1.5},
            "dydx": {"taker": 5.0, "maker": 1.0}}


def _get(req, retries: int = 5):
    for a in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as f:
                return json.loads(f.read().decode())
        except Exception as e:
            err = e
            time.sleep(2.0 * 2 ** a)
    raise RuntimeError(f"request failed after {retries} tries: {err}")


def hl_post(payload: dict):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info", method="POST",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    return _get(req)


def hl_book(coin: str, sig: int | None = None):
    q = {"type": "l2Book", "coin": coin}
    if sig:
        q["nSigFigs"] = sig
    b = hl_post(q)["levels"]
    bids = [(float(x["px"]), float(x["sz"])) for x in b[0]]
    asks = [(float(x["px"]), float(x["sz"])) for x in b[1]]
    return bids, asks


def hl_deep_slip(coin: str, side: str, mid: float, usd: float):
    """Hyperliquid's full-precision book stops at 20 levels. When that is not
    enough, re-read it in coarser price buckets. A bucket is quoted at its edge,
    so this slightly overstates the cost rather than understating it."""
    for sig in (4, 3, 2):
        bids, asks = hl_book(coin, sig)
        v = fill_cost(bids if side == "sell" else asks, mid, usd)
        if v is not None:
            return v, sig
    return None, None


def market_stats() -> dict:
    """24h volume and open interest on both venues, in USD: capacity, not cost."""
    meta, ctx = hl_post({"type": "metaAndAssetCtxs"})
    hl = {}
    for u, c in zip(meta["universe"], ctx):
        px = float(c.get("markPx") or 0)
        hl[u["name"]] = {"vol24h": float(c.get("dayNtlVlm") or 0),
                         "oi": float(c.get("openInterest") or 0) * px}
    dy = {}
    for t, m in _get(urllib.request.Request(
            "https://indexer.dydx.trade/v4/perpetualMarkets"))["markets"].items():
        dy[t] = {"vol24h": float(m.get("volume24H") or 0),
                 "oi": float(m.get("openInterest") or 0) * float(m.get("oraclePrice") or 0),
                 "trades24h": int(m.get("trades24H") or 0)}
    return {"hyperliquid": hl, "dydx": dy}


def dydx_book(ticker: str):
    b = _get(urllib.request.Request(
        f"https://indexer.dydx.trade/v4/orderbooks/perpetualMarket/{ticker}"))
    bids = [(float(x["price"]), float(x["size"])) for x in b["bids"]]
    asks = [(float(x["price"]), float(x["size"])) for x in b["asks"]]
    return bids, asks


def dydx_ticker(coin: str) -> str:
    return (coin[1:] if coin.startswith("k") and coin[1:].isupper() else coin) + "-USD"


def fill_cost(levels, mid: float, usd: float):
    """Average price paid to fill `usd` of notional, as bps away from mid.
    None if the visible book is not deep enough."""
    left, cost, qty = usd, 0.0, 0.0
    for px, sz in levels:
        take = min(left, px * sz)
        cost += take
        qty += take / px
        left -= take
        if left <= 1e-9:
            return abs(cost / qty / mid - 1) * 1e4
    return None


def measure(bids, asks, side: str) -> dict:
    """side 'sell' walks the bids, 'buy' walks the asks."""
    if not bids or not asks:
        return {"ok": False, "why": "empty book"}
    bb, ba = bids[0][0], asks[0][0]
    if bb >= ba:
        return {"ok": False, "why": "crossed book"}
    mid = (bb + ba) / 2
    levels = bids if side == "sell" else asks
    out = {"ok": True, "mid": mid, "half_spread_bps": (ba - bb) / mid / 2 * 1e4}
    for s in SIZES:
        out[f"slip_{s // 1000}k_bps"] = fill_cost(levels, mid, s)
    return out


def latest_positions() -> dict:
    rows = [r for r in ledger.read_all(POSITIONS) if r["kind"] == "xv_positions"]
    if not rows:
        sys.exit("no xv_v1 positions written yet")
    return rows[-1]


def cmd_snapshot(_a) -> int:
    p = latest_positions()
    held = {c: e for c, e in p["expo"].items() if e}
    stats = market_stats()
    coins = {}
    for c, e in held.items():
        # +1 = short Hyperliquid / long dYdX; -1 the reverse.
        hl_side, dy_side = ("sell", "buy") if e > 0 else ("buy", "sell")
        try:
            h = measure(*hl_book(c), hl_side)
            if h["ok"]:
                for sz in SIZES:
                    k = f"slip_{sz // 1000}k_bps"
                    if h[k] is None:
                        h[k], h[f"{k}_sigfigs"] = hl_deep_slip(c, hl_side, h["mid"], sz)
        except Exception as ex:
            h = {"ok": False, "why": str(ex)[:120]}
        try:
            d = measure(*dydx_book(dydx_ticker(c)), dy_side)
        except Exception as ex:
            d = {"ok": False, "why": str(ex)[:120]}
        coins[c] = {"expo": e,
                    "hyperliquid": {"side": hl_side, **h, **stats["hyperliquid"].get(c, {})},
                    "dydx": {"side": dy_side, **d, **stats["dydx"].get(dydx_ticker(c), {})}}
        time.sleep(0.2)
    entry = {"kind": "exec_snapshot",
             "taken_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "positions_week": p["week_start"], "positions_hash": p["entry_hash"],
             "fees_bps": FEES_BPS, "coins": coins}
    ledger.append([entry], LEDGER)
    ok = sum(v["hyperliquid"]["ok"] and v["dydx"]["ok"] for v in coins.values())
    print(f"snapshot of {len(coins)} held coins ({ok} with both books usable); "
          f"{ledger.verify(LEDGER)}")
    return 0


def table() -> pd.DataFrame:
    rows = []
    for r in ledger.read_all(LEDGER):
        if r["kind"] != "exec_snapshot":
            continue
        for c, v in r["coins"].items():
            for venue in ("hyperliquid", "dydx"):
                m = v[venue]
                row = {"taken_at": r["taken_at"], "coin": c, "venue": venue, "ok": m["ok"],
                       "why": m.get("why"), "vol24h": m.get("vol24h"), "oi": m.get("oi")}
                if m["ok"]:
                    fee = r["fees_bps"][venue]
                    row["half_spread"] = m["half_spread_bps"]
                    row["maker"] = fee["maker"]
                    for s in SIZES:
                        k = f"slip_{s // 1000}k_bps"
                        row[f"taker_{s // 1000}k"] = (m[k] + fee["taker"]
                                                      if m[k] is not None else np.nan)
                rows.append(row)
    return pd.DataFrame(rows)


def cmd_summary(_a) -> int:
    t = table()
    if t.empty:
        print("no snapshots yet")
        return 0
    n = t["taken_at"].nunique()
    print(f"{n} snapshots, {t.coin.nunique()} coins, {t.taken_at.min()} to {t.taken_at.max()}")
    bad = t[~t.ok]
    if len(bad):
        print(f"unusable books: {len(bad)} of {len(t)} ({bad.why.value_counts().to_dict()})")
    ok = t[t.ok]
    print(f"\ncost per leg in bps, median across snapshots (xv_v1 assumes {ASSUMED_BPS:.0f})")
    g = ok.groupby(["coin", "venue"])[["half_spread", "taker_10k", "taker_100k", "maker"]].median()
    print(g.unstack("venue").round(1).to_string())
    both = ok.groupby("venue")[["half_spread", "taker_10k", "taker_100k", "maker"]].median()
    print("\nall coins")
    print(both.round(1).to_string())
    cap = t.groupby(["coin", "venue"])[["vol24h", "oi"]].median().unstack("venue") / 1e6
    print("\ncapacity: median 24h volume and open interest, $m")
    print(cap.round(2).to_string())
    # One unit of xv_v1 trades both legs; its spec charges 2 x 3bp.
    leg = ok.groupby(["taken_at", "coin"])["taker_10k"].mean()
    print(f"\ntaking liquidity at $10k, average of the two legs: median {leg.median():.1f}bp, "
          f"75th pct {leg.quantile(0.75):.1f}bp vs {ASSUMED_BPS:.0f}bp assumed")
    print(f"  share of coin-snapshots where taking costs more than assumed: "
          f"{(leg > ASSUMED_BPS).mean():.0%}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snapshot")
    sub.add_parser("summary")
    a = ap.parse_args()
    return {"snapshot": cmd_snapshot, "summary": cmd_summary}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
