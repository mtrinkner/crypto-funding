#!/usr/bin/env python3
"""Forward test of strategy 26 (xv_v1): Hyperliquid vs dYdX funding dispersion.

    python3 forward_xv.py freeze      # once: write the manifest and hash this file
    python3 forward_xv.py run         # weekly: score last week, then commit next week
    python3 forward_xv.py status      # the record so far
    python3 forward_xv.py run --dry-run [--as-of 2026-09-28]   # print, write nothing

WHY A FORWARD TEST. Strategy 25 showed a real gross dispersion between the two
venues' funding that its declared costs consumed. This spec cuts those costs,
but it was designed after seeing that, so its backtest is in-sample and worth
nothing as evidence. The only clean test is data that did not exist when the
rule was written down.

HOW IT STAYS HONEST.
  - The spec and a SHA-256 of this file are frozen in models/xv_v1.json. `run`
    refuses to start if either has changed. Fixing a bug means xv_v2, a new
    trial, not an edit.
  - Each run first SCORES the positions written at the previous run against
    what then happened, and only then WRITES the positions for the coming week,
    before their outcome exists. Both go to a hash-chained ledger
    (data/forward_xv.jsonl). A deleted bad week breaks every hash after it.
  - `--as-of` only works with `--dry-run`, so history cannot be backfilled
    into the live record.

Self-contained on purpose: every function the result depends on is in this
file, so the hash covers all of it.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import ledger

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "models" / "xv_v1.json"
LEDGER = ROOT / "data" / "forward_xv.jsonl"

SPEC = {
    "name": "xv_v1",
    "registry_strategy_id": 26,
    "venues": ["hyperliquid", "dydx_v4"],
    "universe": "weekly top 20 Hyperliquid perps by trailing 30-day notional, listed on dYdX",
    "top_n": 20,
    "volume_days": 30,
    "signal_days": 30,
    "min_hours_each_venue": 600,
    "leverage": 2.0,
    "entry_buffer": 0.02,
    "cost_per_leg": 0.0003,
    "collateral_move_cost": 0.0001,
    "maintenance": 0.03,
    "liquidation_penalty": 0.05,
    "review": "weekly, Monday 00:00 UTC",
    "pass": "at 52 live weeks: annualized Sharpe of weekly excess >= 1.5 and PSR(SR>0) >= 0.95",
    "kill": "cumulative live excess below -5% of capital",
    "kill_level": -0.05,
    "pass_weeks": 52,
}

HL = "https://api.hyperliquid.xyz/info"
DYDX = "https://indexer.dydx.trade/v4"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTB3"
WINDOW_HOURS = 12


# ------------------------------------------------------------------ fetching
# Every fetch raises on failure. A silent empty response once truncated nine
# coins in this project's history; a forward test that scores a week on missing
# data is worse than one that skips a run and says so.

def _http(req, retries: int = 6):
    for a in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as f:
                return f.read().decode()
        except Exception as e:
            err = e
            time.sleep(2.0 * 2 ** a)
    raise RuntimeError(f"request failed after {retries} tries: {err}")


def hl(payload: dict):
    req = urllib.request.Request(HL, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    return json.loads(_http(req))


def dydx(path: str):
    return json.loads(_http(urllib.request.Request(DYDX + path)))


def hl_candles(coin: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    c = hl({"type": "candleSnapshot", "req": {
        "coin": coin, "interval": "1d",
        "startTime": int(start.timestamp() * 1000), "endTime": int(end.timestamp() * 1000) - 1}})
    if not c:
        return pd.DataFrame()
    d = pd.DataFrame(c)
    d["day"] = pd.to_datetime(d["t"].astype("int64"), unit="ms", utc=True)
    for k, s in (("close", "c"), ("high", "h"), ("low", "l")):
        d[k] = d[s].astype(float)
    d["notional"] = d["v"].astype(float) * d["close"]
    # Only finished days: a candle that opens at or after `end` is not known yet.
    return d.loc[d["day"] < end, ["day", "close", "high", "low", "notional"]]


def hl_funding(coin: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    out, s = [], int(start.timestamp() * 1000)
    e = int(end.timestamp() * 1000)
    while True:
        b = hl({"type": "fundingHistory", "coin": coin, "startTime": s, "endTime": e - 1})
        if not b:
            break
        out.extend(b)
        last = b[-1]["time"]
        if len(b) < 500 or last <= s:
            break
        s = last + 1
        time.sleep(0.2)
    if not out:
        return pd.DataFrame(columns=["ts", "rate", "premium"])
    d = pd.DataFrame(out).drop_duplicates("time")
    d["ts"] = pd.to_datetime(d["time"].astype("int64"), unit="ms", utc=True)
    d["rate"] = d["fundingRate"].astype(float)
    d["premium"] = pd.to_numeric(d["premium"], errors="coerce")
    return d.loc[(d.ts >= start) & (d.ts < end), ["ts", "rate", "premium"]].sort_values("ts")


def dydx_funding(ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    out, before = [], (end - pd.Timedelta(milliseconds=1))
    while True:
        q = urllib.parse.urlencode({"limit": 1000, "effectiveBeforeOrAt":
                                    before.isoformat().replace("+00:00", "Z")})
        rows = dydx(f"/historicalFunding/{ticker}?{q}").get("historicalFunding", [])
        if not rows:
            break
        out.extend(rows)
        oldest = pd.Timestamp(rows[-1]["effectiveAt"])
        if len(rows) < 1000 or oldest < start:
            break
        before = oldest - pd.Timedelta(milliseconds=1)
    if not out:
        return pd.DataFrame(columns=["ts", "rate"])
    d = pd.DataFrame(out)
    d["ts"] = pd.to_datetime(d["effectiveAt"], utc=True)
    d["rate"] = d["rate"].astype(float)
    d["hour"] = d["ts"].dt.floor("h")
    d = d.sort_values("ts").drop_duplicates("hour", keep="last")
    return d.loc[(d.ts >= start) & (d.ts < end), ["ts", "rate"]]


def tbill(asof: pd.Timestamp) -> float:
    d = pd.read_csv(io.StringIO(_http(urllib.request.Request(FRED))))
    d.columns = ["date", "yld"]
    d["date"] = pd.to_datetime(d["date"]).dt.tz_localize("UTC")
    d["yld"] = pd.to_numeric(d["yld"], errors="coerce")
    d = d.dropna()
    return float(d.loc[d.date < asof, "yld"].iloc[-1]) / 100


def dydx_ticker(coin: str, listed: set[str]) -> str | None:
    t = (coin[1:] if coin.startswith("k") and coin[1:].isupper() else coin) + "-USD"
    return t if t in listed else None


# ------------------------------------------------------------------ the rule

def universe(t: pd.Timestamp, listed: set[str]) -> list[str]:
    """Top N Hyperliquid perps by notional over the volume window before t,
    among those listed on Hyperliquid the day before and on dYdX now."""
    meta = hl({"type": "meta"})["universe"]
    start = t - pd.Timedelta(days=SPEC["volume_days"])
    vol = {}
    for m in meta:
        if m.get("isDelisted"):
            continue
        c = hl_candles(m["name"], start, t)
        if not c.empty and (c["day"] == t - pd.Timedelta(days=1)).any():
            vol[m["name"]] = c["notional"].sum()
        time.sleep(0.1)
    ranked = sorted(vol, key=vol.get, reverse=True)[:SPEC["top_n"]]
    return [c for c in ranked if dydx_ticker(c, listed)]


def decide(spread: float | None, prev: int, rf: float) -> int:
    """+1 short Hyperliquid / long dYdX, -1 the reverse, 0 flat in T-bills."""
    if spread is None or math.isnan(spread):
        return 0
    on_cap = abs(spread) / (2 / SPEC["leverage"])
    side = 1 if spread > 0 else -1
    enter = rf + SPEC["entry_buffer"]
    if prev == 0:
        return side if on_cap > enter else 0
    if side == prev:
        return prev if on_cap >= rf else 0
    return side if on_cap > enter else 0


def positions(t: pd.Timestamp, prev: dict) -> dict:
    listed = set(dydx("/perpetualMarkets")["markets"].keys())
    rf = tbill(t)
    uni = universe(t, listed)
    start = t - pd.Timedelta(days=SPEC["signal_days"])
    expo, signal, hours = {}, {}, {}
    for c in uni:
        h = hl_funding(c, start, t)
        d = dydx_funding(dydx_ticker(c, listed), start, t)
        hours[c] = [len(h), len(d)]
        ok = min(len(h), len(d)) >= SPEC["min_hours_each_venue"]
        s = (h["rate"].sum() - d["rate"].sum()) * 365 / SPEC["signal_days"] if ok else None
        signal[c] = s
        expo[c] = decide(s, int(prev.get(c, 0)), rf)
    # Coins that left the universe are closed; their exit is a trade.
    trades = {c: abs(expo.get(c, 0) - int(prev.get(c, 0)))
              for c in set(expo) | set(prev)}
    return {"universe": uni, "expo": expo, "signal": signal, "hours": hours,
            "trades": {c: v for c, v in trades.items() if v}, "tbill": rf}


def score(p: dict, t0: pd.Timestamp, t1: pd.Timestamp) -> dict:
    """What the positions written at t0 earned over [t0, t1)."""
    listed = set(dydx("/perpetualMarkets")["markets"].keys())
    lev, cap = SPEC["leverage"], 2 / SPEC["leverage"]
    leg_trade = 2 * SPEC["cost_per_leg"]                 # one unit across both legs
    liq_level = 1 / lev - SPEC["maintenance"]
    days = (t1 - t0).days
    per = {}
    for c in p["universe"]:
        e = int(p["expo"].get(c, 0))
        cost = p["trades"].get(c, 0) * leg_trade
        if e == 0:
            per[c] = {"expo": 0, "excess": -cost / cap}
            continue
        h = hl_funding(c, t0 - pd.Timedelta(hours=2), t1)
        tk = dydx_ticker(c, listed)
        d = dydx_funding(tk, t0, t1) if tk else pd.DataFrame(columns=["ts", "rate"])
        hw = h[h.ts >= t0]
        prem0 = h.loc[h.ts < t0, "premium"]
        prem1 = hw["premium"]
        dprem = (prem1.iloc[-1] - prem0.iloc[-1]) if len(prem0) and len(prem1) else 0.0
        k = hl_candles(c, t0 - pd.Timedelta(days=1), t1)
        k["prev"] = k["close"].shift(1)
        k = k[k.day >= t0]
        rally = (k["high"] / k["prev"] - 1).fillna(0)
        drop = (1 - k["low"] / k["prev"]).fillna(0)
        liqs = int(((rally >= liq_level) | (drop >= liq_level)).sum())
        moved = float((k["close"] / k["prev"] - 1).abs().sum())
        spread = float(hw["rate"].sum() - d["rate"].sum())
        pnl = (e * spread - e * dprem
               - liqs * (SPEC["liquidation_penalty"] + 2 * leg_trade)
               - SPEC["collateral_move_cost"] * moved)
        ex = pnl / cap - p["tbill"] * days / 365 - cost / cap
        per[c] = {"expo": e, "hl": float(hw["rate"].sum()), "dydx": float(d["rate"].sum()),
                  "dprem": float(dprem), "liquidations": liqs, "excess": float(ex),
                  "hl_hours": len(hw), "dydx_hours": len(d)}
    # Exits of coins no longer in the universe are charged to the book.
    exit_cost = sum(v for c, v in p["trades"].items() if c not in p["universe"]) * leg_trade
    n = max(1, len(p["universe"]))
    book = (sum(v["excess"] for v in per.values()) - exit_cost / cap) / n
    return {"days": days, "book_excess": float(book), "per_coin": per}


# ------------------------------------------------------------------ freeze & ledger

def code_hash() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def check_frozen() -> dict:
    if not MANIFEST.exists():
        sys.exit("no manifest: run `forward_xv.py freeze` once first")
    m = json.loads(MANIFEST.read_text())
    if m["spec"] != SPEC:
        sys.exit("SPEC differs from the frozen manifest. A changed rule is a new "
                 "version and a new trial, not an edit.")
    if m["code_sha256"] != code_hash():
        sys.exit("forward_xv.py has changed since it was frozen. Restore it, or freeze "
                 "a new version as a new trial.")
    return m


def week_start(now: pd.Timestamp) -> pd.Timestamp:
    d = now.floor("D")
    return d - pd.Timedelta(days=d.dayofweek)


def entries() -> list[dict]:
    return ledger.read_all(LEDGER) if LEDGER.exists() else []


def cmd_freeze(_a) -> int:
    if MANIFEST.exists():
        print("already frozen; a new rule needs a new version", file=sys.stderr)
        return 1
    MANIFEST.parent.mkdir(exist_ok=True)
    m = {"spec": SPEC, "code_sha256": code_hash(),
         "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    MANIFEST.write_text(json.dumps(m, indent=2) + "\n")
    print(f"frozen {SPEC['name']}: code sha256 {m['code_sha256'][:16]}...")
    return 0


def cmd_run(a) -> int:
    m = check_frozen()
    if a.as_of and not a.dry_run:
        sys.exit("--as-of is only allowed with --dry-run: history cannot enter the live record")
    now = pd.Timestamp(a.as_of, tz="UTC") if a.as_of else pd.Timestamp.now(tz="UTC")
    t = week_start(now)
    # Positions for a week must be written as that week opens. Writing them on a
    # Saturday would date them to a Monday whose outcome is already half known.
    if not a.dry_run and now - t > pd.Timedelta(hours=WINDOW_HOURS):
        nxt = t + pd.Timedelta(days=7)
        print(f"outside the run window: live runs happen within {WINDOW_HOURS}h of Monday "
              f"00:00 UTC. next window opens {nxt.isoformat()}")
        return 0
    rows = entries()
    if rows and not a.dry_run:
        v = ledger.verify(LEDGER)
        if not v.ok:
            sys.exit(str(v))
    pos = [r for r in rows if r["kind"] == "xv_positions"]
    scored = {r["positions_hash"] for r in rows if r["kind"] == "xv_score"}
    if pos and pos[-1]["week_start"] == t.isoformat():
        print(f"positions for {t.date()} already written; nothing to do")
        return 0

    out = []
    prev = {}
    if pos:
        last = pos[-1]
        prev = last["expo"]
        if last["entry_hash"] not in scored:
            t0 = pd.Timestamp(last["week_start"])
            s = score(last, t0, t)
            out.append({"kind": "xv_score", "week_start": last["week_start"],
                        "week_end": t.isoformat(), "positions_hash": last["entry_hash"],
                        "manifest_sha256": m["code_sha256"], **s})
            print(f"scored {t0.date()} to {t.date()}: book excess {s['book_excess']:+.4%}")
    p = positions(t, prev)
    out.append({"kind": "xv_positions", "week_start": t.isoformat(),
                "manifest_sha256": m["code_sha256"], **p})
    held = {c: e for c, e in p["expo"].items() if e}
    print(f"positions for week of {t.date()}: {len(held)} of {len(p['universe'])} coins held, "
          f"T-bill {p['tbill']:.2%}")
    for c in p["universe"]:
        s = p["signal"][c]
        print(f"  {c:<10}{'n/a' if s is None else f'{s:+8.1%}':>9}  expo {p['expo'][c]:+d}")
    if a.dry_run:
        print("\n(dry run: nothing written)")
        return 0
    ledger.append(out, LEDGER)
    print(f"\nwrote {len(out)} entries; {ledger.verify(LEDGER)}")
    return 0


def cmd_status(_a) -> int:
    rows = entries()
    if rows:
        print(ledger.verify(LEDGER))
    sc = [r for r in rows if r["kind"] == "xv_score"]
    pos = [r for r in rows if r["kind"] == "xv_positions"]
    print(f"{SPEC['name']}: {len(pos)} position sets written, {len(sc)} weeks scored")
    if not sc:
        print("no scored weeks yet: the first score lands one run after the first positions")
        return 0
    x = np.array([r["book_excess"] for r in sc])
    cum = x.sum()
    print(f"cumulative excess {cum:+.2%}, mean {x.mean() * 52:+.2%} a year")
    if len(x) >= 4 and x.std(ddof=1) > 0:
        sr = x.mean() / x.std(ddof=1)
        g3 = pd.Series(x).skew() if len(x) > 2 else 0.0
        g4 = pd.Series(x).kurt() + 3 if len(x) > 3 else 3.0
        z = sr * math.sqrt(len(x) - 1) / math.sqrt(max(1e-9, 1 - g3 * sr + (g4 - 1) / 4 * sr ** 2))
        print(f"annualized Sharpe {sr * math.sqrt(52):.2f}, PSR(SR>0) "
              f"{0.5 * (1 + math.erf(z / math.sqrt(2))):.2f}  ({len(x)} weeks)")
    if cum < SPEC["kill_level"]:
        print("KILL LEVEL BREACHED: stop and record the result in the registry")
    elif len(x) >= SPEC["pass_weeks"]:
        print(f"{SPEC['pass_weeks']} weeks reached: evaluate against the pass rule now")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("freeze")
    r = sub.add_parser("run")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--as-of", help="YYYY-MM-DD; dry runs only")
    sub.add_parser("status")
    a = ap.parse_args()
    return {"freeze": cmd_freeze, "run": cmd_run, "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
