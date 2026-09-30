# Analyst Layer — Design

Date: 2026-09-21
Status: Approved for implementation planning

## Purpose

The owner invests long-term in blue-chip dividend stocks, reinvests all
dividends, holds a concentrated set of positions, and adds new money over time rather than
trading. He wants every report to end with a committed, reasoned opinion
per holding, plus a ranking of where his next contribution should go.

This layer adds that: a deterministic scoring engine tuned to *his*
strategy, plus a structured judgment step where the agent commits to a
verdict, a confidence level, and a falsifiable "what would change my
mind".

**What this is not:** not autonomous trading, not a licensed financial
advisor, and not a replacement for the owner's decision. It is a disciplined
analysis tool whose value is consistency, shown work, and stated
uncertainty. Every decision remains the owner's.

## Non-goals

- No selling advice. The verdict ladder has no "sell" rung (see §3).
- No changes to the existing Rating / Overall Score / 4 dimension scores,
  and no changes to the technical indicators shipped on 2026-09-18.
- No new tickers, screening, or discovery of companies the owner doesn't own.
- No price targets or forecasts invented by the agent. Analyst targets are
  reported only as fetched data.

## 1. New fetched data

Extend `FUNDAMENTALS_FIELDS` in `tools/fetch_fundamentals.py` with fields
already present in the yfinance `info` payload but not stored today:

| Stored key | yfinance key | Used by |
|---|---|---|
| `payout_ratio` | `payoutRatio` | dividend safety |
| `dividend_rate` | `dividendRate` | dividend safety (FCF cover) |
| `five_year_avg_dividend_yield` | `fiveYearAvgDividendYield` | valuation |
| `free_cashflow` | `freeCashflow` | dividend safety |
| `shares_outstanding` | `sharesOutstanding` | dividend safety (FCF cover) |
| `revenue_growth` | `revenueGrowth` | quality |
| `earnings_growth` | `earningsGrowth` | quality |
| `operating_margins` | `operatingMargins` | quality |
| `current_ratio` | `currentRatio` | quality |
| `price_to_book` | `priceToBook` | valuation |
| `target_mean_price` | `targetMeanPrice` | valuation |
| `recommendation_key` | `recommendationKey` | context in the narrative only |
| `beta` | `beta` | context in the narrative only |

Missing keys stay absent from the snapshot (the existing `extract_fundamentals`
behaviour); every score below treats a missing input as "component not
available" rather than zero.

## 2. Scoring engine: `tools/analyst.py`

Pure functions, no I/O. Four sub-scores, each 0-100, each returning `None`
when none of its inputs are available. These are *separate from* the
existing four scores in `tools/scoring.py`; nothing there changes.

**2.1 Dividend safety** — `compute_dividend_safety_score(payout_ratio, dividend_rate, shares_outstanding, free_cashflow)`

Since the owner reinvests dividends, a cut damages the whole plan, so this is
the heaviest-weighted score.

- Payout component: `100` at payout ≤ 0.40, falling linearly to `0` at
  payout ≥ 1.00 (so 0.75 → ~42, a deliberate hard penalty per the owner's rule).
- FCF-cover component: `cover = free_cashflow / (dividend_rate * shares_outstanding)`;
  `0` at cover ≤ 0.8, rising linearly to `100` at cover ≥ 2.5.
- Score = mean of available components.

**2.2 Business quality** — `compute_quality_score(profit_margin, operating_margins, revenue_growth, earnings_growth, debt_to_equity, current_ratio)`

- Margin component: mean of `profit_margin * 500` and `operating_margins * 400`, each clamped 0-100.
- Growth component: `50 + revenue_growth * 500` clamped 0-100, averaged with
  `50 + earnings_growth * 100` clamped 0-100 (earnings growth is far noisier,
  so it moves the score less per unit).
- Balance-sheet component: `100 - debt_to_equity / 300 * 100` clamped 0-100,
  averaged with `current_ratio / 2 * 100` clamped 0-100.
- Score = mean of available components.

**2.3 Valuation** — `compute_value_score(pe_ratio, forward_pe, price_to_book, price_local, target_mean_price, dividend_yield, five_year_avg_dividend_yield)`

- Forward-P/E component: `50 + (pe - forward_pe) / pe * 100`, clamped.
- Price-to-book component: `100` at P/B ≤ 1, `0` at P/B ≥ 10, linear between.
- Target component: `50 + (target_mean_price / price_local - 1) * 100`, clamped.
- Yield-vs-history component: `50 + (dividend_yield / five_year_avg_dividend_yield - 1) * 100`,
  clamped. Included because it is the dividend investor's cheapness test,
  but as one component of four — the owner explicitly did not want it to be the
  primary driver.
- Score = mean of available components.

**2.4 Portfolio fit** — `compute_fit_score(position_weight_pct, sector_weight_pct)`

This scores *the owner's portfolio*, not the company. It is what makes the
ranking his rather than generic.

- Position component: `100` at ≤ 5%, falling to `0` at ≥ 15% (10% → 50).
- Sector component: `100` at ≤ 15%, falling to `0` at ≥ 30% (25% → 33).
- Score = mean of the two.

Weights come from `tools/allocation.py`, which already computes both.

## 3. Verdicts

Two separate verdicts per holding, deliberately not merged:

**Business view** — from `business_score = mean(dividend_safety, quality, valuation)`:
- ≥ 60 → **Bullish**
- 40-60 → **Neutral**
- < 40 → **Bearish**

**Add decision** — from `add_score`, a weighted mean:
`0.30 * dividend_safety + 0.30 * quality + 0.25 * valuation + 0.15 * fit`
(weights renormalized over whichever components exist):
- ≥ 65 → **Add**
- 45-65 → **Hold**
- < 45 → **Stop adding**

There is no "Sell" rung. "Stop adding" means "no new money here", never
"exit the position".

Keeping the two separate is what prevents the concentration rule from
silently corrupting the business assessment: a company can be Bullish and
"Stop adding" purely because the owner is already overweight it.

**Insufficient data:** if fewer than two of the three business sub-scores
are available, both verdicts become `"Insufficient data"` and the holding
is listed separately from the ranking rather than ranked with a guessed
score.

**ETFs take precedence over that rule.** A holding with `is_etf: true` in
`portfolio.yaml` legitimately has no dividend-safety or quality inputs, so
it is scored and ranked on valuation and fit alone (its `add_score`
renormalizes over those two), gets a normal verdict, and its report entry
states that the business sub-scores do not apply. Only a *non-ETF* holding
missing its data falls to "Insufficient data".

## 4. Ranking: where the next euro goes

`rank_next_euro(holdings, scores)` returns every holding sorted by
`add_score` descending, each with: rank, ticker, add_score, verdict, the
single strongest contributing sub-score, and the single weakest. Holdings
with "Insufficient data" are excluded from the ranking and reported under
it.

## 5. The agent's judgment layer

The scores are inputs to the agent's analysis, not a replacement for it.
Per holding, the agent reads the sub-scores, the fetched fundamentals, the
week's headlines, and the technical signals, then records via an extended
`tools/append_analysis.py`:

| Field | Constraint |
|---|---|
| `--verdict` | one of `Add`, `Hold`, `Stop adding`, `Insufficient data` |
| `--business-view` | one of `Bullish`, `Neutral`, `Bearish`, `Insufficient data` |
| `--confidence` | one of `high`, `medium`, `low` |
| `--case-for` | free text, must cite a fetched number or headline |
| `--case-against` | free text, must cite a fetched number or headline |
| `--what-would-change-my-mind` | free text, must be concrete and checkable |
| `--override-reason` | required *only* when `--verdict` differs from the computed verdict |

**The override guardrail is enforced in code:** `append_analysis` computes
the verdict itself and exits non-zero if the agent supplies a different
`--verdict` without `--override-reason`. This makes disagreement explicit
and auditable instead of silent, and every override is stored in the
holding's analysis YAML so past overrides can be reviewed against what
actually happened.

**Honesty rules** (enforced by the workflow, and by the citation
requirement above):
- Every number in the narrative must come from the fetched data. No
  invented figures, no invented price targets.
- Confidence must be stated; `low` confidence must name what is missing.
- Stale data (fundamentals snapshot older than 7 days) is called out in
  the report rather than presented as current.

## 6. Deliverables

**Summary Doc** (`tools/sync_summary_doc.py`): a new **Analyst View**
section, one block per holding — verdict, business view, confidence,
add-score with its four sub-scores, case for, case against, what would
change my mind, and the override reason when present. The section ends
with the **Where your next euro goes** ranked table.

**Sheet** (`tools/sync_google_sheet.py`): two new Overview columns,
`Verdict` and `Confidence`, placed after the technical columns and before
`P/E`. `Add` green, `Hold` neutral, `Stop adding` red, via
`TEXT_STARTS_WITH` rules (locale-safe, per the es_ES constraint). Plus a
new `Analyst` tab holding the ranked next-euro table. New Legend rows
explain the verdict ladder, the four sub-scores and the confidence levels.

## 7. Workflow

New file `workflows/analyze_portfolio.md` (the owner's approval of this design
is the approval to create it, per `CLAUDE.md`): the SOP for the analysis
pass — inputs to read per holding, the citation and confidence rules, the
override protocol, and how to write the ranking commentary.
`workflows/update_portfolio.md` step 5 gains a pointer to it.

## 8. Known tension with existing scores (not changed here)

Recorded so it isn't rediscovered later:
- `tools/scoring.py`'s `STATUS_BANDS` labels 0-25 as **"Sell"**, which
  contradicts the no-selling rule. The analyst layer uses its own bands and
  leaves the existing Rating untouched, because the owner reads that column
  today and a silent relabel would be worse than the inconsistency.
- `compute_momentum_score` rewards a *rising* price, which is backwards for
  someone deciding where to add money. The analyst layer does not consume
  it; the technical signals (RSI/MACD/Konkorde) serve that role instead.

Both are deliberate deferrals, revisitable if the owner wants the older scores
re-tuned.

## 9. Testing

- `tests/test_analyst.py`: each sub-score against hand-built profiles,
  including a MDLZ-like case (yield 4.4%, payout 0.75, D/E 239 → low
  dividend-safety, low quality) and a healthy blue chip; every score
  returns `None` with no inputs; clamping at both ends; the weighted
  `add_score` renormalizes correctly when a component is missing; band
  boundaries (exactly 65, exactly 45) resolve as specified.
- `compute_fit_score` against a concentrated portfolio
  (a sector above 25%, a position above 10%) as a regression case.
- `rank_next_euro`: ordering, exclusion of insufficient-data holdings.
- `tests/test_append_analysis.py`: the override guardrail exits non-zero
  without a reason and succeeds with one; enum validation rejects "Sell".
- Sheet/Doc tests extended for the new columns, tab and legend rows.
