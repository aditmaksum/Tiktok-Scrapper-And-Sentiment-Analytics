# TODOS

Deferred work, not scheduled into the current session's scope. Written down
per project convention: vague intentions don't count until they're here.

## sosmed_sentiment

- **FR-09 dry-run cost estimator** (`PRD.md` "Sebaiknya", never built). Split
  out of the 2026-08-30 DX-polish plan on purpose (`docs/plans/2026-08-30-dx-polish-post-model-cascade.md`)
  because it needs its own design, not a quick flag: estimate how many
  comments will escalate to the LLM from the local model's confidence
  distribution (no API calls made), then estimate cost from that count and
  the configured LLM's per-token pricing. `sample.py`'s existing `--dry-run`
  convention ("print the split and duration estimate, write nothing") is the
  pattern to follow for consistency, not a new one. Needs: where does
  per-token pricing come from (hardcoded table? env var? router API?) - that
  question alone is worth an `/office-hours` pass before implementation.

## sosmed_sentiment — report layer

Deferred from the 2026-09-02 `/autoplan` review of
`docs/plans/2026-09-02-insight-driven-report.md`. Each was surfaced, considered,
and consciously left out of that plan's scope.

- **Per-tier narrative and theme breakdown (KOL / Official / Affiliate).** P3.
  `html_builder._tier_breakdown` (:144-191) already computes per-tier sentiment,
  keywords, and themes using the same `classify_tier` the sampler and batch
  runner use, so the data is there and only the interpretation is missing. The
  operator's real question is usually "which tier is the problem", not "what is
  the aggregate". Deferred because reconciling the existing tier taxonomy with
  the plan's LLM-proposed theme taxonomy is its own design question, and because
  it multiplies the narrative LLM cost by the tier count. Blocked on the base
  narrative layer shipping first. Effort: M (human) -> S (CC).

- **Flat CSV export from `analyze`.** P2. One additional output file,
  `comments_flat.csv`, one row per comment with the 14 scalar fields already
  present in `analysis_result.json`. Unblocks every ad-hoc question the report
  did not anticipate — a spreadsheet pivot answers most of them — without a code
  change per question. ~20 lines in `output/serializer.py`. **Must write UTF-8
  WITH BOM and force `comment_id` / `video_id` to text**, or Excel converts the
  19-digit ids to scientific notation and silently destroys the low-order digits
  (this has bitten the project once already; see the
  `excel-corrupts-19-digit-comment-ids` learning). Deferred because it lives
  outside the report layer and is independent of everything in that plan.
  Effort: S -> S.

- **`pyproject.toml` with console entry points (`sosmed-analyze`,
  `sosmed-report`).** P3. `python -m sosmed_sentiment.cli.generate_report` is 45
  characters and is the larger half of the "command too long" complaint that
  started the 2026-09-02 plan; the flag changes in that plan address the shorter
  half. An entry point would cut more characters than every flag change
  combined, and would make the runbook's copy-paste lines permanently shorter.
  Deferred because it is packaging work unrelated to the insight layer, and
  because adding `--month` to `generate_report` (mirroring `analyze.py`:312-320)
  already takes the monthly command from 108 characters to 62, which resolves
  the stated pain. Effort: S -> S.

- **Engine reconciliation between the BERT and LLM classification paths.** P1,
  and the largest open question in the project — **not a report problem.**
  Measured on `runs/2026-08/analysis_result.json` during the 2026-09-02 review:
  the BERT path (n=4,077) scores net **+11.97** and the LLM path (n=4,147)
  scores net **+34.60**, a **22.63-point divergence** on the same scale the
  report's headline KPI uses. Which path a comment takes is decided entirely by
  `ambiguous_confidence_threshold: 0.95` in `config/thresholds.yaml`, which
  routes **51.9%** of the corpus to the LLM — so the headline number is
  substantially a measurement of the mixing ratio between two disagreeing
  instruments. The report plan's scope is **disclosure** (surface the divergence
  in the KPI row and the methodology block); **fixing** it means reconciling the
  two engines against the labeled sample and reporting one calibrated number.
  Needs an `/office-hours` pass. Effort: L -> M.

- **Diagnose the 251 `llm_failed` comments.** P2. That is **5.71% of LLM
  traffic** (251 of 4,398), against a **local** endpoint
  (`http://localhost:20128/v1`) where network failure is not the explanation.
  `Architecture.md` §8 sets the systemic-failure gate at 10% of escalations, so
  this run passed silently at more than half the alarm threshold. Sample 20 of
  the 251 and find out why — malformed responses, timeouts, or a prompt/parse
  mismatch. Also consider lowering the exit-3 gate: 10% of escalations is ~5% of
  the corpus, which is far too loose to be a useful alarm. Effort: S -> S.

- **Fix the stale claim in `docs/Architecture.md` §2.** P3. It states that
  `preprocessing/stemming.py` caches per unique token with `functools.lru_cache`.
  It does not — the file has no cache, and its docstring records that a
  per-token cache was tried and rejected because informal TikTok vocabulary is
  too wide for it to hit. Unrelated to the report plan; flagged during that
  review under see-something-say-something. Has already misled two review
  sessions (see the `architecture-doc-wrong-about-own-code` learning).
  Effort: S -> S.
