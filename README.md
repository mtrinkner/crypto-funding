# Crypto Funding Audit

Perpetual-swap funding strategies, tested the way
[edge-audit](https://github.com/mtrinkner/edge-audit) tests equity strategies.
Every idea is declared in a hash-chained registry before it runs, every variant
counts as a trial, and the luck bar rises with each one. Results are reported
whichever way they go.

Split off from edge-audit on 2026-10-09. The registry here starts by inheriting
edge-audit's 304 trials (see `registry.py` and the first entry of
`data/strategy_registry.jsonl`), because moving the research to a new repo
doesn't reset how many times the same person has searched. Edge-audit kept
searching after the split, so on 2026-10-29 a top-up entry brought the inherited
count to 852 and the total to 865, and another top-up goes in before each new
crypto result. At 865 trials the luck bar for a 42-month monthly series is 1.72.

**What funding is.** A perpetual swap never expires, so the exchange ties it to
spot with a periodic funding payment: when the perp trades above spot, longs pay
shorts. Short perp against long spot is delta-neutral and collects that payment
as a contractual cash flow rather than a forecast.

**Where it stands.** Nothing here clears a defensible out-of-sample Sharpe of
1.5, and on BitMEX from 2017 to 2023 the carry loses money in both bear years
it had never seen. The single-venue carry generalizes to 94 held-out coins (1.70 before
liquidations) but fails once its short perp gets liquidated (-0.24), and its
excess decayed from 12% to 2% a year. The cross-venue version (strategy 25)
finds a real, persistent dispersion between Hyperliquid and dYdX, with a gross
Sharpe of 3.72 (5.35 in 2025-26 alone). Execution costs as declared eat all
but 0.6% of it (net Sharpe 0.24, once coin-days on dYdX markets that had
already settled are dropped). Measured order books and dYdX's own volume history
show why: the dispersion lives in markets almost nobody trades, and where size
is possible it is about the T-bill rate.

## The bear markets it never saw: BitMEX, 2017 to 2023

Everything above comes from Hyperliquid, which starts in May 2023, after the
2018 crash and after Luna, 3AC and FTX in 2022. BitMEX ran the first perps and
serves their funding publicly back to 2016. The rules already declared, with
unchanged parameters and the same engine, costs and liquidation model, were run
on BTC and ETH from March 2017 to April 2023, strictly before the Hyperliquid
sample. The window and specs were fixed in the registry before any BitMEX data
was pulled.

**As precommitted, it looked like a breakthrough:** Sharpe 1.59 to 2.15, and
positive in both bear years. **That was my mistake in the precommitment.**
BitMEX's ETHUSD is a *quanto* contract, settled in BTC, and I modeled it as a
plain dollar position. A short quanto hedged with spot ETH carries a cross-term
of minus (ETH return × BTC return) every day, and ETH and BTC move together
(correlation 0.83):

| ETH, 2018-2023 | Per year |
|---|---|
| Funding received | 57.3% |
| Quanto cross-term | -57.8% |
| **Net** | **-0.5%** |

The famous ETHUSD funding was the price of the quanto risk, almost to the
decimal. With that cost charged:

| Spec, 2017-03 to 2023-04 | Excess over T-bills | Sharpe | 2018 | 2022 |
|---|---|---|---|---|
| 20 always on, 3x | -1.8% | -0.15 | -10.1% | -8.4% |
| 21 switched, 3x | -0.2% | -0.02 | -5.7% | -6.2% |
| 24 equal, 2x | 0.3% | 0.03 | -5.2% | -5.7% |
| 24 inverse-vol, 2x | 0.6% | 0.08 | -5.0% | -5.1% |
| *BTC alone, switched / 2x* | *2.7% / 2.9%* | *0.37 / 0.51* | | |

**The carry loses money in every bear year it hadn't seen.** The switch halves
the damage relative to always-on, but it doesn't avoid it. BTC alone, a clean
inverse contract, gives 0.37 to 0.51, the same picture as Hyperliquid. Both
versions are printed by `out_of_time.py`, the precommitted one first, so the
error stays on the record.

## A daily strategy: momentum on Hyperliquid (strategy 27)

The signal here actually changes day to day, which the funding carry's doesn't.
Crypto shows momentum at 1-4 week horizons (Liu, Tsyvinski and Wu, JF 2022)
and reversal at very short ones. The test ran on the point-in-time top 20
Hyperliquid perps, rebalanced at each daily close. Costs are 8bp per side
(measured at about 7bp to take $10k), and funding is paid or received on every
position. Six variants were declared, with the primary named before running:

| Variant | Gross | Funding | Costs | Net | Sharpe |
|---|---|---|---|---|---|
| **Cross-sectional, 21 days (primary)** | 58.7% | -9.9% | -18.4% | **30.4%** | **0.52** |
| Cross-sectional, 7 days | 35.7% | -6.6% | -31.1% | -2.0% | -0.03 |
| Cross-sectional, 1-day reversal | -8.4% | +5.2% | -77.6% | -80.8% | -1.41 |
| Time-series, 21 / 7 / 1 days | | | | 6.2% / 1.6% / -27.8% | 0.15 / 0.03 / -0.54 |

**Three-week momentum is real and unusable.** It earns 30% a year after costs,
is positive in both halves of the sample, and is uncorrelated with BTC. But it
went +87%, -48%, +123% and -30% in successive years, with an 85% maximum
drawdown, for a Sharpe of 0.52 against a luck bar of 1.74 at today's 865 trials (1.58 at
317; first printed as 3.23 in weekly units). Shorter horizons are
eaten by turnover. Funding works against momentum, because it's long the coins
that cost the most to hold. On BitMEX from 2017 to 2023, the time-series
versions on BTC and ETH give 0.45 to 0.49. It fails two of the three declared
criteria.

### Volatility scaling makes it worse (strategy 28)

The standard fix for momentum crashes is to scale the book by the inverse of its
own trailing volatility (Barroso and Santa-Clara 2015; Moreira and Muir 2017).
It was declared before running, though tried because strategy 27 was this
volatile, so it's post-hoc.

| | Net | Sharpe | Max drawdown |
|---|---|---|---|
| Unscaled (27) | 30.4% | 0.52 | 85% |
| **Scaled, 30-day volatility (primary)** | 11.1% | **0.35** | 57% |
| Scaled, 90-day volatility | 13.8% | 0.49 | 51% |

**Retracted: "momentum only pays when it's volatile."** An earlier version of
this section explained the result with a table saying crypto momentum earns
everything in its most volatile third of days (Sharpe 1.41) and nothing in the
rest. That table has look-ahead in it. The terciles were cut with `pd.qcut`
over the full sample, so each day was sorted using volatility levels that
hadn't happened yet. The script behind it was never committed. It is now
committed as [`vol_terciles.py`](vol_terciles.py), and it prints both versions
(audit 2026-10-29, finding A3):

| Momentum's own trailing volatility | Full-sample cutoffs (look-ahead) | Point in time |
|---|---|---|
| Calm third | -0.09 | -0.09 |
| Middle third | -0.09 | **0.53** |
| Volatile third | **1.39** | 0.43 |

Point in time ranks each day only against the volatility seen so far, with at
least 180 days of history. The published 1.41 reproduces as 1.39 in the pinned
environment. Once the cutoffs stop looking ahead, the volatile third is no
better than the middle one, so there is no regime effect to explain. The 10
best days also carry 141% of the book's total P&L, so any split of this book is
mostly a statement about where those 10 days fell. The "trade momentum only when
volatile, and test it forward" idea that this table motivated is withdrawn.
Volatility scaling simply didn't help.

## Forward test: xv_v1 (strategy 26), running

Strategy 25's dispersion is real before costs, and its costs are the open
question. A backtest can't answer that honestly any more, because any cheaper
variant would be designed after seeing the results. So a cheaper-execution
version is frozen and scored only on weeks that hadn't happened when it was
written down.

- **Spec**, frozen in [`models/xv_v1.json`](models/xv_v1.json) with a SHA-256
  of [`forward_xv.py`](forward_xv.py):
  - Hyperliquid vs dYdX on the weekly top 20 by volume, 2x leverage.
  - Trailing 30-day spread.
  - Enter when the spread on capital beats T-bills by 2 points, exit below
    T-bills.
  - Costs: 3bp per leg for resting orders, 1bp to move collateral, and a 5%
    penalty per liquidation.
- **Mechanics.** Every Monday at 00:20 UTC a [GitHub Action](.github/workflows/forward-xv.yml)
  scores last week's positions against what happened, then writes next week's
  to the hash-chained [`data/forward_xv.jsonl`](data/forward_xv.jsonl) before
  their outcome exists. The runner refuses to start if its code or spec has
  changed, refuses live writes outside 12 hours of Monday 00:00 UTC, and
  refuses `--as-of` outside dry runs, so history can't be backfilled.
- **Pass, at 52 live weeks:** annualized Sharpe of 1.5 or more and PSR(SR > 0)
  of 0.95 or more. The 26-week look is report-only. **Kill:** stop if
  cumulative excess falls below -5% of capital.
- Its backtest is in-sample by construction and isn't reported as evidence.

### What its trades would actually cost

The forward test never trades, so it can't check its own 3bp per leg. Three
times a day, a [second Action](.github/workflows/exec-costs.yml) reads both
order books for every coin xv_v1 holds. It records the half-spread, what it
would cost to fill $10k and $100k on the side the position needs (fees
included), and each market's 24-hour volume and open interest, all to the
hash-chained [`data/exec_costs.jsonl`](data/exec_costs.jsonl). It leaves the
frozen test untouched.

**The first snapshot (2026-10-12) says the 3bp assumption doesn't hold, and the
reason is dYdX.**

| Median across the 16 held coins | Hyperliquid | dYdX |
|---|---|---|
| Half-spread | 0.7bp | 35bp |
| Taking $10k, with fees | 7bp | 42bp |
| Taking $100k, with fees | 12bp | 214bp |
| 24h volume | $15m to $2.4bn | under $0.05m on 14 of 16 |

dYdX traded $3m of BTC in a day, against $2.4bn on Hyperliquid. XPL and LIT
had zero trades, and dYdX open interest is under $0.3m on every held coin but
BTC and SOL. So much of the funding spread comes from dYdX markets that almost
nobody trades. The funding prints are real, but nobody can hold size against
them. **The frozen spec has no capacity filter, so it can pass on positions
that couldn't be put on.** That was written into the registry before the first
scored week, so any verdict gets read with these numbers.

```bash
python3 exec_costs.py summary
```

### The dispersion lives where you can't trade

Was the gross edge ever collectible? `capacity.py` buckets each coin-day
strategy 25 held by dYdX's trailing 30-day volume for that coin, as known at
the time. It's descriptive: no threshold is chosen, and no trials are added.

| dYdX daily volume | Share of held days | Share of gross spread | Gross spread a year |
|---|---|---|---|
| under $0.1m | 29% | 32% | 13.2% |
| $0.1m to $1m | 29% | 26% | 10.4% |
| $1m to $10m | 27% | 35% | 15.5% |
| **over $10m** | 15% | 7% | **5.7%** |

In the only markets that could take size, the spread was 5.7% a year before
costs, about what T-bills paid. And dYdX has drained: the median universe coin
traded $5.3m a day there in early 2024 and $0.03m now. The share of the gross
coming from coins trading over $1m a day fell from 59% in 2024 to 31% in 2025
and 17% in 2026.

That is the signature of a limits-to-arbitrage premium. The gap persists
because the markets are too thin to arbitrage, so it was never a free
dispersion. xv_v1 keeps running unchanged, as a record of a spread that can't
be collected at size.

```bash
python3 forward_xv.py status
```

## Strategy 25: cross-venue dispersion, Hyperliquid vs dYdX v4

No spot leg. For each coin, short the perp on whichever venue has paid more
funding over the trailing 30 days and long it on the other, when that spread
on capital beats T-bills. Both legs post margin and both can be liquidated, the
short on a rally and the long on a crash. The rule, costs, liquidation model,
January 2024 start, four variants and pass criteria were declared before any
dYdX data was pulled. dYdX v4's indexer is public: 1.97M hourly prints, 95
coins, 81 of them on both venues while in the universe.

**dYdX has no interest floor.** 52% of its hourly prints are exactly zero, while
Hyperliquid's most common print is its 11% constant. So the raw spread is
mostly Hyperliquid's constant, and it is decaying:

| Year | Spread, short HL / long dYdX | HL interest leg | Spread excluding it |
|---|---|---|---|
| 2024 | 9.3% | 11.0% | -1.7% |
| 2025 | 0.2% | 11.0% | -10.8% |
| 2026 | 0.2% | 10.9% | -10.7% |

| Variant | Excess over T-bills | Sharpe | 2024 | 2025-26 | Liquidations / coin-yr |
|---|---|---|---|---|---|
| **2x, 30-day (primary)** | **0.6%** | **0.24** | 2.78 | -0.65 | 0.47 |
| 2x, 7-day | 0.2% | 0.08 | 1.51 | -0.45 | 0.55 |
| 3x, 30-day | -9.9% | -1.77 | | | 2.20 |
| 3x, 7-day | -11.9% | -1.90 | | | 2.49 |

All three declared criteria fail: Sharpe 0.24 against 1.5, PSR(SR > 0) 0.64
against 0.95, and -0.65 in 2025-26. The bootstrap 90% interval is -0.67 to 2.12.

**Correction (audit 2026-10-29).** After a dYdX market's final settlement, the
indexer keeps printing a rate of 0, so the spread becomes pure Hyperliquid
funding on a market nobody can trade. 38 of 95 dYdX markets stopped inside the
data, for example FET in June 2024, MATIC in September 2024 and FTM in January
2025. `ingest_dydx.py --status` now infers each stop, as the point where funding
stayed at zero and trading stopped, and `cross_venue.py` drops every coin-day
from then on. That's 59 held coin-days, which took the primary from 1.1% and
0.39 to 0.6% and 0.24.

**But the dispersion is real; it's the costs that kill it.** The rule picks the
direction (74% of the time short Hyperliquid), and what it captures holds up:

| Primary, 2x 30-day | Excess | Sharpe |
|---|---|---|
| As declared | 0.6% | 0.24 |
| Without switching and entry costs (8bp per leg) | 2.6% | 1.07 |
| Without the daily collateral top-up | 2.4% | 0.93 |
| Without the liquidation penalty | 2.5% | 1.47 |
| **Nothing charged** | **6.1%** | **3.72** (5.35 in 2025-26) |

The 5.5 points of drag split about evenly three ways. Each cost was set
conservatively. The 8bp is a taker fill, where resting orders cost less. The
top-up is charged as a trade, where in practice it's a stablecoin transfer
between venues. And the penalty assumes every liquidation loses 5%. But any
cheaper-execution variant designed now has seen this data, so it would be
in-sample. **The only clean test of the execution question is a forward one.**


## Headline: a universe without survivors

All three tests first ran on today's 16 Hyperliquid volume leaders, which is a
universe of survivors. The headline numbers below come from a point-in-time
universe instead: each week, the top 20 listed perps by trailing 30-day
Hyperliquid volume, using only data from before that week, delisted coins
included. That's 109 coins over 178 weeks, 14 of them since delisted (FTT,
MATIC, OM, TON, ...), and 2.4M hourly funding prints. Basis comes from
Hyperliquid's own premium field, because delisted coins have no OKX spot. The
universe rule was fixed in the registry before anything was pulled.

| | 16 survivors | **Point-in-time** |
|---|---|---|
| 20: always-on carry, excess over T-bills | 1.1%, Sharpe 0.26 | **-5.6%, Sharpe -1.08** |
| 21: switched on trailing funding | 4.0%, Sharpe 1.26 | **2.2%, Sharpe 0.72** |
| 22: funding as a crowding signal, IC (t) | +0.06 (2.15) | **+0.0001 (0.00)** |
| *20, before liquidations (as first published)* | *4.0%, 0.87* | *3.0%, 0.51* |
| *21, before liquidations (as first published)* | *5.9%, 1.71* | *7.6%, 1.92* |

Excess is per dollar of capital, after costs. Sharpes are monthly. The luck bar
is 1.72 (865 trials, 42 months; 1.56 at 317 before the 2026-10-29 top-up; first
printed as 3.17 in weekly units).

**Correction (audit 2026-10-29).** These carry books first ran without ever
liquidating the 3x short perp, while `validate.py` charged liquidations only on
the holdout. They now use `validate.py`'s model: liquidated when the day's high
clears the prior close by 30%, at a cost of 5% of notional plus re-entry. That's
147 liquidations on 24,839 held coin-days for strategy 20 and 92 on 15,983 for
strategy 21. The uncharged figures, kept above in italics, are what the rest of
this section originally described.

| Year | 20 always on | 21 switched | 20, liquidations charged | 21, liquidations charged |
|---|---|---|---|---|
| 2023 | -8.5% | +8.4% | -14.8% | +5.2% |
| 2024 | +15.8% | +15.5% | +8.0% | +8.7% |
| 2025 | +1.4% | +3.4% | -11.6% | -3.7% |
| 2026 | -2.0% | +1.9% | -8.0% | -1.2% |

- **Survivorship was flattering the carry.** On the wider universe, always-on
  pays 3.0% over T-bills, and 2026 is negative.
- **Survivorship had manufactured the crowding result.** Strategy 22's IC was
  zero once the coins that later disappeared were back in. Funding says nothing
  about next week's return in either direction.
- **The switched carry got stronger, and the gain is broad.** 62 of 109 coins
  contribute, the top five are 36% of it, and delisted coins add 0.4 points.
  Without the top five it's still 7.5% with a Sharpe of 1.94. A wider universe
  has more coins whose funding goes negative, and the rule's job is to stop
  paying on them. But all of this is before liquidations. Uncharged, its 1.92
  would clear the correctly computed bar of 1.72 (deflated p 0.64 at 865 trials,
  0.74 at 317; first printed as 0.135 in the wrong units). With liquidations
  charged it is 0.72 (deflated p 0.03), and it fails. Its Sharpe is also low-variance for the same reason
  strategy 20's daily Sharpe was 7: the volatility is the wobble in a cash flow,
  and the risk is a tail (squeeze, venue failure) that no series contains.

The precommitment said the point-in-time numbers replace the survivor numbers
whichever way they went. One went up, so it's reported going up. The sections
below are the original 16-coin results, kept as the record.

## Out-of-sample validation: it doesn't hold up

The 1.92 above was then put through a validation protocol fixed in the registry
before anything ran (`validate.py`). The pass bar for the goal of a defensible
out-of-sample Sharpe of at least 1.5 required all three of: a holdout Sharpe
after liquidations of 1.5 or more, a probabilistic Sharpe above zero of 0.95,
and a walk-forward Sharpe of 1.5 or more.

**The holdout.** The rule was conceived on 16 survivor coins. The other 94 coins
in the point-in-time universe played no part in forming it, so they are a true
out-of-sample cross-section.

| Strategy 21 (30d, weekly, 3x) | Sharpe |
|---|---|
| All coins, as previously reported | 1.92 |
| ...charging the daily margin top-up, a real cost the first model skipped | 1.66 |
| Seen coins only | 1.64 |
| **Holdout coins, before liquidations** | **1.70** |
| Holdout, liquidation penalty 2% | 1.02 |
| **Holdout, liquidation penalty 5% (precommitted headline)** | **-0.24** |
| Holdout, liquidation penalty 10% | -1.81 |

**The signal generalizes.** Coins that never shaped the idea give 1.70, the same
as the coins that did. Walk-forward lookback selection (each quarter, pick from
7, 14, 30 or 60 days on the trailing year) gives 1.73 against 1.82 for the fixed
30 days. So the parameters aren't overfit, and tuning them adds nothing.

**The trade's Sharpe is set by margin management, not by the signal.** A short
perp at 3x, managed at the daily close, gets liquidated whenever the day's high
clears the prior close by 30%. On the holdout that happened 3.1 times per
coin-year (0.6 at 2x, 14 at 5x). Depending on the cost per liquidation, the
Sharpe runs from 1.02 to -1.81, and that cost can't be measured from this data.
Under the base case the bootstrap 90% interval is -1.39 to 0.84. Adding venue
failure (losing the perp margin, 1% to 5% a year) moves the median only from
-0.26 to -0.39, but the chance of a 20% drawdown goes from 1% to 17%.

**And it is decaying.** Before liquidations, the holdout earned 12.1% excess in
2023-24 and 1.9% in 2025-26.

| Criterion | Result |
|---|---|
| Holdout Sharpe after liquidations >= 1.5 | **fail** (-0.24) |
| PSR(SR > 0) >= 0.95 | **fail** (0.33) |
| Walk-forward >= 1.5 | pass (1.73), but computed without liquidations |

## Strategy 24: engineering the risk

Declared before running, designed only on the seen coins, judged only on the
holdout with 5% liquidations. Eight variants: equal or inverse-volatility
sizing, 2x or 3x leverage, and a stablecoin-supply regime gate (on-chain,
DefiLlama: carry off when 30-day supply growth is negative).

| Variant (holdout, 5% liquidations) | Excess | Sharpe | PSR > 1.5 |
|---|---|---|---|
| Equal, 2x, no gate | 4.6% | **1.42** | 0.39 |
| **Inverse-vol, 2x, no gate (primary)** | 3.8% | **1.24** | 0.19 |
| Equal, 3x, no gate | -0.8% | -0.24 | 0.00 |
| Gated variants | | 0.1 to 0.2 lower than ungated, every time | |

- **Leverage is the only lever that works.** Going from 3x to 2x cuts
  liquidations fivefold and takes equal weight from -0.24 to 1.42.
- **Inverse-vol sizing hurt.** Low-volatility coins carry less funding, so
  de-risking them cut the return more than the risk.
- **The stablecoin gate hurt every variant.** Funding itself is a better
  real-time measure of leverage demand than the collateral behind it.
- **The primary decays to zero:** 7.8% excess and Sharpe 1.93 in 2023-24,
  0.1% and Sharpe 0.13 in 2025-26.

Deflated p for the primary is 0.66 against the 19 crypto trials (bar 1.00)
and 0.20 against all 865 (bar 1.72; 0.29 and 1.55 against the 304 inherited at the split). Both were first printed in weekly units,
as 0.23 and 0.04. Against the crypto trials alone, the primary's 1.24 does beat
the expected best result from luck. Once liquidations are charged, it's the
only crypto result that does. But a deflated p of 0.66 is a long way from
significant. **Nothing here clears a defensible out-of-sample 1.5.**

## What would actually move it

- **Margin architecture is the strategy.** A portfolio-margin account where the
  spot leg collateralizes the short perp removes the liquidation tail. Before
  liquidations the holdout is 1.70, and 1.60 even in 2025-26, but on 1.9%
  excess that is a high Sharpe on a tiny return. That is a venue and execution
  question this data can't answer.
- **Cross-venue dispersion** is how a desk would run this. Short the perp where
  funding is rich and long it where it is cheap, with no spot leg and no
  exposure to the exchange's interest constant. dYdX v4 serves public hourly
  funding back to late 2023 across 296 markets, so it can be tested against
  Hyperliquid.
- **Forward data** is the only cure for the decay question, and it accrues one
  week at a time.
- **Not available free:** historical order flow and open interest. Hyperliquid
  serves only recent trades, and Coinglass and Coinalyze need paid keys.

## Result (16 survivors)

| | |
|---|---|
| Median coin, annualized funding | 10.0% |
| ...of which Hyperliquid's fixed interest constant | **11.0%** |
| ...of which the market premium | **-0.9%** |
| Equal-weight book, after basis and costs | 11.2% |
| Per dollar of capital (spot leg + 3x perp margin) | 8.4% |
| **In excess of T-bills** | **4.0%** |
| Monthly Sharpe of the excess | 0.87 against a luck bar of 1.50, deflated p 0.13 |
| **With liquidations charged (audit 2026-10-29)** | **1.1% excess, Sharpe 0.26, deflated p 0.008** |

The bar and deflated p were first printed in weekly units, as 3.07 and 0.024.
The liquidation line uses `validate.py`'s model, with the high taken from
Hyperliquid's daily candle, because OKX bars have closes only: 27 liquidations
on these 16 coins.

| Year | Funding | Excess over T-bills, per dollar of capital |
|---|---|---|
| 2023 | 6.2% | -1.0% |
| 2024 | **23.2%** | **+12.3%** |
| 2025 | 7.4% | +1.4% |
| 2026 | 6.0% | +0.5% |

**The median coin's carry is a number the exchange typed in.** Hyperliquid
funding is `premium + clamp(interest - premium, ±0.05%)` per 8 hours, with
interest fixed at 0.01% per 8h, which comes to about 11% a year. When the perp
trades near the index, funding equals that constant exactly, and 54% of all
353,123 hourly prints sit on it. For the median coin the market's own
contribution is slightly negative. Shorts do get the cash, but the venue sets
the rate and can change it. It tells you nothing about demand for leverage.

**All of the excess return is 2024.** That was a year of real levered-long
demand, with a market leg of +12.2%. The other three years pay roughly what
T-bills pay, with venue risk on top.

## Switching it on and off (strategy 21, 16 survivors)

If all the excess is 2024, could a rule that only looks backward have known it
was in 2024? Funding is persistent, so I declared one before running it. For
each coin, hold the carry only while its trailing funding, scaled to capital,
beats the T-bill yield. Otherwise hold T-bills. Every switch pays the cost of
trading out of or into both legs. There were four variants, and the primary was
named in advance.

| | Excess over T-bills | Monthly Sharpe | Worst month | Time on |
|---|---|---|---|---|
| Always on (strategy 20) | 4.0% | 0.87 | -2.4% | 100% |
| **30-day lookback, weekly (primary)** | **5.9%** | **1.71** | -0.2% | 64% |
| 30-day, monthly | 5.4% | 1.60 | -0.3% | 63% |
| 7-day, weekly | 5.7% | 1.54 | -0.3% | 66% |
| 7-day, monthly | 5.5% | 1.55 | -0.3% | 65% |

The luck bar at 228 trials is 1.50, and the primary's deflated p is 0.64 (first
printed in weekly units as 3.08 and 0.11). Those figures are before
liquidations. Charged, the primary is 4.0% and Sharpe 1.26, deflated p 0.21 at
today's 865 trials (0.30 at 317), and the other variants are 1.05 to 1.15.

It isn't lookahead. Letting the rule peek one week ahead gives 6.5%. Delaying
it 7, 14 and 30 days gives 5.3%, 4.8% and 4.2%, a smooth decay toward
always-on, which is what a real but modest persistence effect looks like.

**But the prediction was wrong about where the gain comes from.**

| Year | Always on | Switched |
|---|---|---|
| 2023 | -1.0% | **+8.9%** |
| 2024 | 12.3% | 11.6% |
| 2025 | 1.4% | 1.9% |
| 2026 | 0.5% | 1.1% |

The prediction was that the rule would sit out 2025 and 2026. It can't. The 11%
interest constant, scaled to capital, is 8.25% on its own, which clears T-bills,
so the rule stays on while the negative market leg bleeds the position down to
about 1%. The whole improvement is in 2023, and most of that is two coins: SUI
and AVAX went through long stretches of negative funding that cost the
always-on book 8.0% and 4.2%, and the switch sat them out. That's a handful of
episodes in a book of 5 to 7 coins, not a regime signal.

The lesson to keep: the switch is sensible risk hygiene (don't pay funding you
expected to receive), but it doesn't turn the carry into an edge.

## Funding as a crowding signal (strategy 22, 16 survivors)

The crypto-research story is that high funding means a crowded, fragile long
side, so high-funding coins should underperform. That predicts price, which is
a different claim from collecting funding. A book that shorts high-funding perps
also collects their funding, so the P&L is split. The claim stands or falls on
the price part.

| Weekly book | Price | Funding | Costs | Net | IC (t) |
|---|---|---|---|---|---|
| **Cross-sectional, 7-day (primary)** | **-88.0%** | +15.9% | -6.8% | -78.9% | +0.06 (2.15) |
| Cross-sectional, 30-day | -77.0% | +15.9% | -2.9% | -64.0% | +0.07 (2.03) |
| Time-series, 7-day | -21.6% | +9.4% | -1.9% | -14.1% | +0.06 (2.22) |
| Time-series, 30-day | -27.0% | +8.2% | -1.0% | -19.8% | +0.07 (2.17) |

Annualized, per $1 long and $1 short. The hypothesis predicted a negative IC.

**The sign is wrong.** High funding was followed by *higher* returns, and all
four variants lose. I'm not flipping it into "buy high funding":

- **77% of the loss comes from 10 weeks**, mostly the December 2023 to January
  2024 alt rally, when crowded coins kept rising. The worst week cost 49% of the
  book. That's the squeeze risk of shorting the crowd, which is exactly the side
  this bet took.
- **It fades as the survivorship bias is removed.** The universe is today's
  volume leaders, and many of them pumped while crowded. Dropping coins listed
  after mid-2024 gives t = 1.99. The 6 oldest coins alone give IC +0.045,
  t = 1.18, not significant.

Reversing the trade now would be a hypothesis chosen after seeing the answer,
tested on a universe built from winners.

## What the funding series cannot show

Measured on OKX daily perp and spot closes for the same 16 coins:

- **Basis at the daily close is tight.** Worst coin-day basis loss is -0.63%,
  and the worst book day is -0.32%. Basis blowouts, if they happen, happen
  intraday, which daily data cannot see.
- **Squeezes are routine.** A 30% three-day rally, enough to wipe the margin of
  an unrebalanced 3x short perp, happened in 13 of 16 coins, about 3.3 times per
  coin-year. The trade survives only if someone is moving collateral across legs
  around the clock.
- **Venue failure** is the risk that has actually ended this trade, and no
  series prices it.

## How the first pass got it wrong

The first version, committed in 820721d, said median 10.5%, daily Sharpe 7.11,
monthly 1.56, and 1.7% in 2026. It had three defects:

1. **No analysis script.** The numbers could not be reproduced. `funding_carry.py`
   is that script.
2. **Truncated data.** `post()` returned `[]` after three failed requests, and the
   pagination loop read that as the end of history. Rate limiting cut 9 of 16
   coins off at exact multiples of 500 rows (AVAX after 44 days, ZEC after 21).
   That is the same failure as the FINRA offset cap that killed short_v2. The
   ingest now raises instead, and warns when a series ends early. The re-pull
   has 353,123 prints, up from 233,170. The published 2026 figure of 1.7% was an
   artifact of this. The real figure is 6.0%: the carry decayed back to the
   interest constant, not to zero.
3. **Period length.** Hyperliquid settled every 8 hours until 2023-06-08.
   `mean(rate) * 24 * 365` treats those 410 prints as hourly. Funding is now
   summed as cash and divided by elapsed time.

A precommitment was written to the registry before any of this was computed:
the reproducible numbers replace the published ones, whichever way they go.

## Running it

```bash
pip install -r requirements.txt
python3 registry.py status                  # every trial, and the bar it sets
python3 ingest_hl_funding.py --same-coins   # Hyperliquid hourly funding
python3 ingest_okx.py --basis               # OKX perp + spot closes, same coins
python3 ingest_tbill.py                     # 3-month T-bill (FRED DTB3)
python3 funding_carry.py                    # the analysis
python3 carry_switch.py                     # strategy 21, switched on trailing funding
python3 funding_crowding.py                 # strategy 22, funding as a crowding signal
python3 ingest_hl_universe.py               # point-in-time universe, ~1 hour, resumable
python3 pit_rerun.py                        # 20, 21, 22 on that universe
python3 ingest_stablecoins.py               # DefiLlama total stablecoin supply
python3 validate.py                         # holdout, liquidations, PSR, bootstrap, strategy 24
python3 ingest_dydx.py                      # dYdX v4 hourly funding, ~30 min, resumable
python3 cross_venue.py                      # strategy 25, Hyperliquid vs dYdX dispersion
python3 ingest_dydx.py --candles            # dYdX daily volume and open interest
python3 capacity.py                         # where strategy 25's gross came from, by liquidity
python3 daily_momentum.py                   # strategy 27, daily momentum and reversal
python3 vol_momentum.py                     # strategy 28, volatility-managed momentum
python3 vol_terciles.py                     # retracted regime table, full-sample vs point in time
python3 ingest_bitmex.py                    # BitMEX funding + perp/spot daily since 2016
python3 out_of_time.py                      # the carry rules on 2017-2023 bear markets
```

The data the numbers come from is committed in `data/`.

| File | What it is |
|---|---|
| `hl_funding.parquet` | Hyperliquid funding, 16 coins, 2023-05 to 2026-10 |
| `okx_basis.parquet` | OKX daily perp and spot closes for those coins |
| `tbill.parquet` | FRED DTB3, 2016 on |
| `hl_candles.parquet` | Hyperliquid daily perp candles, all 234 coins in meta, delisted included |
| `hl_universe.parquet` | weekly top 20 by trailing 30-day volume, point in time |
| `hl_funding_pit.parquet` | hourly funding for the 109 coins that ever made the top 20 |
| `stablecoins.parquet` | DefiLlama total stablecoin supply, daily since 2017 |
| `dydx_funding.parquet` | dYdX v4 hourly funding, 95 coins, 2023-10 to 2026-10 |
| `dydx_candles.parquet` | dYdX v4 daily volume, trades and open interest, 95 coins |
| `bitmex_funding.parquet` | BitMEX XBTUSD (2016 on) and ETHUSD (2018 on) funding |
| `bitmex_daily.parquet` | BitMEX perp and spot-index daily closes, 2017 on |
| `okx_funding/perp/spot.parquet` | the original OKX pull: 100 days of funding, top 40 by coin count (see below) |

## Limits

- **Survivorship**, for the 16-coin sections. The headline fixes it as far as
  Hyperliquid's API allows. Coins removed from its metadata entirely, if any,
  are still missing, and so is anything that never listed there.
- **Cross-venue.** Funding comes from Hyperliquid and basis from OKX. A real
  position would hold both legs on venues it can move collateral between.
- **Costs.** Costs are a flat 8bp per leg, charged on entry and exit. Rebalancing
  to avoid liquidation would cost more.
- **The original OKX universe was ranked by 24h volume in coins, not dollars**,
  so it is mostly sub-penny meme coins with no BTC or ETH. That ranking is fixed
  in `ingest_okx.py`, but the pinned files were not re-pulled because nothing
  here depends on them.
