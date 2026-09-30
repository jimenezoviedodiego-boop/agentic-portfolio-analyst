# Workflow: Analyze Portfolio (the analyst pass)

**Trigger:** Runs as part of `workflows/update_portfolio.md` step 5, after
prices/news/fundamentals are fetched and `record_snapshot` has run. The owner
may also ask for it alone ("what do you think about my holdings", "where
should my next contribution go").

**Objective:** Commit to a reasoned opinion per holding — a verdict, a
business view, a confidence level, the case for and against, and what
would change your mind — and produce the ranking of where the owner's next
contribution should go.

**What this is, and is not.** the owner makes every decision. This pass is
analysis, not advice, and it is never a recommendation to sell. Its value
is that it is consistent, shows its work, and states its uncertainty. Say
plainly when you don't know something.

## The strategy (what "good" means here)

Judge every holding against *this* strategy, not investing in general:

- Long-term buy-and-hold of blue chips. He does not trade.
- Dividends are reinvested, so **a dividend cut breaks the compounding
  plan**, not just this year's income. Dividend safety is weighted
  heaviest for that reason.
- He adds new money over time, aiming for a concentrated portfolio.
- **He does not sell.** The verdict ladder is Add / Hold / Stop adding.
  "Stop adding" means "no new money here for now", never "exit".

## Steps

1. **Compute the scores first.** Never write a verdict before seeing what
   the math says:

   ```
   python -c "from tools.portfolio_lib import load_portfolio; from tools.record_snapshot import latest_history_by_ticker; from tools.fetch_fundamentals import latest_fundamentals_snapshot; from tools.allocation import compute_allocation; from tools.analyst import analyze_portfolio, rank_next_euro; h=load_portfolio(); lh=latest_history_by_ticker(); lf={x['ticker']:(latest_fundamentals_snapshot(x['ticker']) or {}) for x in h}; a=analyze_portfolio(h,lf,lh,compute_allocation(h,lh,lf)); [print(r['rank'], r['ticker'], round(r['add_score'],1), r['verdict'], r['business_view'], r['dividend_safety'], r['quality'], r['value'], r['fit']) for r in rank_next_euro(a)]"
   ```

2. **For each holding, read before judging:**
   - its four sub-scores and the computed verdict (step 1),
   - `data/fundamentals/<TICKER>.yaml` — the latest snapshot,
   - `data/news/<TICKER>.jsonl` — this week's headlines,
   - the technical signals (RSI / MACD / Konkorde) from the ticker's
     Sheet tab or `tools.technicals.latest_signals`,
   - its position and sector weight from `tools.allocation`.

3. **Write the judgment**, obeying these rules:

   - **Cite or don't claim.** Every number in the case for/against must
     come from the fetched data. No invented figures, no invented price
     targets, no half-remembered facts about the company.
   - **"What would change my mind" must be checkable.** "Two consecutive
     quarters of revenue growth above 3%" is checkable. "If things
     improve" is not.
   - **Confidence is honest, not polite.** `low` must name what is
     missing or unresolved. Thin news plus stale fundamentals is a `low`,
     however confident the number looks.
   - **Stale data gets said out loud.** If the fundamentals snapshot is
     more than 7 days old, say so rather than presenting it as current.
   - **Never write "sell"**, in the verdict or the prose. If the case is
     bad, the verdict is "Stop adding" and the prose says why.

4. **Record it.** Always pass `--computed-verdict` — the tool requires it
   alongside `--verdict`, so the agent's call is always cross-checked
   against the score:

   ```
   python -m tools.append_analysis --ticker <TICKER> \
     --price-change-pct <PCT> --window "<WINDOW>" \
     --price-narrative "<NARRATIVE>" --status "<STATUS>" --watch "<WATCH>" \
     --news-sentiment-score <0-100> \
     --verdict "<Add|Hold|Stop adding|Insufficient data>" \
     --computed-verdict "<what step 1 printed>" \
     --business-view "<Bullish|Neutral|Bearish|Insufficient data>" \
     --confidence "<high|medium|low>" \
     --case-for "<...>" --case-against "<...>" \
     --what-would-change-my-mind "<...>" \
     [--override-reason "<required only when verdict != computed-verdict>"]
   ```

5. **Overriding the score is allowed — silently is not.** The tool
   refuses an override without a reason. Override when you can see
   something the formula cannot: a one-off charge distorting the payout
   ratio, an acquisition that explains the debt, news the numbers haven't
   caught up with. Do NOT override merely because a verdict feels harsh.
   The stored `computed_verdict` is what the score said *at the time*, so
   past overrides can be judged against what actually happened.

6. **Sync**, then tell the owner the three or four things that actually
   changed since last time — not every holding.

## Reading the scores honestly

- **A high dividend-safety score is about the dividend, not the company.**
- **A non-payer scores `n/a`, not 100.** AMZN and KD pay nothing today;
  their dividend-safety score is "not applicable", and the report says so.
- **Portfolio fit is about the owner, not the company.** A great business he
  already holds too much of scores badly on fit and well on the business
  view. That divergence is the point — say it out loud rather than
  averaging it away.
- **The ranking is relative.** #1 does not mean "buy now"; it means "of
  these holdings, this is where the next euro looks best placed".
- **Concentration beats cheapness.** When a sector is already above the
  25% cap, its holdings rank low even when their valuation scores look
  attractive. Say that explicitly rather than
  letting the number speak for itself.

## Error handling

- Missing fundamentals for a holding → its verdict is "Insufficient
  data". Do not guess a verdict from price action alone.
- An ETF has no dividend-safety or quality inputs. If it has no valuation
  data either, it is unrankable and reported under the ranking (this is
  the case for VWRL.AS today).
- If the scoring command errors, fix the tool before writing any
  narrative — never hand-wave a verdict around a broken score.

## Notes for future refinement

- **2026-09-21, first run.** Two defects surfaced only against real data,
  never in unit tests: non-payers scored 100/100 on dividend safety (now
  `None`), and an ETF with no valuation data was ranked on the
  concentration component alone (now unrankable). The lesson generalises:
  **dry-run the scores on the real portfolio and check them against
  holdings the owner knows well before trusting a ranking.**
- Open question for the owner: a non-payer is currently *excluded* from the
  dividend-safety component rather than *penalised* for paying nothing.
  For a strategy built on reinvested dividends, penalising may be the
  better fit. Revisit if the ranking keeps floating non-payers upward.
