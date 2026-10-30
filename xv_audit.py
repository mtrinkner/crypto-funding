#!/usr/bin/env python3
"""xv_v1 rescored without legs on dYdX markets that had stopped trading.

    python3 xv_audit.py

Read-only. forward_xv.py is hash-frozen and builds its dYdX universe from
/perpetualMarkets without checking `status`, so it can hold markets that are in
FINAL_SETTLEMENT. A settled market can't be traded, and its legs book a spread
nobody could collect. Per the strategy 26 annotation in the registry, the
52-week verdict is reported twice: as frozen (forward_xv.py status) and with
those legs removed (this script).

dYdX's API only reports a market's status NOW. For each market that is not
ACTIVE today, the time it stopped is when BOTH hold: its funding has been zero
ever since (the start of its final unbroken zero run), and it has stopped
trading (midnight after its last day with any trades). That is the same rule
as ingest_dydx.py's stop_time. Live dYdX markets print exactly zero about half
the time, so a zero run alone proves nothing; and VVV is settled but still
prints nonzero funding, so it is judged on trades alone.
A leg is excluded from a scored week if its market had stopped before that
week ended. That is conservative, so a market that settles mid-week loses the
whole week. An excluded leg is treated as not held: zero excess, no entry
cost, and the same denominator as the frozen score.

Limitation: a market ACTIVE today is assumed to have been active throughout.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

import pandas as pd

import ledger

ROOT = Path(__file__).resolve().parent
LEDGER = ROOT / "data" / "forward_xv.jsonl"
DYDX = "https://indexer.dydx.trade/v4"
COST_PER_LEG = 0.0003            # xv_v1's spec; used only to back out entry costs


def get(path: str):
    with urllib.request.urlopen(DYDX + path, timeout=60) as f:
        return json.loads(f.read().decode())


def ticker(coin: str) -> str:
    # Same mapping as forward_xv.py: kPEPE trades on dYdX as PEPE-USD. Funding is
    # a fraction of notional, so the per-1,000 contract size doesn't matter.
    return (coin[1:] if coin.startswith("k") and coin[1:].isupper() else coin) + "-USD"


def stopped_at(t: str) -> pd.Timestamp:
    f = get(f"/historicalFunding/{t}?limit=1000")["historicalFunding"]      # newest first
    zero_since = None
    for r in f:
        if float(r["rate"]) != 0:
            break
        zero_since = pd.Timestamp(r["effectiveAt"])
    k = get(f"/candles/perpetualMarkets/{t}?resolution=1DAY&limit=100")["candles"]
    traded = [pd.Timestamp(x["startedAt"]) for x in k if int(x["trades"]) > 0]
    after_trades = (max(traded) + pd.Timedelta(days=1)) if traded else pd.Timestamp.min.tz_localize("UTC")
    if zero_since is None:
        return after_trades
    return max(zero_since, after_trades)


def main() -> int:
    rows = ledger.read_all(LEDGER)
    print(ledger.verify(LEDGER))
    pos = {r["entry_hash"]: r for r in rows if r["kind"] == "xv_positions"}
    scores = [r for r in rows if r["kind"] == "xv_score"]
    coins = sorted({c for p in pos.values() for c in p["universe"]})
    markets = get("/perpetualMarkets")["markets"]
    status = {c: markets.get(ticker(c), {}).get("status", "NOT LISTED") for c in coins}
    stopped = {c: stopped_at(ticker(c)) for c, s in status.items() if s != "ACTIVE"}

    print("\nmarkets in the xv_v1 universe that are not ACTIVE today")
    for c, t in stopped.items():
        held = [p["week_start"][:10] for p in pos.values() if p["expo"].get(c, 0)]
        print(f"  {c:<7}{ticker(c):<11}{status[c]:<18} stopped {t:%Y-%m-%d %H:%M}   held weeks {held}")

    print(f"\n{'week':<24}{'as frozen':>11}{'ex-settled':>12}  excluded legs")
    frozen, clean = [], []
    for s in scores:
        p = pos[s["positions_hash"]]
        end = pd.Timestamp(s["week_end"])
        n = max(1, len(p["universe"]))
        out = []
        adj = s["book_excess"] * n
        for c, v in s["per_coin"].items():
            if c in stopped and stopped[c] < end and v["expo"] != 0:
                out.append(c)
                adj -= v["excess"]       # the leg as scored, entry cost included
        adj /= n
        frozen.append(s["book_excess"])
        clean.append(adj)
        print(f"{s['week_start'][:10]} -> {s['week_end'][:10]}{s['book_excess']:>11.3%}{adj:>12.3%}  "
              f"{', '.join(out) or '-'}")
    print(f"{'cumulative':<24}{sum(frozen):>11.3%}{sum(clean):>12.3%}")

    open_ = [p for p in pos.values() if p["entry_hash"] not in {s["positions_hash"] for s in scores}]
    for p in open_:
        bad = [c for c, e in p["expo"].items() if e and c in stopped]
        print(f"\nunscored positions for {p['week_start'][:10]} hold settled markets: {', '.join(bad) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
