<!-- /autoplan restore point: /c/Users/asets/.gstack/projects/tiktok-comment-scrapper/feat-sentiment-model-cascade-and-report-review-autoplan-restore-20260904-113243.md -->

# Plan — LLM Narrative Layer with Citation Guardrail + Human Spot-Check

| | |
|---|---|
| **Tanggal** | 2026-09-04 |
| **Status** | Draf, belum direview |
| **Sumber** | `/office-hours` session 2026-09-04 (D1-D6), `docs/plans/2026-09-02-insight-driven-report.md` (master plan, Layer 2/3 architecture already reviewed 3x), `docs/TODOS.md`, `docs/Rules.md` |
| **Relasi** | Mengimplementasikan Layer 3 ("Narrative") dari master plan di atas, yang sengaja di-skip di fix-pass 2026-09-02c/03 (hanya Layer 1 metrics + deep-dive yang dibangun, Layer 3 LLM ditunda). Ini BUKAN plan dari nol — ambil arsitektur yang sudah diputuskan di master plan §3 Layer 3 dan §4, tambah 2 syarat baru dari office-hours: citation guardrail otomatis + human spot-check. |

## 1. Problem

`insights.py:build_narrative()` dan `_build_tier_narrative()` sekarang 100%
string format Python atas angka yang sudah dihitung deterministik — bukan LLM.
Ini sudah divalidasi user (399 test lolos, sesi 2026-09-03) tapi narasinya kaku:
tidak bisa merangkai insight lintas-metrik yang tidak dianggap penulis kode
sebelumnya (misal kombinasi tema + tier + tren dalam satu kalimat).

Project ini internal perusahaan — laporannya dipakai orang lain buat ambil
keputusan, jadi narasi yang lebih kaya nilainya nyata, TAPI resiko LLM menulis
klaim yang kedengaran meyakinkan tapi tidak didukung data juga nyata (lihat
`docs/plans/2026-09-02-insight-driven-report.md` S-5, sudah pernah diberi
rating CRITICAL oleh review sebelumnya, belum pernah diselesaikan).

## 2. Keputusan yang sudah difinalkan (`/office-hours` 2026-09-04)

Jangan direview ulang dari nol — ini keputusan user, ambil sebagai given, kecuali
ada bukti teknis baru yang mematahkannya:

- **D1 (terpisah, sudah dieksekusi, tidak diimplementasikan di plan ini):**
  500-sample ground truth (200 existing `local/labeling_sample_labeled.xlsx` +
  300 baru `local/labeling_sample_batch2_labeled.xlsx`, sudah dilabel user)
  dipakai untuk mengukur akurasi BERT vs LLM produksi lewat `compare_models.py`
  yang di-extend. **Tidak masuk scope plan ini** — dicatat di sini hanya untuk
  konteks, tiketkan terpisah kalau perlu.
- **D2 — Modul baru, bukan numpang di `llm_classifier.py`.** Sesuai keputusan
  arsitektur 0D master plan (baris ~412-423): **satu** modul baru
  `sosmed_sentiment/report/llm_insights.py` (bukan dua file terpisah
  `themes_llm.py` + `narrative_llm.py` seperti draf awal master plan) — satu
  titik panggil LLM baru di luar `sentiment/llm_classifier.py`, share pola
  client (`OpenAI`-compatible, `LLM_BASE_URL`/`LLM_API_KEY` dari env) dengan
  `sentiment/llm_classifier.py` tapi file terpisah karena kontraknya beda
  total (1 komentar -> 1 label vs metrics dict -> narasi).
- **D3 — Citation guardrail wajib.** Tiap klaim di narasi LLM harus menempel ke
  angka yang benar-benar ada di metrics dict yang dikirim ke LLM. Klaim tanpa
  angka pendukung valid = reject otomatis, bukan lolos ke laporan final.
- **D4 — Retry-then-fallback, BUKAN retry-then-blank.** Kalau guardrail reject:
  retry generate 1x. Kalau retry kedua juga reject: fallback ke
  `build_narrative()`/`_build_tier_narrative()` yang deterministik (Python,
  data selalu fresh dari run yang sama — bukan teks statis dari run lama).
  Section TIDAK PERNAH kosong. Ini juga sudah ditulis sebagai *"required, not
  optional"* di master plan §3 Layer 3 sebelum office-hours ini — office-hours
  hanya mengonfirmasi ulang, bukan keputusan baru.
- **D5 — Human spot-check ringan, bukan re-proses data.** Bukan membaca ulang
  komentar mentah. Baca ~10-15 kalimat narasi FINAL (headline + risk + actions
  + tiap tier narrative), cocokkan tiap angka yang disebut ke tabel yang sudah
  ada di laporan yang sama. Tidak di setiap generate — sample sebagian run,
  lebih sering di awal (masa membangun kepercayaan sistem), bisa dikurangi
  setelah terbukti reliable.
- **D6 — Diagnosis 251 komentar `llm_failed` — di luar scope, ditunda** (P2,
  sudah tercatat di `TODOS.md`, tidak terkait langsung ke narrative layer ini).

## 3. Konflik dengan aturan project — harus diresolusi SEBELUM koding

`docs/Rules.md` §3, baris 34:

> **Larangan tegas:** tidak boleh ada panggilan ke LLM API di luar
> `sentiment/llm_classifier.py`.

Modul baru `report/llm_insights.py` melanggar ini secara literal. Master plan
§4 sudah menuliskan opsi resminya (baris 153-160), auto-decided di sana:

> **Amend the rule** to "LLM calls only from dedicated `*_llm.py` client
> modules; never from `cli/`, never inline in business logic" — preserves the
> rule's actual intent (one auditable call site per concern) while allowing a
> second, legitimately different concern.

Ini persis **UC-4** yang masih terbuka di `TODOS.md` ("butuh amandemen Rules.md
§3 dulu, belum resmi dijalankan"). **Blocking step pertama plan ini**: amend
`Rules.md` §3 dengan kalimat di atas, dalam commit yang sama dengan
`llm_insights.py` pertama kali muncul — bukan didiskusikan lalu dilupakan.

## 4. Kontrak data — metrics dict ke LLM, dan balik

**Input ke LLM** (serialize `insights.py`'s metrics dict, subset yang relevan —
bukan seluruh dict, dan TIDAK PERNAH comment mentah individual, hanya angka
agregat + quote pendek yang sudah dipilih `insights.py` sebagai contoh):

```json
{
  "net_overall": 11.97,
  "classified_total": 8224,
  "sentiment_counts": {"positif": ..., "negatif": ..., "netral": ...},
  "tier_breakdown": [
    {"tier": "kol", "label": "KOL", "net": 23.0, "video_count": 61, "comment_count": 3621, ...},
    ...
  ],
  "themes": [...],
  "data_quality": {"unclassified_pct": ..., "llm_escalation_pct": ...}
}
```

Field mana persis yang masuk (semua dari `build_narrative()`'s existing
`metrics` parameter dan `_build_tier_deep_dive()`'s row dict — lihat
`insights.py:509-597` dan `:749+`) — detail final diputuskan Eng review di
`/autoplan`, bukan ditebak di sini.

**Output dari LLM**, strict JSON, bentuk SAMA seperti yang sudah didesain
master plan §3 Layer 3 (baris 106-112):

```json
{
  "headline": [{"title": "...", "body": "..."}],
  "risk":     [{"title": "...", "body": "..."}],
  "actions":  [{"title": "...", "body": "..."}]
}
```

## 5. Mekanisme guardrail (citation validator)

Sesudah LLM mengembalikan JSON di atas, sebelum masuk ke laporan:

1. Parse tiap `body` string, ekstrak semua angka yang disebut (regex angka +
   opsional tanda %, +/-).
2. Tiap angka harus match (dengan toleransi pembulatan, misal 1 desimal) ke
   salah satu nilai yang ADA di metrics dict yang dikirim tadi.
3. Kalau ada 1 angka saja yang tidak match ke metrics dict manapun -> seluruh
   response di-reject (bukan partial-accept per kalimat — lebih aman, lebih
   sederhana untuk diverifikasi).
4. Reject -> retry generate 1x (D4) -> masih reject -> fallback deterministic
   narrative untuk RUN INI (tidak mengubah default untuk run berikutnya).

**Belum terselesaikan di plan ini, harus dijawab reviewer `/autoplan`:**
guardrail di atas cuma menjamin angka valid — TIDAK menjamin hubungan
sebab-akibat yang ditulis LLM benar (S-5, master plan, CRITICAL, belum pernah
diselesaikan). Contoh: "Affiliate net +26.8 karena kontennya lebih otentik" —
angka valid, "karena"-nya karangan. Opsi yang perlu dipertimbangkan reviewer:
larang kata penghubung kausal (`karena`, `disebabkan`, `menunjukkan bahwa`,
dst) kecuali frasa itu sendiri ada di data tema/keyword yang dikirim; atau
strukturkan prompt supaya LLM hanya boleh mendeskripsikan (bukan menjelaskan
sebab) kecuali eksplisit diberi tag `[inferensi]` yang dirender beda secara
visual di HTML. Plan ini TIDAK memutuskan mana yang dipakai — hanya menandai
bahwa D3 (citation guardrail) sendirian tidak cukup untuk menutup S-5.

## 6. Human spot-check — mekanisme konkret

- **Bentuk:** tidak ada UI baru. `cli/generate_report.py` menambah flag
  `--narrative-review` yang, kalau di-pass, mencetak SEMUA kalimat narasi
  (headline/risk/actions/tier narratives) ke terminal SETELAH HTML ditulis,
  bersebelahan dengan angka metrics dict yang relevan supaya operator bisa
  cocokkan tanpa buka file lain (pola yang sama seperti `_print_tier_sanity_check`
  yang sudah ada di `generate_report.py:51-70`).
- **Kapan dipicu:** operator (yang menjalankan `generate_report`) yang
  memutuskan, bukan otomatis dari sistem — konsisten dengan D5 ("tidak di
  setiap generate"). Rekomendasi tertulis di runbook: pakai flag ini di setiap
  run selama 2 minggu pertama sistem jalan, setelah itu boleh sampling
  (misal 1 dari 5 run).
- **Bukan gate blocking:** laporan tetap ter-generate dan tersimpan meskipun
  operator tidak sempat spot-check — spot-check adalah quality signal
  tambahan, bukan syarat publish. (Kalau user mau ini jadi blocking gate,
  itu keputusan terpisah yang harus eksplisit dikonfirmasi — plan ini
  berasumsi tidak, karena D5 eksplisit bilang "gak di setiap generate".)

## 7. Testing (ikuti master plan §7 + tambahan guardrail)

| Layer | Yang dites | Perkiraan jumlah |
|---|---|---|
| Unit | Citation validator: angka valid lolos, angka tidak match ditolak, angka dengan pembulatan wajar lolos, body tanpa angka sama sekali (klaim kualitatif murni) — kasus batas yang perlu diputuskan eksplisit | +6-8 |
| Unit | Retry-then-fallback: reject pertama trigger retry, reject kedua trigger fallback ke `build_narrative()`, sukses di percobaan pertama tidak retry | +3 |
| Integration | `llm_insights.py` mocked client — valid JSON tervalidasi lolos; JSON valid tapi angka salah -> fallback; API failure -> fallback (bukan raise, konsisten `Rules.md` §2) | +3-4 |
| Integration | `--narrative-review` flag mencetak semua kalimat + angka pembanding, tidak crash saat metrics kosong | +1-2 |

## 8. Out of scope (jangan diseret masuk)

- D1 (validasi akurasi BERT vs LLM via 500 sample) — tiket terpisah.
- D6 (diagnosis `llm_failed`) — `TODOS.md`, P2, terpisah.
- Solusi final S-5 (larangan kausal / tagging inferensi) — DIPUTUSKAN di
  `/autoplan` review ini, bukan diimplementasikan sebelum direview.
- Perubahan `analysis_result.json` schema — tidak perlu, sesuai master plan §3.

## 9. Pertanyaan terbuka untuk `/autoplan` (CEO / Design / Eng / DX)

1. Field metrics dict mana persis yang masuk payload LLM (§4) — lengkap tapi
   tidak boros token.
2. Solusi konkret untuk S-5 (kausal fabrication) — lihat §5.
3. Apakah `--narrative-review` cukup sebagai bentuk spot-check, atau perlu
   sidecar file (`narrative_review.json`) supaya bisa diaudit belakangan (siapa
   generate kapan, apakah di-spot-check)?
4. Cache narasi (`narrative.json` sidecar, disebut master plan §3 baris 124-125)
   — apakah tetap relevan di sini, mengingat guardrail+retry+fallback menambah
   kompleksitas caching (cache hasil sebelum atau sesudah guardrail lolos?).

## User Challenges (queued)

Auto-run CEO review (no interactive user available). One premise below is
flagged as a genuine technical gap rather than accepted as given — queued
here per the run's operating rules instead of blocking on it.

- **What the plan assumes:** D3's citation guardrail (§5) — "every claim
  cites a number that exists in the metrics dict" — is described (and will
  read, to anyone skimming the plan) as making the narrative *accurate*.
- **Why it looks wrong:** the guardrail as specified checks numeric
  *membership* in a flat set of valid values, not numeric *binding* to the
  correct claim. `tier_breakdown` contains three `net` values (kol +23.0,
  affiliate +26.8, official +19.6) in the same metrics dict sent to the LLM.
  A hallucinated sentence — "Net sentimen KOL +26.8, jauh di atas tipe akun
  lain" — cites a real number (affiliate's, not KOL's) and passes the
  guardrail exactly as specified, because 26.8 is present somewhere in the
  payload. The guardrail cannot tell which entity a number was supposed to
  describe; it only proves the number wasn't invented from nothing.
- **Cost of proceeding anyway:** the shipped feature would carry an implicit
  "guardrail-verified" badge (§5, §6 spot-check pitches itself as the safety
  net) while remaining silently vulnerable to exactly the kind of
  cross-attribution error a human skim of 10-15 sentences (D5) is least
  likely to catch — spot-checkers verify "does 26.8 appear in the tables
  nearby," not "is 26.8 KOL's or affiliate's number," especially under time
  pressure during the 2-week high-frequency spot-check window. This is
  addressed below (Section 2 finding F1, auto-decided into scope) by binding
  each citation to its claim's entity (tier/theme label) at validation time,
  not just checking flat membership — but it is flagged here explicitly
  because the plan's own text (§5) describes the guardrail's guarantee more
  strongly than the literal mechanism (§5 steps 1-4) delivers.

## Decision Audit Trail

Auto-decided per the 6 CEO-phase principles (completeness, boil-the-ocean
within blast radius, pragmatic, DRY, explicit-over-clever, bias-to-action).
No interactive user available for this run; every non-trivial choice below
is logged rather than asked.

| # | Phase | Decision | Classification | Principle | Rationale |
|---|-------|----------|-----------------|-----------|-----------|
| 1 | 0C-bis | Chose "citation guardrail + causal-connector allowlist" (approach B) over guardrail-only (A) or guardrail+HTML-tagging (C) to close S-5 | Architecture — two-way door (extra regex layer inside `llm_insights.py`, easy to loosen/tighten later) | 1 completeness, 2 boil-the-ocean | Closes the plan's own explicitly-flagged CRITICAL gap (§5) within the same commit; C's HTML/template change is real but separable and deferred (row 3 below) rather than blocking this plan |
| 2 | 0D expansion | Accept causal-connector allowlist into this plan's scope (not deferred) | Scope addition, <1 day | 2 boil-the-ocean | S-5 was rated CRITICAL by a prior review and left unresolved twice already (§1); shipping D3 alone repeats that miss inside blast radius |
| 3 | 0D expansion | Accept a small `narrative_review.json` audit sidecar (generated_at, guardrail_status, reviewed_at/by — nullable) alongside `--narrative-review`, answering plan's open question #3 | Scope addition, <1 day (~20 lines, mirrors `output/serializer.py` JSON-write pattern) | 2 boil-the-ocean, 4 DRY | D5's "spot-check sample varies over time, more often early" is unauditable with terminal-only output — no record of which runs were checked. A sidecar is the same shape of artifact the codebase already uses (`themes.json`, `narrative.json`) rather than a new pattern |
| 4 | 0D expansion | Decide narrative cache (`narrative.json`) is keyed by a hash of the exact metrics-dict subset sent to the LLM, and only ever caches a **guardrail-accepted** narrative (never a rejected draft, never the deterministic fallback silently mislabeled as cached-LLM) | Two-way door, reversible | 5 explicit-over-clever | Directly answers plan's open question #4. Hash-keyed cache auto-invalidates on any data change (no manual `--refresh-narrative` dependency for correctness, though the flag stays as an explicit override) — the 10-line obvious fix beats a bespoke invalidation scheme |
| 5 | 0D expansion | Tighten payload rule: never send raw individual example quotes to `llm_insights.py`, only aggregate numbers + short theme labels/keyword lists; leave the *exact* field enumeration (plan open question #1) to Eng review, which owns `insights.py`'s metrics dict shape | Scope clarification, not full spec | 3 pragmatic | The guardrail (§5) can only verify numbers, not quoted text authenticity — sending quotes invites a citation the guardrail can't check. Deciding the constraint here and the enumeration in Eng review puts each decision with the party that owns the relevant contract |
| 6 | 0D expansion | Confirm D6 (`llm_failed` diagnosis), D1 (500-sample BERT/LLM comparison), and TD-7 (theme-primary rollup) stay out of this plan's scope, unchanged from the plan's own §8 | Scope hold | 2 boil-the-ocean (these sit outside this plan's blast radius; already tracked in `TODOS.md`) | No new information changes the prior review's placement of these items |
| 7 | Section 2 (Error/Rescue) | `llm_insights.py`'s guardrail-reject and malformed-JSON-from-LLM paths both route through the same "reject → retry → fallback" state machine (D4), not two different exception types | Code-shape choice | 5 explicit-over-clever | A malformed response and a response with an unverifiable citation have the same required handling (retry once, then deterministic fallback) — modeling them as one `NarrativeRejected` internal signal, not two, avoids duplicated retry/fallback logic (4 DRY too) |
| 8 | Section 2 (Error/Rescue) | The LLM transport failure itself (timeout, HTTP error, malformed JSON at the wire level) reuses `LLMCallError` from `sosmed_sentiment/errors.py` rather than a new exception class | Code-shape choice | 4 DRY | `errors.py` already defines the "one LLM call failed" contract; `llm_classifier.py` (line 84) raises exactly this. A second identically-shaped exception class for the second LLM call site would violate DRY for no benefit — the two call sites can share a rescue pattern even though they live in different modules |
| 9 | Section 6 (Tests) | Citation-validator unit tests use small hand-built metrics-dict fixtures (not property-based/fuzzed) for the boundary cases: exact match, rounding tolerance, no-numbers-in-body, negative numbers, percentage-vs-raw-count collision | Test design | 5 explicit-over-clever | The validator's correctness hinges on specific boundary values (rounding tolerance, sign handling) that are easier to reason about and review as named fixtures than as generated cases; this is a ~150-comment-scale internal tool, not a security-critical parser |
| 10 | Section 8 (Observability) | Guardrail outcome (accept / reject-then-retry-accept / reject-then-fallback) logs at `INFO` for accept, `WARNING` for reject-then-retry or fallback, one structured line per narrative generation, per `Rules.md` §7 log-level convention | Observability requirement | 1 completeness | `Rules.md` already defines this level scheme (§7) for the rest of the pipeline; the narrative layer should not invent its own |
| 11 | Section 9 (Deployment) | No new feature flag for the LLM narrative path — the required D4 fallback (§2) already IS the safe-degrade path; a separate flag would duplicate what "no `LLM_API_KEY`" already does (`Rules.md`/master-plan §3 Layer 3 fallback) | Deploy posture | 3 pragmatic, 4 DRY | Two independent kill switches for the same failure mode (missing/misbehaving LLM) is duplicated control surface, not extra safety |
| 12 | §3 Rules.md amendment | Adopt the master plan's exact wording ("LLM calls only from dedicated `*_llm.py` client modules; never from `cli/`, never inline in business logic") verbatim, no further edits | Governance, already 3x-reviewed | 3 pragmatic | This exact wording was already the auto-decided outcome of the master plan's own review (2026-09-02-insight-driven-report.md §4); re-litigating wording here would violate the "don't re-litigate settled decisions" instruction for this run |
| 13 | Section 11 (Design) | Skipped — no new UI/template scope in this plan (narrative text plugs into the existing headline/risk/actions blocks already rendered by `report.html.j2`; `--narrative-review` prints to the terminal, not a new screen) | Scope determination | 3 pragmatic | Matches the skill's own "skip if no UI scope detected" instruction for Section 11 |
| 14 | DX Phase | Add a `--no-narrative` boolean flag on `generate_report` that skips `llm_insights.py` entirely, independent of whether `LLM_API_KEY` is set | Scope addition, <1 day | 1 completeness, 6 bias-to-action | CEO Decision #11's "no flag needed, `LLM_API_KEY` absence is the kill switch" conflates two independent operator choices — trust LLM sentiment escalation in `analyze` but not yet trust LLM narrative prose in `generate_report` — since both currently key off the same env var. A scoped flag closes this without reopening #11's actual point (no *second* env-var-driven kill switch is needed, just a narrative-only override) |
| 15 | DX Phase | Name the narrative-cache-bypass flag `--fresh-narrative`, not `--refresh-narrative` | Naming consistency, <1 day | 5 explicit-over-clever, naming consistency over cleverness | `analyze.py --fresh` (cli/analyze.py:333-337) is already this codebase's chosen verb for "ignore the cache/checkpoint and redo the work." A second flag inventing `--refresh` for the same concept on `generate_report` would fork the CLI suite's naming grammar for no reason — this directly answers the plan's still-open cache-bypass question (Decision #4) with the name, not just the mechanism |
| 16 | DX Phase | `--narrative-review`'s terminal output must lead with a one-line narrative-source banner (`llm-accepted` / `llm-retried-then-fallback` / `no-llm-configured`) before the sentence-by-sentence dump | UX/error requirement, <1 day | 1 completeness, "problem+cause+fix" always required for error-adjacent output | Without this, an operator doing the D5 spot-check has to separately scroll the WARNING/ERROR log lines above the dump to learn whether they are reading an LLM narrative or a silent fallback — the one fact that most changes how skeptically they should read the numbers |
| 17 | DX Phase | Add an explicit task to update `README.md` (`### Running it`, ~line 362-378) and `docs/runbook.md` with `--narrative-review` usage and the "every run for the first 2 weeks, then sample 1-in-5" cadence | Docs scope addition, <1 day | 2 boil-the-ocean | Plan §6 promises this cadence is "written in runbook," but none of the CEO phase's Implementation Tasks (T1-T7) touch `README.md` or `docs/runbook.md` — the promise currently has no task backing it, so it would silently not happen |
| 18 | DX Phase | `llm_insights.py`'s WARNING/ERROR log lines for guardrail-reject and transport-failure must follow the same problem+cause+fix message shape `analyze.py` already uses (e.g. its LLM-not-configured message at cli/analyze.py:182-186, or its model-load-failure message), not just land on the correct log level | Code-shape / message-content requirement, <1 day | 5 explicit-over-clever, "problem+cause+fix" always required | CEO Decision #10 fixed the log LEVEL scheme (INFO/WARNING) but not message CONTENT. This repo already sets a message-quality bar elsewhere in the same CLI suite (`analyze.py`'s own error text names what happened, why, and what to do) — the new module should be held to that existing bar explicitly, not left to land wherever the implementer's first draft happens to phrase it |
| 19 | Eng Phase | Add explicit JSON-shape/type validation (isinstance checks on headline/risk/actions structure) as the FIRST guardrail step, raising `NarrativeGuardrailError` directly rather than relying on F2's top-level `except Exception` catch to absorb a malformed-but-syntactically-valid JSON response | Scope addition, <1 day | 1 completeness, 5 explicit-over-clever | "Wrong shape" in CEO Section 2's error table was never disambiguated from "missing keys" vs "keys present, wrong type" — routing the latter through F2's ERROR-level last-resort catch instead of the guardrail's own WARNING-level reject conflates "routine malformed LLM response" with "something is badly broken," degrading the observability CEO Decision #10 already established (test-plan artifact row 6) |
| 20 | Eng Phase | Add a numeric-collision-across-entities fixture test (two different tiers/fields sharing the identical cited number) to prove F1's entity-binding fix resolves by nearest-label, not first-match | Test-only addition, <1 day | 1 completeness, 2 boil-the-ocean | F1's fix is only as strong as its own test coverage; no existing test in §7/CEO Section 6/DX forces an actual numeric TIE across entities, which is exactly the scenario F1 exists to close (test-plan artifact row 14) |
| 21 | Eng Phase | Define `--no-narrative` + `--narrative-review` combined-flag behavior explicitly (reuse the `no-llm-configured`-equivalent banner text, or a 4th `narrative-disabled` state) rather than leaving it to click's unspecified flag precedence | Scope addition, <1 day | 5 explicit-over-clever, 1 completeness | Two flags this review pipeline is adding (T8, T10) interact and neither prior phase specifies the interaction — an undefined combination is exactly the kind of ambiguity Rules.md §11 asks the implementer NOT to silently resolve with the easiest interpretation (test-plan artifact row 35) |
| 22 | Eng Phase | Add message-content substring assertions (not just log-level assertions) to the tests T12 already specifies for the transport-failure/guardrail-reject log lines | Test-only addition, <1 day | 1 completeness ("well-tested code is non-negotiable") | T12's own verify line says "code review only, no new test needed" — under-tests a requirement (Decision #18) that exists specifically because message CONTENT, not just level, was found lacking; a substring assertion costs ~5 lines and prevents future silent drift back to a generic stub message |
| 23 | Eng Phase | Name the volume floor constant `MIN_NARRATIVE_VOLUME = 30`, defined in `llm_insights.py`, mirroring `insights.py`'s `MIN_VIDEO_COMMENTS = 30` (not `MIN_MONTH_VOLUME = 20`) | Scope clarification, concrete value | 5 explicit-over-clever | Section 4's original recommendation named the constant but not its value; `MIN_VIDEO_COMMENTS` is the closer analogue (both gate "is this subset of the corpus large enough to say something meaningful," not "is this a whole calendar month") — picking a value here removes one ambiguous judgment call from T5's implementation |
| 24 | Eng Phase | Set an explicit request timeout (e.g. 30s) on `llm_insights.py`'s `OpenAI()` client construction, distinct from `llm_classifier.py`'s existing untimed pattern | Scope addition, <1 day | 1 completeness, 3 pragmatic | `llm_classifier.py`'s lack of an explicit timeout is an accepted, out-of-blast-radius risk there (thousands of small per-comment calls, any one hang is isolated by the existing per-comment try/except). `llm_insights.py` is architecturally different: ONE synchronous call gates the entire report render with no per-item isolation — an unbounded hang blocks `generate_report` indefinitely, since D4's retry/fallback logic never gets a chance to run until the call itself returns or errors |
| 25 | Eng Phase | Confirmed (verified finding, not a new decision): Jinja2's `select_autoescape(['html', 'j2'])` (`html_builder.py:493`) already escapes `{{ item.body }}`/`{{ item.title }}` for both the existing deterministic narrative AND the new LLM narrative — no `\|safe` filter touches either narrative block in `report.html.j2` (confirmed by reading the template, lines 282-401). Add one regression test asserting an HTML-metacharacter-bearing narrative body renders escaped in `report.html` | Test-only addition, <1 day | 1 completeness | Prevents a future template edit from silently adding `\|safe` to the narrative blocks without a test catching the regression — this is the one place a text source is about to become LLM-authored where escaping matters most |
| 26 | Eng Phase | Recommend atomic write (write-to-tmp, then `os.replace()`) for both `narrative.json` (Decision #4) and `narrative_review.json` (Decision #3) sidecar writes, folded into T3/T4's existing implementation rather than a new task | Code-shape requirement, <1 day | 1 completeness | Decision #4 already specifies "corrupt cache file -> treat as miss, log WARNING" (good defense on the READ side); an interrupted write (Ctrl-C, disk full mid-write) is the actual mechanism that produces a corrupt file in the first place — atomic write closes the gap at the source instead of only defending against its symptom |

## GSTACK REVIEW REPORT — CEO Phase (2026-09-04)

Auto-mode run: no interactive user available. Every AskUserQuestion point in
the skill was auto-decided per the 6 principles above instead of asked; every
decision is logged in the Decision Audit Trail. codex CLI is confirmed
absent on this machine — the "Outside Voice" step below runs as a
self-performed adversarial CEO-strategist pass (Claude only), not a
subagent dispatch, per this run's explicit instruction. Codex column in the
consensus table is N/A throughout.

### Step 0: Platform / base branch

No git repository detected at the working directory (`git remote get-url
origin` and every git-native fallback fail — this is a plain directory, not
a git repo). Base-branch detection is not applicable; proceeding without it,
consistent with "git-native fallback... if all fail, fall back to `main`"
degrading gracefully rather than blocking.

### Pre-review system audit

- `TODOS.md` (repo root): read in full. Contains 6 open items, one directly
  relevant here (the P1 BERT-vs-LLM 22.6-point divergence item — informs
  D1, correctly out of this plan's scope) and one indirectly relevant
  (D6's 251 `llm_failed` comments, 5.71% of LLM traffic against a **local**
  endpoint — worth remembering when sizing `llm_insights.py`'s own retry
  budget, since local-endpoint failures aren't purely network noise).
- `docs/Rules.md`: read in full. §3 line 34 is the literal blocking
  constraint this plan must amend (confirmed exact text match against the
  plan's §3 quote). §7 defines the log-level convention reused in Decision
  #10. §9 states `sentiment/llm_classifier.py` tests **must** mock the API
  call — the same rule needs to extend to `report/llm_insights.py`'s tests;
  the plan's own testing table (§7) already frames tests as "mocked client,"
  consistent with this.
- `sosmed_sentiment/sentiment/llm_classifier.py` (85 lines, read in full):
  the reuse target named in D2. Established pattern: `_client()` factory
  wrapping `OpenAI(api_key, base_url)`, env-var read at the call site
  (`LLM_API_KEY`), `MAX_RETRIES=2` with linear backoff over
  `RETRY_BACKOFF_SECONDS=(1,3)`, broad `except Exception` at the transport
  layer only (annotated `# noqa: BLE001`, intentional — any failure there is
  a retry candidate), raising `LLMCallError` after exhausting retries. This
  is the pattern `llm_insights.py` should structurally mirror for its own
  transport-level retry (distinct from D4's content-level retry — see
  Decision #7).
- `sosmed_sentiment/errors.py` (40 lines, read in full): five exceptions,
  all `PipelineError` subclasses, each with an explicit fatal/non-fatal
  docstring contract. No existing exception fits "guardrail rejected the
  LLM's JSON" — new signal needed (Section 2).
- `sosmed_sentiment/report/insights.py` (938 lines): `build_narrative()`
  at line 749, `_build_tier_narrative()`/`_build_tier_deep_dive()` around
  lines 480-597 as the plan's §4 references state. Confirmed these are the
  deterministic fallback targets D4 requires — they take the same metrics
  dict shape the plan proposes sending to the LLM, so "fallback to
  `build_narrative()`" is mechanically direct, not a rewrite.
- `sosmed_sentiment/cli/generate_report.py` (180 lines, read in full):
  `_print_tier_sanity_check()` (lines 51-70) is the exact existing pattern
  the plan's §6 cites for `--narrative-review` — confirmed it already prints
  per-tier numbers to the terminal via `logger.info` before the HTML write,
  the same shape §6 proposes. `run_generate_report()` catches
  `ReportBuildError` from `build_report()` and returns exit code 2; the new
  `llm_insights.py` call site needs to NOT raise into this path if D4's
  fallback is to hold (a raised, uncaught guardrail failure would currently
  propagate as an unhandled exception, not the intended graceful fallback —
  flagged in Section 2, F2).
- No stashed work, no other open plan files under review, no prior CEO plan
  documents under `~/.gstack/` for this feature slug (fresh review).

### 0A. Premise Challenge

1. **Right problem?** Yes, with one flagged gap (see User Challenges above).
   Richer cross-metric narrative is real, stated value for an internal
   report stakeholders use to decide; the existing deterministic narrative
   is already validated (399 tests, 2026-09-03) but structurally cannot
   combine insights its authors didn't anticipate. LLM narrative generation
   is the direct tool for that specific gap — not a proxy metric.
2. **Actual outcome vs. proxy?** The actual outcome is "a stakeholder trusts
   and acts on the report correctly." Citation guardrail (accuracy of
   numbers) is a genuine proxy for only *half* of that outcome; the other
   half (causal correctness) is explicitly unaddressed until Decision #1/#2
   above. With those decisions folded in, the plan now targets the real
   outcome, not just the numeric-membership proxy.
3. **Do-nothing cost?** Real but bounded — the current system works and is
   tested; the cost of doing nothing is a report that's accurate but reads
   as a spreadsheet with sentences, not a genuinely helpful analysis.
   Moderate value, moderate urgency — matches SELECTIVE EXPANSION (hold
   scope, cherry-pick), not a forced EXPANSION.

### 0B. Existing Code Leverage

- `llm_classifier.py`'s client/retry pattern → reused by `llm_insights.py`
  per D2 (confirmed necessary, not duplicative — different contract,
  1-comment-in/1-label-out vs. metrics-in/JSON-narrative-out, matches the
  master plan's own reasoning at 2026-09-02 plan §4 for why one shared
  module was rejected).
- `_print_tier_sanity_check()` → reused as the direct precedent for
  `--narrative-review` (D5/§6). Confirmed, not rebuilt.
- `build_narrative()`/`_build_tier_narrative()` → reused as-is for D4's
  fallback path, unchanged. Confirmed no rebuild.
- Nothing in this plan rebuilds existing code; it is additive.

### 0C. Dream State Mapping

```
CURRENT STATE                       THIS PLAN (+ auto-accepted        12-MONTH IDEAL
                                     expansions)
Deterministic narrative,     --->   LLM narrative, numeric      --->  Narrative system where every
rigid but 100% trustworthy,         citation guardrail +               claim is both numerically
399 tests passing. Cannot           causal-connector allowlist         AND causally verifiable;
combine cross-metric                (Decision #1/#2), retry-then-      spot-checks are tracked in
insights the code's authors         fallback (D4, never blank),        an audit sidecar with a
didn't anticipate.                  audited human spot-check           trend line ("caught N/run,
                                     sidecar (Decision #3), hash-       falling"); narrative quality
                                     keyed narrative cache               is scored against the
                                     (Decision #4), Rules.md §3          500-sample ground truth
                                     amended for one auditable           (D1) the same way BERT/LLM
                                     second LLM call site.                classification accuracy is.
```

### 0C-bis. Implementation Alternatives (S-5 guardrail mechanism)

The master plan's architecture (module split, JSON contract, retry/fallback
state machine) is already 3x-reviewed and out of scope to re-litigate. The
one genuinely open architectural decision left in *this* plan is §5's own
question: how to close S-5 (causal fabrication). Three approaches:

```
APPROACH A: Numeric guardrail only, as specced
  Summary: Ship §5 exactly as written — no causal-language constraint.
  Effort:  S (human: ~2h / CC: ~15min)
  Risk:    High — ships with a CRITICAL gap the plan itself names and does
           not close (S-5, rated CRITICAL twice already, per §1).
  Pros:    Smallest diff. Fastest to land.
  Cons:    Repeats the exact miss two prior reviews already flagged;
           "guardrail-verified" narrative can still fabricate causation.

APPROACH B: Numeric guardrail + causal-connector allowlist (RECOMMENDED)
  Summary: Reject a claim if it uses a causal connector ("karena",
           "disebabkan", "menunjukkan bahwa", "sehingga", "akibatnya", ...)
           unless that connector's causal pairing is already present in the
           theme/keyword data sent to the LLM (i.e. the LLM is only allowed
           to restate a causal link insights.py's deterministic theme
           extraction already surfaced, never invent a new one).
  Effort:  S-M (human: ~4h / CC: ~30min) — one regex pass + one membership
           check against the theme payload, inside the same validator
           function §5 already specifies.
  Risk:    Low. Reversible (loosen/tighten the connector list later).
  Pros:    Closes the plan's own explicitly-flagged CRITICAL gap in the
           same commit. Small, explicit, testable in isolation (Decision
           #9's fixture style fits it directly).
  Cons:    Indonesian causal-connector coverage will need occasional
           tuning (the allowlist is a living list, not exhaustive at
           launch) — acceptable given it fails closed (over-rejection just
           triggers D4's fallback, never a false "safe" claim).

APPROACH C: Numeric guardrail + structural [inferensi] tagging
  Summary: Extend the LLM's output JSON schema so any interpretive/causal
           sentence carries an explicit tag, rendered as a visually
           distinct span in the HTML (§5's second option).
  Effort:  M (human: ~1-2 days / CC: ~1-2h) — schema change, prompt change,
           AND a `report.html.j2` template change (new CSS treatment) —
           the one path here that touches rendering, which the rest of
           this plan deliberately does not.
  Risk:    Low-medium. Most transparent to the end reader long-term, but
           the template diff makes it the largest change of the three and
           couples this plan to a Layer 4 (rendering) change it currently
           has zero other reason to touch.
  Pros:    Best long-term reader trust — an explicit "this is inference"
           marker is more honest than silently allowing/disallowing causal
           language.
  Cons:    Largest diff, only approach requiring a template/CSS change,
           delays shipping the (already twice-deferred) guardrail fix.
```

**RECOMMENDATION:** Approach B (Decision #1). Closes the CRITICAL gap this
plan itself flags, at the same effort scale as the rest of §5, without
pulling in template work this plan otherwise doesn't need. Approach C's
value is real but belongs with the next Layer-4/rendering pass — logged to
`TODOS.md` below as a P2 follow-up rather than silently dropped.

### 0D. SELECTIVE EXPANSION analysis

**Complexity check:** plan touches one new module (`llm_insights.py`), one
doc amendment (`Rules.md` §3), one CLI flag, plus the auto-accepted
sidecar/cache additions — comfortably under the 8-file / 2-new-service smell
threshold. No red flag.

**Minimum viable set:** guardrail (with Decision #1's connector allowlist
folded in — cutting it back out would reopen the CRITICAL gap, so it's
treated as part of the minimum, not an optional extra), retry-then-fallback,
Rules.md amendment, `--narrative-review` flag, tests. Nothing here can be
deferred without reopening either the blocking rule conflict (§3) or the
explicitly-flagged S-5 gap.

**Expansion scan → cherry-pick outcomes** (auto-decided, logged in the
Decision Audit Trail table above):
- Causal-connector allowlist — **ACCEPTED** (row 2).
- `narrative_review.json` audit sidecar — **ACCEPTED** (row 3).
- Hash-keyed narrative cache semantics — **ACCEPTED** as a clarification
  (row 4), not new scope; resolves the plan's own open question #4.
- Payload tightening (no raw quotes to the narrative LLM) — **ACCEPTED**
  as a constraint (row 5); exact field list left to Eng review.
- `[inferensi]` structural tagging (Approach C above) — **DEFERRED** to
  `TODOS.md` (P2, next Layer-4 pass).
- D1, D6, TD-7 — **confirmed out of scope**, unchanged (row 6).

### 0E. Temporal Interrogation

```
HOUR 1 (foundations):    Rules.md §3 amendment lands in the SAME commit as
                          llm_insights.py's first appearance (already
                          required by the plan, §3) — implementer should
                          write the doc diff first so the module never
                          exists in a rule-violating state, even transiently.
HOUR 2-3 (core logic):   The guardrail validator needs the tier/theme
                          payload's exact shape settled before the connector
                          allowlist can check causal-pairing membership
                          (Decision #1 depends on Decision #5's payload
                          constraint being resolved first, not after).
HOUR 4-5 (integration):  generate_report.py's exception handling around the
                          new call site (F2, Section 2) — a raised, uncaught
                          guardrail/transport error must not propagate past
                          run_generate_report() the way ReportBuildError
                          currently does; this is easy to miss because the
                          existing exit-code-2 path looks like "the pattern
                          to follow" when it's actually the wrong one here
                          (D4 requires a caught, logged, non-fatal fallback).
HOUR 6+ (polish/tests):  Cache-key hashing (Decision #4) needs a stable,
                          deterministic serialization of the metrics subset
                          (sorted keys, fixed float formatting) or identical
                          runs will silently miss the cache and re-bill an
                          LLM call — worth a dedicated unit test, not just
                          an integration-level assumption.
```

(Effort scale: all four items above are CC-compressed to 10-20 min each once
identified; the value here is surfacing the sequencing/dependency now,
not the raw hours.)

### 0F. Mode confirmed

**SELECTIVE EXPANSION**, as instructed for this run. Scope held at the
plan's own baseline + the cherry-picks accepted in 0D above. Committed for
the remainder of this review — no drift toward HOLD or EXPANSION below.

---

### Dual Voices — Independent Challenge

| Voice | Ran? | Verdict |
|---|---|---|
| Claude CEO subagent (self-performed adversarial pass, per this run's instructions) | Yes | Issues found — folded into Sections 1/2/3/10 below and the User Challenges entry above |
| Codex | N/A (codex unavailable) | N/A (codex unavailable) |

**Overall dual-voice status: [subagent-only]** — codex CLI confirmed absent
on this machine per this run's setup; no fallback subagent dispatch was run
either, per this run's explicit instruction to perform the adversarial pass
directly instead of spawning one.

**Self-performed adversarial pass — findings not already covered above:**
1. *Is this the right problem?* Answered in 0A — yes, with the flagged gap.
2. *Premises assumed vs. stated:* the plan states D3 closes the risk (§1
   frames S-5 as "belum pernah diselesaikan" and implies this plan is where
   it gets resolved) but §5's own body then says D3 alone does *not* close
   it and defers the actual mechanism to this review — that's the User
   Challenges entry above, now resolved by Decision #1.
3. *6-month regret scenario:* if Approach A (guardrail-only) had shipped
   instead of B, the 6-month regret is a stakeholder making a real decision
   off a causally-fabricated but numerically-verified claim, discovering it
   was wrong, and losing trust in the *entire* narrative system — including
   the parts that were accurate — which is strictly worse than the current
   rigid-but-trusted deterministic narrative it replaces. This is why
   Decision #1 was folded into the minimum scope rather than deferred.
4. *Alternatives dismissed too quickly:* none found — the master plan's
   architecture was already through 3 rounds and this plan correctly
   avoids re-opening it; the one real open decision (guardrail mechanism)
   got the full 3-approach treatment above.
5. *Competitive/market risk:* not applicable — internal tool, weighted
   lightly per this run's instructions. No finding.

---

### Section 1: Architecture Review

```
                 ┌─────────────────────┐
                 │ analysis_result.json│
                 └──────────┬──────────┘
                             │
                    insights.py (Layer 1, deterministic)
                    build_narrative() / build_metrics()
                             │
                 ┌───────────┴────────────┐
                 │  metrics dict subset    │  (Decision #5: aggregates +
                 │  (no raw quotes)        │   theme labels only, no quotes)
                 └───────────┬────────────┘
                             │
                    report/llm_insights.py   (NEW — D2)
                    reuses llm_classifier.py's client/retry
                    pattern (transport-level, MAX_RETRIES-style)
                             │
                    LLM call → strict JSON
                    {headline, risk, actions}
                             │
                    citation guardrail (§5 + Decision #1
                    causal-connector allowlist)
                             │
              ┌──────pass────┴────reject (D4)─────┐
              │                                     │
      accept, cache (Decision #4,             retry generate 1x
      hash-keyed, post-guardrail only)               │
              │                              ┌───pass───┴───reject──┐
              │                              │                       │
              │                        accept, cache          fallback to
              │                              │                build_narrative()/
              │                              │                _build_tier_narrative()
              │                              │                (Layer 1, same run's
              │                              │                 fresh metrics — D4)
              └──────────────┬───────────────┴───────────────┘
                             │
                    html_builder.build_report()
                    (existing render path, unchanged)
                             │
                    report.html + narrative_review.json sidecar
                    (Decision #3, updated by --narrative-review)
```

- **Component boundaries:** clean — `llm_insights.py` is the second and
  only other LLM call site (D2/Rules.md amendment), matches
  `llm_classifier.py`'s pattern without merging into it. No new coupling
  between `report/` and `sentiment/` beyond the shared client-construction
  pattern (which is duplication-by-necessity, not accidental — flagged
  correctly by the plan itself as intentional).
- **Coupling concerns:** `generate_report.py` now depends on
  `llm_insights.py` in addition to `html_builder.py`. Justified — CLI
  orchestration only, no business logic added to `cli/` (Rules.md §3's
  second clause).
- **Scaling:** narrative generation is one LLM call per report render (not
  per comment), so 10x/100x comment volume does not change the LLM call
  count — only the metrics dict computation (Layer 1, already O(n) over
  comments) scales, and that's unchanged by this plan.
- **Single point of failure:** the LLM endpoint itself — fully mitigated by
  D4's fallback; a report NEVER fails to render because of this dependency
  (confirmed: `build_narrative()` requires no network access).
- **Rollback posture:** trivial — this plan adds a code path behind a
  purely additive contract (existing `build_narrative()` untouched, new
  module opt-in via env vars already required for any LLM path per
  `analyze.py`'s existing `LLM_API_KEY`/`LLM_MODEL`/`LLM_BASE_URL`
  convention). Reverting the commit removes the new path; no data
  migration, no schema change (§8 confirms no `analysis_result.json`
  schema change).

No unresolved architecture findings beyond what's captured in Decisions
#1-#5 above.

### Section 2: Error & Rescue Map

```
  METHOD/CODEPATH                        | WHAT CAN GO WRONG                     | EXCEPTION CLASS
  ----------------------------------------|----------------------------------------|---------------------------
  llm_insights.generate_narrative()       | LLM endpoint timeout/network error    | LLMCallError (reused, Decision #8)
                                           | LLM returns non-JSON content          | LLMCallError (reused, Decision #8)
                                           | LLM returns valid JSON, wrong shape    | NarrativeGuardrailError (NEW)
                                           | (missing headline/risk/actions keys)  |
                                           | LLM returns valid JSON, cited number  | NarrativeGuardrailError (NEW)
                                           | not in metrics dict (S-5 numeric)     |
                                           | LLM returns valid JSON, causal claim  | NarrativeGuardrailError (NEW)
                                           | not backed by theme/keyword data      | (Decision #1)
                                           | (S-5 causal)                          |
                                           | LLM_API_KEY absent entirely           | not an error — same "no LLM
                                           |                                        | configured" convention as
                                           |                                        | analyze.py, skip straight to
                                           |                                        | fallback, log at INFO not ERROR
  narrative cache read (Decision #4)      | narrative.json exists but hash key    | treat as cache-miss, not error
                                           | doesn't match current metrics subset  | (Decision #4's whole point)
                                           | narrative.json is corrupt/truncated   | treat as cache-miss, log WARNING
  narrative_review.json sidecar write     | output dir not writable               | OSError — caught, logged
  (Decision #3)                           |                                        | WARNING, report STILL writes
                                           |                                        | (sidecar is a quality signal,
                                           |                                        | never a publish gate — §6)
  generate_report.run_generate_report()   | llm_insights raises uncaught past its | F2 (GAP, see below)
  (existing, new call site added)         | own boundary                          |

  EXCEPTION CLASS              | RESCUED?     | RESCUE ACTION                              | USER SEES
  ------------------------------|--------------|---------------------------------------------|------------------------
  LLMCallError                  | Y (in llm_insights.py, per D4) | retry 1x, then fall to build_narrative() | Nothing — narrative renders normally, banner marks source (master plan §3's existing "banner marks which mode produced the narrative" requirement — confirmed still applies)
  NarrativeGuardrailError       | Y (in llm_insights.py, per D4) | retry 1x, then fall to build_narrative() | Same as above
  OSError (sidecar write)       | Y            | log WARNING, continue                       | Nothing (report still writes — D5's "not a gate" requirement)
  Uncaught exception past       | N ← **F2 GAP** | —                                          | Whatever run_generate_report()'s
  llm_insights.py's own                                                                       generic exception handling does
  boundary (transport error                                                                    today — likely an unhandled
  during retry #2, e.g.)                                                                       traceback, NOT the intended
                                                                                                 graceful fallback banner
```

**F1 (from User Challenges, folded into Decision #1):** the numeric-only
guardrail's blind spot (number valid but attributed to the wrong
tier/entity) — resolved by binding each parsed number to the specific
tier/theme label it's syntactically nearest to in the claim, then checking
that *pair* against the metrics dict (tier X → net Y), not just checking Y
alone against a flat set of all valid numbers in the payload. This is a
refinement of §5 step 2, not a new mechanism — implementer detail worth
spelling out in the eng-review pass.

**F2 (GAP — CRITICAL):** the plan's D4 promises "section TIDAK PERNAH
kosong" (never empty) via retry-then-fallback, but that promise is only as
strong as `llm_insights.py`'s own exception handling. If a bug or an
unanticipated exception type escapes `llm_insights.py`'s own
try/except-and-fallback wrapper (e.g. the *second* retry attempt itself
throws something not caught by the inner handler, or a `KeyError` from
malformed guardrail logic), it propagates into `run_generate_report()`,
which currently only catches `ReportBuildError` (generate_report.py, the
`try/except ReportBuildError` block around `build_report()`). An uncaught
exception there is NOT the intended graceful degrade — it's an unhandled
crash, the opposite of D4's guarantee. **Fix (folded into scope, <1 day):**
wrap the entire narrative-generation call (guardrail included) in
`llm_insights.py` in a top-level `except Exception` that unconditionally
falls back to `build_narrative()`/`_build_tier_narrative()` and logs at
`ERROR` — belt-and-suspenders under D4's own "section is never empty"
promise, matching the existing `classify_via_llm()` precedent (Rules.md
§2's "never let one failure stop the whole run").

### Section 3: Security & Threat Model

- **Attack surface:** none new in the traditional sense — no new user input,
  no new endpoint (this is an offline CLI report generator per Rules.md
  §8, "tidak ada input dari pengguna luar"). The LLM call itself is an
  outbound call to a configured endpoint, same trust boundary as
  `llm_classifier.py`.
- **Prompt injection:** the metrics dict payload (Decision #5: aggregates +
  theme labels, no raw comment text) substantially narrows this compared
  to sending raw comments — theme *labels* were themselves LLM-generated
  once (Layer 2, `themes_llm.py`, cached) from real comment text, so a
  motivated commenter could in principle seed a theme label with
  injection-style text that later reaches the narrative LLM. Low
  likelihood/low impact for an internal tool with no automated action on
  the LLM's output (a human reads it; D4's citation guardrail also bounds
  what survives to the report) — noted, not blocking.
- **Secrets:** reuses `LLM_API_KEY`/`LLM_BASE_URL` env-var convention
  already established (`analyze.py`, `llm_classifier.py`) — no new secret
  handling introduced, no new logging risk (Rules.md §7 already forbids
  logging the key; the new module inherits the same client factory
  pattern, not a copy that could drift).
- **New dependency:** none — reuses the already-vendored `openai` SDK.

No High-severity findings. No blocking issues.

### Section 4: Data Flow & Interaction Edge Cases

```
  INPUT ──▶ metrics dict ──▶ LLM call ──▶ guardrail parse ──▶ cache/render
    │            │                │               │                │
    ▼            ▼                ▼               ▼                ▼
  [nil?]     [empty metrics,  [LLM returns   [claim with no    [cache write
  analysis_   e.g. 0 classi-  empty string   numbers at all —  fails silently
  result.json  fied comments  or refusal     qualitative-only  vs. loudly?]
  always      — see below]    text]          claim — reject    → Decision #3's
  present,                                   or allow? See      OSError handling
  schema-                                    below]             covers this
  validated
  upstream]
```

- **Empty-metrics edge case (GAP, minor):** the plan doesn't explicitly
  address what happens when `classified_total` is 0 or very low (e.g. a
  test run with almost no comments) — sending a near-empty metrics dict to
  the LLM either produces a degenerate narrative or the LLM declines to
  answer. **Recommendation (fold into scope, <1 day):** if
  `classified_total` is below a small floor (reuse the existing
  `MIN_MONTH_VOLUME`-style named-constant convention from the master plan's
  Layer 1, e.g. `MIN_NARRATIVE_VOLUME`), skip the LLM call entirely and go
  straight to the deterministic fallback — cheaper and avoids an LLM call
  that's statistically meaningless anyway.
- **Qualitative-only claims (explicit decision needed, plan §7 already
  flags this as a boundary case for the guardrail unit tests):** a body
  string with zero numbers (e.g. "Sebagian besar komentar bersifat netral
  karena..." with no digit) cannot be validated by §5's numeric-membership
  check at all. **Decision needed at implementation time, recommended
  now:** a claim with zero numbers is not automatically safe — Decision
  #1's causal-connector allowlist still applies to it (a qualitative claim
  can still fabricate causation), but a purely descriptive claim with no
  numbers and no causal connector should PASS (the guardrail's numeric
  check has nothing to validate, and rejecting all non-numeric prose would
  make the narrative unnaturally choppy). This matches the plan's own §7
  test-table row ("body tanpa angka sama sekali... kasus batas yang perlu
  diputuskan eksplisit") — now decided explicitly rather than left open.
- **LLM refusal/empty response:** covered by Decision #7/#8 — routes
  through the same `LLMCallError`/retry/fallback path as any other
  malformed response.

### Section 5: Code Quality Review

- **Organization:** fits existing patterns (`sentiment/llm_classifier.py`
  precedent, `report/` module convention). No deviation without reason.
- **DRY:** the transport-level retry logic (connection/timeout retry, D2's
  reused pattern) and the content-level retry logic (D4's guardrail-reject
  retry) are two distinct concepts that happen to both be called "retry" —
  **naming risk flagged:** name them distinctly in code
  (`_call_llm_with_transport_retry()` vs. the outer
  `generate_narrative_with_guardrail()` that owns D4's single content
  retry) so a future reader doesn't conflate "retried the HTTP call twice"
  with "retried guardrail validation once." Not a functional bug, a
  naming/clarity fix — cheap, fold into implementation.
- **Over-engineering check:** none found — the module stays a thin
  client + validator, no premature abstraction (no plugin system, no
  factory-of-factories), consistent with Rules.md §11's explicit
  prohibition.
- **Under-engineering check:** F2 (Section 2) is the one under-engineering
  gap — the "never empty" promise needs the belt-and-suspenders top-level
  catch to actually hold.

### Section 6: Test Review

```
  NEW UX FLOWS:
    --narrative-review flag prints narrative + comparison numbers to terminal

  NEW DATA FLOWS:
    metrics dict subset -> LLM -> JSON -> citation guardrail -> cache/report
    (diagrammed in Section 1)

  NEW CODEPATHS:
    citation guardrail (numeric membership + Decision #1 causal-connector
    check + Section 4's zero-numbers boundary), retry-then-fallback state
    machine, hash-keyed cache read/write (Decision #4), narrative_review.json
    sidecar write (Decision #3)

  NEW BACKGROUND JOBS / ASYNC WORK:
    none (synchronous CLI call)

  NEW INTEGRATIONS / EXTERNAL CALLS:
    one new LLM call site (report/llm_insights.py)

  NEW ERROR/RESCUE PATHS:
    LLMCallError (reused), NarrativeGuardrailError (new) — both routed
    through D4's retry-then-fallback; F2's top-level catch (Section 2)
```

Coverage against the plan's own §7 table, confirmed adequate in shape, with
additions from this review folded in:
- Citation validator: exact match / rounding tolerance / no-numbers body
  (now explicitly decided, Section 4) / **+ new: numeric-membership-but-
  wrong-entity case (F1/Decision #1's binding fix)** / **+ new:
  causal-connector-present-but-unsupported case (Decision #1)**.
- Retry-then-fallback: as specced (+3), **+ new: second-attempt-itself-
  throws case (F2's top-level catch)**.
- Integration (mocked client): as specced, **+ new: empty-metrics /
  below-floor case skips the LLM call entirely (Section 4 recommendation)**.
- `--narrative-review`: as specced, **+ new: sidecar write failure doesn't
  block report write (Decision #3's OSError handling)**.
- Cache: **+ new (not in plan's original §7 table): hash-key stability
  test — same metrics subset serializes to the same key across two calls
  (0E hour-6+ finding); cache miss on any metrics change; cache never
  stores a rejected/fallback narrative as if accepted (Decision #4)**.
- Rules.md §9 mock requirement: confirmed this extends to
  `report/llm_insights.py`'s tests — no test may call the real LLM API
  (same rule as `sentiment/llm_classifier.py`).

Test pyramid: unit-heavy (validator, cache-key, retry state machine) with a
handful of mocked-client integration tests — matches the existing project's
pyramid shape (Rules.md §9's own split between "wajib test" core logic and
"cukup test bahwa field tersedia" for rendering).

Flakiness risk: none identified — no time/randomness/ordering dependency in
any new codepath; the cache hash must be float-formatting-stable (0E), which
is a determinism requirement, not a flakiness risk per se, but worth calling
out as the one place a naive implementation could accidentally introduce one
(e.g. hashing a dict without sorting keys first).

### Section 7: Performance Review

- **LLM call cost:** one call per report render (not per comment, not per
  video) — bounded, cheap relative to `themes_llm.py`'s Layer 2 call and
  far cheaper than the `sentiment/llm_classifier.py` path's per-comment
  volume (thousands of calls in a normal run per `TODOS.md`'s own numbers,
  ~4,398 LLM escalations in the referenced 2026-08 run).
- **Cache (Decision #4):** removes repeated LLM billing for CSS-only /
  template-only re-renders, which is the whole point — no performance
  concern, a performance win.
- **Memory:** metrics dict subset is KB-scale (§4 estimates 3-5 KB, plan's
  own number) — negligible.
- **No N+1, no new DB/index concerns** — this project has no database
  (Rules.md §1 confirms flat-file JSON pipeline).

No findings.

### Section 8: Observability & Debuggability Review

- **Logging (Decision #10):** guardrail accept at INFO, reject-then-retry
  or reject-then-fallback at WARNING, one structured line per generation
  attempt — matches Rules.md §7's existing level convention. **Gap folded
  into scope:** the log line should include which specific claim/number
  failed the guardrail (not just "guardrail rejected"), so a 3-weeks-later
  debugging session (Prime Directive 5's own bar) can reconstruct *why*
  without re-running the LLM. Cheap addition — the guardrail already has
  this information at reject time.
- **Metrics:** the accept/retry/fallback counts are exactly what
  `narrative_review.json` (Decision #3) already captures — no separate
  metrics pipeline needed; the sidecar doubles as the observability signal
  for "is the guardrail actually catching things or always passing
  trivially," which answers the plan's own §6 "quality signal" framing
  with a concrete artifact instead of an ephemeral terminal print.
- **Debuggability:** confirmed sufficient — sidecar + structured logs +
  the fact that the fallback narrative is mechanically reproducible
  (deterministic, same run's fresh metrics) together satisfy the "can I
  reconstruct what happened" bar.
- **Runbook:** the plan's §6 already writes the operational
  recommendation (use `--narrative-review` every run for 2 weeks, then
  sample) — sufficient; no missing runbook piece found.

### Section 9: Deployment & Rollout Review

- **No DB migration** (no database in this project).
- **No feature flag needed** — Decision #11: the existing "no `LLM_API_KEY`
  configured → fallback" behavior already IS the safe default/kill switch;
  a report with no LLM config renders identically to today's report before
  this plan ships. Deploying this plan changes behavior ONLY when
  `LLM_API_KEY`/`LLM_MODEL`/`LLM_BASE_URL` are already configured, which is
  an opt-in the operator already controls.
- **Rollback:** revert the commit; no data migration to undo (§8 of the
  plan confirms no `analysis_result.json` schema change). The sidecar file
  (`narrative_review.json`) and cache file (`narrative.json`) are both
  purely additive artifacts next to the input — deleting them or ignoring
  them after a rollback is harmless.
- **Deploy-time risk window:** none identified — this is a batch CLI tool,
  not a running service; there's no "old code and new code running
  simultaneously" window in the traditional sense.
- **Post-deploy verification:** run `generate_report` once with
  `--narrative-review` on a real dataset immediately after landing, confirm
  the banner correctly marks LLM-vs-fallback source, confirm the sidecar
  writes. Matches the plan's own §6 recommendation to use the flag for the
  first 2 weeks.

### Section 10: Long-Term Trajectory Review

- **Technical debt introduced:** minimal — the causal-connector allowlist
  (Decision #1) is a living list that will need occasional tuning as new
  Indonesian phrasing patterns show up; this is expected, ongoing
  maintenance, not accidental debt, and it fails closed (over-rejection
  triggers the safe fallback, never a false pass).
- **Path dependency:** none found that makes future changes harder — the
  module boundary (D2) and the Rules.md amendment (§3) actually make the
  *next* LLM-calling module easier to add correctly (the amended rule now
  states the pattern explicitly instead of leaving it to convention).
- **Reversibility:** 4/5 — a two-way door. Reverting the code is clean;
  the one one-way-ish element is the Rules.md §3 amendment itself, which
  is a documentation change, trivially revertible, but represents a
  precedent (this repo now has 2 sanctioned LLM call sites instead of 1) —
  future proposals for a 3rd site will point at this one as precedent,
  which is intended (D2's whole rationale) not a risk.
- **1-year question:** a new engineer reading this plan in 12 months should
  find it obvious — the module split, the guardrail, and the fallback are
  all named for what they do. The one thing that would NOT be obvious
  without this review is *why* the causal-connector allowlist exists
  (S-5's history spans two prior review cycles) — **recommendation:**
  the implementer should carry a one-line comment in the allowlist code
  pointing back to this plan file's User Challenges / Decision #1, so the
  "why" survives past this review's own text.
- **Platform potential:** the `narrative_review.json` sidecar pattern
  (Decision #3) is reusable for the next report-layer audit need (e.g. if
  Layer 2's theme generation ever needs its own spot-check trail) — noted
  as a nice byproduct, not claimed as new scope.

### Section 11: Design & UX Review — SKIPPED

No new UI/template scope in this plan (Decision #13). The narrative text
plugs into `report.html.j2`'s existing headline/risk/actions blocks
unchanged; `--narrative-review` is a terminal print, not a new screen.
Approach C's `[inferensi]` HTML tagging (deferred to TODOS.md, P2) is the
one piece of this feature area that WOULD need Section 11 depth — flagged
for whoever picks up that follow-up to run `/plan-design-review` at that
time, not now.

---

### "NOT in scope" section

- **D1** (500-sample BERT-vs-LLM ground-truth comparison) — separate
  ticket per plan §8, confirmed correctly out of blast radius (row 6,
  Decision Audit Trail).
- **D6** (diagnose 251 `llm_failed` comments, 5.71% of LLM traffic) —
  already P2 in `TODOS.md`, unrelated to the narrative layer's own
  correctness; confirmed out of scope.
- **TD-7** (theme-primary cross-tier rollup) — already P3 in `TODOS.md`,
  unrelated to this plan; confirmed out of scope.
- **Approach C — `[inferensi]` structural HTML tagging** — real value,
  deferred to `TODOS.md` (P2) because it's the only piece of this feature
  area that touches Layer 4 rendering, which this plan otherwise has zero
  reason to touch (0C-bis).
- **`analysis_result.json` schema changes** — none needed, confirmed per
  plan §8 and this review's Section 1.

### "What already exists" section

- `sentiment/llm_classifier.py` — client/retry pattern, reused (not
  rebuilt) by `llm_insights.py` per D2.
- `insights.py`'s `build_narrative()` / `_build_tier_narrative()` — the
  deterministic fallback target, unchanged, reused directly by D4.
- `generate_report.py`'s `_print_tier_sanity_check()` — the exact existing
  precedent for `--narrative-review`'s print-to-terminal pattern (§6).
- `errors.py`'s `LLMCallError` — reused for the new module's transport
  failures (Decision #8) rather than a duplicate exception class.
- The `LLM_API_KEY`/`LLM_MODEL`/`LLM_BASE_URL` env-var convention
  (`analyze.py`) — reused unchanged as the "is an LLM even configured"
  gate for the new module.
- `output/serializer.py`'s JSON-sidecar-write pattern — the shape reused
  for `narrative_review.json` (Decision #3) and the existing
  `themes.json`/`narrative.json` sidecar convention (master plan §3).

### Dream state delta

This plan, with the auto-accepted expansions folded in, moves the system
from "deterministic but rigid" toward the 12-month ideal of "LLM-assisted
narrative that is both numerically AND causally auditable, with a tracked
spot-check trail" — closing the gap almost entirely for the numeric and
causal-fabrication axes (Decisions #1-#3). What's left toward the full
12-month ideal: narrative quality scored against the D1 ground-truth
sample (deferred, separate ticket by design) and the `[inferensi]`
structural tagging for maximum reader transparency (deferred to TODOS.md,
P2). Both are correctly sequenced after this plan, not blocking it.

### Error & Rescue Registry

See Section 2's full table above. Summary: 5 distinct failure modes across
2 exception classes (1 reused, 1 new), all rescued through the same D4
retry-then-fallback state machine except the sidecar-write failure (rescued
independently, non-blocking) and F2's gap (now closed by the top-level
catch recommendation).

### Failure Modes Registry

```
  CODEPATH                          | FAILURE MODE                    | RESCUED? | TEST? | USER SEES?          | LOGGED?
  -----------------------------------|----------------------------------|----------|-------|----------------------|--------
  llm_insights transport call        | timeout / network error         | Y (D4)   | Y (§7)| Nothing (fallback)   | WARNING
  llm_insights transport call        | malformed JSON at wire level     | Y (D4)   | Y (§7)| Nothing (fallback)   | WARNING
  citation guardrail                 | number not in metrics dict       | Y (D4)   | Y (§7)| Nothing (fallback)   | WARNING (+ which claim, per Section 8)
  citation guardrail (F1/Decision #1)| number valid but wrong tier/entity| Y (D4)  | Y (new, Section 6) | Nothing (fallback) | WARNING
  citation guardrail (Decision #1)   | causal connector, unsupported    | Y (D4)   | Y (new, Section 6)| Nothing (fallback)   | WARNING
  llm_insights top-level (F2)        | any uncaught exception escapes   | Y (fix)  | Y (new, Section 6)| Nothing (fallback)   | ERROR
                                      | inner retry/guardrail logic      | (folded) |       |                      |
  narrative_review.json write        | disk/permission error            | Y        | Y (§7)| Nothing (report      | WARNING
  (Decision #3)                      |                                  |          |       | still writes)        |
  narrative cache read (Decision #4) | corrupt/stale/missing cache file | Y        | Y (new, Section 6)| Nothing (regenerates)| WARNING (corrupt only; miss is silent)
```

No row remains RESCUED=N / TEST=N / USER SEES=Silent — F2 was the one
CRITICAL GAP found and it is folded into scope with a concrete fix, not
left open.

### TODOS.md updates

Per the boil-the-ocean principle, everything within blast radius and under
a day of effort was folded directly into this plan's scope (Decisions
#1-#5) rather than deferred. Two items genuinely belong in `TODOS.md` as
follow-up work outside this plan's blast radius:

1. **`[inferensi]` structural HTML tagging (Approach C, 0C-bis).**
   What: extend the narrative JSON schema + `report.html.j2` to visually
   mark interpretive/causal sentences distinctly, on top of Decision #1's
   connector allowlist. Why: strongest long-term reader trust; the
   connector allowlist (shipping now) already fails closed and prevents
   fabrication, but doesn't make legitimate inference visually distinct
   from description. Pros: most transparent to the end reader. Cons: only
   piece of this feature area needing a template/CSS change; couples to
   Layer 4 unnecessarily if done now. Context: full alternative writeup in
   0C-bis Approach C above. Effort: M (human ~1-2 days / CC ~1-2h).
   Priority: P2. Depends on: this plan shipping first (needs the schema
   Decision #1 establishes as a base).
2. **Narrative quality scoring against the D1 ground-truth sample.** What:
   once the 500-sample labeled set (D1, separate ticket) exists, extend
   `compare_models.py` (or a sibling script) to periodically sample
   narrative outputs and score them the same way BERT-vs-LLM accuracy is
   scored today. Why: closes the last gap in the Dream State Delta above —
   right now narrative "quality" is measured only by the spot-check
   sidecar's pass/fail count, not by an actual accuracy metric against
   ground truth. Pros: turns "does the guardrail catch things" into "is the
   narrative actually good." Cons: depends entirely on D1 landing first,
   genuinely a separate, larger piece of work. Context: mirrors the
   existing BERT/LLM divergence measurement already in `TODOS.md`. Effort:
   L (human) / M (CC) — unestimated precisely pending D1. Priority: P3.
   Depends on: D1.

Auto-decided disposition (per this run's principles, no user available to
choose A/B/C): **A) Add both to TODOS.md** — both are real, both are
outside this plan's blast radius, neither blocks shipping this plan.

### Diagrams

1. System architecture — Section 1 above.
2. Data flow (with shadow paths) — Section 4 above.
3. State machine (retry-then-fallback) — embedded in Section 1's diagram
   (pass/reject/retry/fallback branch).
4. Error flow — Section 2's table (doubles as the error-flow map for this
   scale of feature; a dedicated ASCII flowchart would repeat the same
   information already tabulated).
5. Deployment sequence — Section 9 (no meaningful sequence diagram needed;
   this is a single-commit, no-migration, no-flag deploy).
6. Rollback flowchart — Section 9 ("revert commit; sidecar/cache files are
   inert leftovers, harmless to leave or delete").

### Stale Diagram Audit

No existing ASCII diagrams found in the files this plan touches
(`insights.py`, `generate_report.py`, `llm_classifier.py`, `errors.py`,
`Rules.md`) — none to audit for staleness.

---

## Implementation Tasks

Synthesized from this review's findings. Each task derives from a specific
finding above.

- [ ] **T1 (P1, human: ~4h / CC: ~30min)** — `llm_insights.py` — Implement
  citation guardrail with causal-connector allowlist (Decision #1) bound to
  tier/theme entity (F1), not flat numeric membership
  - Surfaced by: User Challenges + 0C-bis Approach B + Section 2 F1
  - Files: `sosmed_sentiment/report/llm_insights.py` (new)
  - Verify: unit tests per Section 6 (exact match, rounding tolerance,
    wrong-entity, unsupported-causal-connector, zero-numbers-pass cases)
- [ ] **T2 (P1, human: ~1h / CC: ~10min)** — `llm_insights.py` — Add
  top-level `except Exception` around the full generate-and-guardrail call
  that unconditionally falls back to `build_narrative()`, logged at ERROR
  - Surfaced by: Section 2 F2 (CRITICAL GAP)
  - Files: `sosmed_sentiment/report/llm_insights.py`
  - Verify: new test — second retry attempt itself raises an unexpected
    exception type, fallback still fires, report still writes
- [ ] **T3 (P2, human: ~1h / CC: ~10min)** — `llm_insights.py` +
  `generate_report.py` — Write `narrative_review.json` sidecar
  (generated_at, guardrail_status, reviewed_at/by nullable) alongside
  `--narrative-review`
  - Surfaced by: Decision #3, plan's own open question #3
  - Files: `sosmed_sentiment/report/llm_insights.py`,
    `sosmed_sentiment/cli/generate_report.py`
  - Verify: integration test — sidecar written on generate, updated on
    `--narrative-review`, write failure doesn't block report output
- [ ] **T4 (P2, human: ~1h / CC: ~10min)** — `llm_insights.py` — Hash-keyed
  narrative cache (Decision #4): sorted-key, fixed-float serialization of
  the metrics subset as cache key; cache only a guardrail-accepted
  narrative, never a rejected draft or fallback
  - Surfaced by: Decision #4, plan's own open question #4
  - Files: `sosmed_sentiment/report/llm_insights.py`
  - Verify: unit test for hash-key stability across two calls with
    identical metrics; cache-miss on any metrics change; fallback never
    cached as accepted
- [ ] **T5 (P2, human: ~30min / CC: ~5min)** — `insights.py` or
  `llm_insights.py` — Skip the LLM call entirely below a
  `MIN_NARRATIVE_VOLUME` floor, go straight to deterministic fallback
  - Surfaced by: Section 4 empty-metrics edge case
  - Files: `sosmed_sentiment/report/insights.py` or
    `sosmed_sentiment/report/llm_insights.py`
  - Verify: test with `classified_total` at/below the floor never calls
    the mocked LLM client
- [ ] **T6 (P3, human: ~15min / CC: ~5min)** — code — Name the
  transport-level retry and the content-level guardrail retry distinctly
  in code to avoid conflating them
  - Surfaced by: Section 5 DRY/naming note
  - Files: `sosmed_sentiment/report/llm_insights.py`
  - Verify: code review only, no behavioral test needed
- [ ] **T7 (P3, human: ~15min / CC: ~5min)** — `docs/TODOS.md` — Add the
  two deferred follow-ups (inferensi tagging, narrative quality scoring)
  - Surfaced by: TODOS.md updates section above
  - Files: `TODOS.md`
  - Verify: manual — entries present with the context above

---

### Completion Summary

```
+====================================================================+
|            MEGA PLAN REVIEW — COMPLETION SUMMARY                   |
+====================================================================+
| Mode selected        | SELECTIVE EXPANSION                          |
| System Audit         | 6 files read in full; Rules.md §3 conflict  |
|                       | confirmed literal; llm_classifier.py reuse  |
|                       | pattern confirmed viable                    |
| Step 0               | No git repo detected; proceeded without a   |
|                       | base branch (non-blocking, per fallback)    |
| Section 1  (Arch)    | 0 blocking issues (Decisions #1/#4/#5 shape |
|                       | the diagram, no gaps)                        |
| Section 2  (Errors)  | 9 error paths mapped, 1 CRITICAL GAP (F2,   |
|                       | folded into scope as T2), F1 folded as T1   |
| Section 3  (Security)| 1 low-likelihood/low-impact note (theme-    |
|                       | label injection path), 0 High severity      |
| Section 4  (Data/UX) | 3 edge cases mapped, 2 folded into scope    |
|                       | (T5 floor, explicit zero-numbers decision)  |
| Section 5  (Quality) | 1 naming/DRY note (T6), 0 structural issues |
| Section 6  (Tests)   | Diagram produced, 6 test additions folded   |
|                       | into scope (T1-T5's own verify lines)        |
| Section 7  (Perf)    | 0 issues found                              |
| Section 8  (Observ)  | 1 gap folded in (log which claim failed,    |
|                       | part of T1)                                  |
| Section 9  (Deploy)  | 0 risks flagged (no flag needed, Decision   |
|                       | #11)                                         |
| Section 10 (Future)  | Reversibility: 4/5, debt: 1 tracked item    |
|                       | (causal-connector list maintenance)          |
| Section 11 (Design)  | SKIPPED (no UI scope)                        |
+--------------------------------------------------------------------+
| NOT in scope         | written (5 items)                            |
| What already exists  | written (6 items)                            |
| Dream state delta    | written                                      |
| Error/rescue registry| 9 methods/codepaths, 1 CRITICAL GAP (closed  |
|                       | by T2, folded into scope)                    |
| Failure modes        | 8 total, 0 remaining CRITICAL GAPS after     |
|                       | folding T1/T2 into scope                     |
| TODOS.md updates     | 2 items proposed, both auto-accepted (A)     |
| Scope proposals      | 5 proposed (Decisions #1-#5), 5 accepted,    |
|                       | 1 deferred (inferensi tagging), 3 confirmed  |
|                       | out of scope (D1/D6/TD-7, unchanged)         |
| CEO plan             | not written (auto mode, no ~/.gstack/ CEO-   |
|                       | plans persistence step run — see note below) |
| Outside voice         | Codex N/A (unavailable); self-performed      |
|                       | Claude adversarial pass ran — see above      |
| Lake Score            | 9/9 findings folded into this plan's scope   |
|                       | (T1-T6) rather than deferred, except the 2   |
|                       | genuinely out-of-blast-radius TODOS items    |
| Diagrams produced     | 2 (architecture w/ state machine embedded,   |
|                       | data flow) + 4 sections noted as covered by  |
|                       | existing tables rather than redundant charts |
| Stale diagrams found  | 0 (none existed in touched files)            |
| Unresolved decisions  | 0 — all auto-decided per the 6 principles    |
|                       | and logged in the Decision Audit Trail       |
+====================================================================+
```

Note on the "CEO plan" row: this run's instructions route all Step 0D-POST
CEO-plan persistence, AskUserQuestion-driven ceremonies, and
`~/.gstack/`-based artifact writes through the same auto-decide substitution
as every other AskUserQuestion point — no ceremony was interactively run
(none available), so no separate `~/.gstack/projects/*/ceo-plans/*.md`
artifact was produced; this in-plan-file report is the durable record of
the same decisions instead.

### Unresolved Decisions

NO UNRESOLVED DECISIONS

## GSTACK REVIEW REPORT — DX Phase (2026-09-04)

Auto-mode run, mode fixed to **DX POLISH** per this run's instructions (no
scope expansion — every touchpoint the plan already introduces gets made
bulletproof). No interactive user available; every AskUserQuestion point the
skill would have fired is auto-decided per the 6 CEO-phase principles
(completeness, boil-the-ocean within blast radius, pragmatic, DRY,
explicit-over-clever, bias-to-action), with two DX-specific tie-breakers this
run also applied: "always optimize toward fewer steps" for getting-started
friction, and "problem+cause+fix" as a hard requirement for every error
message this plan introduces. Every decision is logged as rows 14-18 in the
Decision Audit Trail above. codex CLI is confirmed absent on this machine —
the "Codex DX voice" step is skipped entirely per this run's explicit
instruction; only the Claude DX subagent pass below ran, performed cold
(no knowledge of the CEO phase's findings) before being reconciled against
this file's existing content.

**Pre-review system audit (DX-specific, in addition to the CEO phase's
audit):** read `sosmed_sentiment/cli/generate_report.py` (181 lines, in
full), `sosmed_sentiment/cli/analyze.py` (400 lines, in full),
`sosmed_sentiment/errors.py` (in full), `README.md` lines 325-384 (the
`sosmed_sentiment/` install + "Running it" section — the actual
getting-started path this plan's persona already follows), and grepped
`docs/runbook.md` for existing LLM-config documentation. Confirmed: the
`--narrative-review` flag named in plan §6 is the ONLY narrative-related
flag the plan text itself specifies anywhere (`grep` across the full file
for `refresh-narrative`/`no-narrative` returns zero hits outside this
review's own additions) — `--refresh-narrative` and `--no-narrative`, named
in this run's task brief as flags to sanity-check for naming, do not
actually exist in the plan; CEO Decision #4's "the flag stays as an
explicit override" and CEO Decision #11's "no new feature flag" name a
concept without ever specifying it, which Pass 2/5 below treat as a real
gap, not a preexisting flag to critique.

### DX Scope Assessment

**Product type:** CLI Tool (internal ops tool — `python -m
sosmed_sentiment.cli.generate_report`). No API/SDK/platform/public-docs
surface. This plan adds one flag and one internal module to an existing
two-command CLI suite (`analyze`, `generate_report`) that already has a
working, documented getting-started path (`README.md:337-384`).

**Developer persona:** the internal operator who already runs this CLI
suite — NOT a first-time external adopter. They have already installed the
~600MB venv (`README.md:339-343`), already have (or deliberately don't have)
`LLM_API_KEY`/`LLM_MODEL`/`LLM_BASE_URL` set from the `analyze` step, and
already know the two-command `analyze` -> `generate_report` shape. This
plan's DX surface is entirely "does the next release of a tool I already
use behave predictably," not "can a stranger get to hello world." Every
score and recommendation below is calibrated to that persona, not a
Stripe-tier public-SDK bar.

**Developer journey map (9 stages):**

| # | Stage | Developer does | Evidence | Friction found |
|---|-------|-----------------|----------|-----------------|
| 1 | Discover | Reads `README.md:331-336` ("Two more CLIs on top of the same scraped data") — already knows this CLI exists, this plan adds nothing new to discover | `README.md:331-336` | None — persona already past this stage |
| 2 | Install | No new dependency (D2 reuses the vendored `openai` SDK, CEO Section 3) | Plan §8, CEO Section 3 | None |
| 3 | Configure | `.env` already carries `LLM_API_KEY`/`LLM_MODEL`/`LLM_BASE_URL` if the operator uses LLM sentiment escalation in `analyze` (`README.md:365-367`, `docs/runbook.md:15-22`) — this plan reuses the exact same three vars for a second, unrelated concern | `README.md:365-367` | **Found (Pass 5):** reusing the same env vars couples two independent on/off decisions — see Decision #14 |
| 4 | Hello World (this feature) | Adds `--narrative-review` to a command they already run (`generate_report --input ... --output ...`) | Plan §6 | **Found (Pass 1):** no console signal distinguishes "flag had no effect because no LLM configured" from "flag worked, narrative was accepted" |
| 5 | Real usage | Runs `--narrative-review` on every real report for the first 2 weeks per plan §6's recommended cadence | Plan §6 | **Found (Pass 4):** cadence is promised in prose but no task writes it into `docs/runbook.md` — see Decision #17 |
| 6 | Debug (LLM/guardrail failure) | Guardrail rejects, or transport fails — operator sees "nothing" per CEO Section 2's table (fallback is silent to the report itself) | CEO Section 2 | **Found (Pass 3):** WARNING/ERROR log message *content* isn't specified to the same problem+cause+fix bar `analyze.py` already sets — see Decision #18 |
| 7 | Verify/trust (spot-check) | Reads the `--narrative-review` sentence dump, cross-checks numbers against the tables in the same report | Plan §6, D5 | **Found (Pass 3):** dump doesn't lead with narrative-source, so trust-calibration requires correlating with log output above it — see Decision #16 |
| 8 | Escape hatch | Wants deterministic-only narrative without losing LLM sentiment escalation | Plan §9 (Decision #11) | **Found (Pass 5):** no scoped kill switch exists — see Decision #14 |
| 9 | Upgrade (later) | Rules.md §3 amendment (this plan) sets precedent for a 3rd LLM call site later; cache/sidecar formats are additive, revert-safe | CEO Section 10 | None — CEO phase already covered reversibility (4/5) |

**TTHW rating:** the *mechanical* time-to-hello-world is Champion tier
(< 2 min) — the persona is already running this exact command; adding one
flag costs zero incremental setup. But mechanical TTHW is the wrong metric
for this persona (per the Product Type note above, this isn't a stranger's
first run). The metric that matters is **time-to-trusted-signal**: how long
until the operator can tell, without reading source code, whether the
narrative they're looking at is LLM-generated-and-verified or a silent
fallback. Current: **not reliably achievable from `--narrative-review`'s
output alone** (Pass 3 finding) — the operator must also read scrollback
log lines to know the narrative's provenance. Target, after Decision #16's
fix: **same < 2 min mechanical time, with the trust signal on line 1 of the
`--narrative-review` output.**

### Dual Voices — Independent Challenge

| Voice | Ran? | Verdict |
|---|---|---|
| Claude DX subagent (self-performed, cold read of the plan before reconciling with CEO-phase content) | Yes | Issues found — folded into Passes 1/2/3/4/5 below and Decisions #14-#18 |
| Codex | N/A (codex unavailable) | N/A (codex unavailable) |

**Overall dual-voice status: [subagent-only]** — codex CLI confirmed absent
on this machine; per this run's explicit instruction, no fallback subagent
dispatch was spawned either — this review performed the independent pass
directly instead.

**Cross-model tension:** none — no second voice ran. The findings below are
this review's own, not a synthesis of disagreement.

### Developer Empathy Narrative (first-person)

I'm the operator who runs this pipeline monthly. I already know the drill:
`analyze --month 2026-08 --threshold-config config/thresholds.yaml`, wait
twenty-some minutes, then `generate_report --input runs/2026-08/analysis_result.json
--output runs/2026-08/report.html`. Today someone tells me there's a new
flag, `--narrative-review`, that lets me sanity-check the AI-written parts
of the report before I forward it. I add it to the command I already know
by heart. It runs. HTML gets written like always, then a wall of sentences
scrolls past — headline, risk, actions, one block per tier. Some numbers
next to each one. Fine, I start reading, cross-checking net sentiment
figures against the tables further up in the terminal log.

Halfway through I stop and ask myself: am I reading what the LLM actually
wrote, or did this silently fall back to the old deterministic narrative
because something failed twice in a row? Nothing in front of me answers
that. I'd have to scroll back up past the sanity-check block to look for a
WARNING or ERROR line, and even if I find one, I'm not sure it tells me
*which* sentence it was about. I decide it probably worked — the sentences
read fluently, not like the old templated style — but I'm guessing, not
verifying, which defeats the entire point of a spot-check flag.

Later I want to try a smaller prompt tweak and see whether the narrative
cache picks up the new metrics. I look for a flag to force a fresh
generation. There isn't one documented anywhere — I'd have to go delete a
`narrative.json` file by hand and hope I found the right one. And when a
teammate asks "can we just turn this LLM stuff off for narratives but keep
using it for sentiment classification," I don't have an answer — unsetting
`LLM_API_KEY` turns off both, and I need the sentiment escalation.

### Pass 1: Getting Started Experience (Zero Friction) — 7/10

**Evidence recall:** persona is already at the CLI (Journey stage 4);
mechanical TTHW is near-zero — this is the correct starting point for the
score, not a fresh-install benchmark.

- README/runbook precedent for "LLM not configured" is excellent elsewhere:
  `analyze.py`'s own console line
  ("LLM_MODEL/LLM_API_KEY belum diisi - komentar dengan confidence model
  rendah TIDAK dieskalasi...", `cli/analyze.py:182-186`) tells the operator
  exactly what didn't happen and why, unprompted.
- **Finding:** the plan does not specify an equivalent line for
  `--narrative-review` when `LLM_API_KEY` is absent. Per plan §2 Error
  table, this case is explicitly "not an error... skip straight to
  fallback, log at INFO not ERROR" — but INFO-level and silent-to-the-flag
  are different things. An operator who passes `--narrative-review`
  specifically to check the LLM's work, on a machine where the env vars
  happen to be unset, gets a normal-looking sentence dump with no signal
  that the flag effectively did nothing this run.
- Fix folded into scope: Decision #16 (narrative-source banner) directly
  closes this — `no-llm-configured` becomes one of the three banner states,
  making the empty-LLM-config case visible on line 1 instead of buried at
  INFO level.

A 10 here (for THIS persona) is: the exact same one-flag addition to a
command they already know, PLUS the banner from Decision #16, so the first
line of new output after adding the flag answers "did this even try to use
the LLM" without the operator needing to know log levels exist.

### Pass 2: API/CLI/SDK Design (Usable + Useful) — 6/10

**Evidence recall:** existing flags on `generate_report`/`analyze`:
`--input`, `--output`, `--template`, `--comments-json`,
`--total-population-videos`, `--month`, `--fresh`, `--exclude-config`,
`--stopwords-config`, `--threshold-config` — all lowercase kebab-case,
`click.option`, one clear default policy stated in `help=`.

- `--narrative-review` fits this pattern cleanly: kebab-case, one word pair,
  reads correctly against `--comments-json`/`--exclude-config`'s
  noun-modifier shape. No finding here.
- **Finding:** the plan references (CEO Decisions #4, #11) a
  cache-bypass concept and a possible narrative-only kill switch without
  ever naming or speccing either as an actual flag anywhere in the plan
  body — confirmed via full-file grep (see pre-review audit above). This
  is a genuine naming-consistency gap this task was specifically asked to
  check: `analyze.py` already established `--fresh` (cli/analyze.py:332-337)
  as this suite's verb for "ignore the cache, redo the work." A
  hypothetical `--refresh-narrative` would introduce a second verb for the
  identical concept inside the same CLI suite, breaking the grammar an
  operator has already learned. **Fix (Decision #15):** name it
  `--fresh-narrative` if/when it's built, matching `--fresh` exactly.
- **Finding:** no scoped kill switch flag exists (elaborated in Pass 5,
  Decision #14) — this is as much a CLI-completeness gap as an
  escape-hatch gap.

A 10 here is: `--narrative-review`, `--fresh-narrative`, and `--no-narrative`
all present, all named to match the suite's existing verbs
(`--fresh`→`--fresh-narrative`, boolean-flag style already used by
`--fresh` itself→`--no-narrative`), documented together in one `--help`
neighborhood.

### Pass 3: Error Messages & Debugging (Fight Uncertainty) — 6/10

**Evidence recall:** traced 3 error paths this plan introduces, evaluated
against problem+cause+fix (the hard requirement for this run) and this
codebase's own Tier-1-equivalent precedent (`analyze.py`'s LLM-not-configured
and model-load-failure messages, which already state what happened, why,
and what to do).

1. **LLM transport failure / malformed JSON** (`LLMCallError`, reused,
   Decision #8). Behavior is fully specified (retry once, fall back, WARNING
   log) — but the plan never specifies the *message text*. Compare to
   `analyze.py`'s model-load-failure path, which is concrete and actionable.
   **Problem+cause+fix status: cause and fix implied by the retry/fallback
   design, but not written down as a message template** — Decision #18
   folds this in.
2. **Citation guardrail reject** (`NarrativeGuardrailError`, new). CEO
   Section 8 already improved this — the WARNING log should include which
   specific claim/number failed. Good: that's problem+cause. Still missing:
   the fix half for the *operator reading `--narrative-review` output*
   specifically (as opposed to reading raw logs) — they need the failing
   claim surfaced where they're already looking, not only in scrollback.
   Decision #16's banner is a partial fix; the full claim detail staying in
   the log (not duplicated into the dump) is a reasonable line to draw —
   noted, not re-litigated.
3. **F2's uncaught-exception path** (already closed by CEO Decision/T2)
   — ERROR log, unconditional fallback. Once T2 lands this is a clean
   problem+cause+fix path: "something in narrative generation broke
   unexpectedly, here's the exception, the report still has a narrative
   (deterministic fallback)." No further DX finding.

A 10 here is: every one of the above three paths has a literal message
string in the plan (or at minimum a one-line template like `analyze.py`'s),
not just a log LEVEL and a rescue ACTION — so the implementer isn't
inventing the wording from scratch, and the operator's first encounter with
each failure mode reads like `analyze.py`'s existing bar, not a generic
"guardrail rejected" stub.

### Pass 4: Documentation & Learning (Findable + Learn by Doing) — 6/10

**Evidence recall:** `README.md:362-378` is the exact, current,
copy-pasteable "Running it" section this persona already uses — it already
documents the `.env` LLM config pattern this plan reuses. `docs/runbook.md`
exists and already carries operational LLM-config notes
(`docs/runbook.md:15-22`).

- Both docs are real, current, and precisely where this plan's new flag and
  its recommended cadence belong.
- **Finding:** confirmed against the CEO phase's own Implementation Tasks
  (T1-T7) — none of them touch `README.md` or `docs/runbook.md`. Plan §6
  states the 2-week-then-sample cadence "tertulis di runbook" (written in
  runbook) as if it's a given, but nothing in the plan's actual task list
  makes that true. This is exactly the kind of promise-with-no-task gap
  that boils away silently. Decision #17 folds in the task.
- Findability of the flag itself once documented: high — `README.md`'s
  existing structure (one code block per command) makes a one-line addition
  trivial to spot for an operator who already reads that section before
  every run.

A 10 here is: the `--narrative-review` line added directly into
`README.md:375-378`'s existing code block (not a separate section), plus a
short "when to use it" paragraph in `docs/runbook.md` next to the existing
`.env`/LLM notes — zero new documentation *surface*, reuse of the existing
one.

### Pass 5: Upgrade & Migration Path (Credible) — 5/10

**Evidence recall:** CEO Section 9 already covers rollback (revert commit,
no migration, additive artifacts) well — that part is not re-litigated.
This pass focuses on the escape-hatch question this task specifically
asked about: can an operator disable this whole feature and get the old
deterministic-only behavior?

- **Finding (the main one this pass surfaces):** per CEO Decision #11, the
  answer today is "unset `LLM_API_KEY`" — but that env var is shared with
  `analyze`'s LLM sentiment escalation (`README.md:365-367`,
  `cli/analyze.py:169-186`). An operator who trusts LLM-assisted sentiment
  classification (already shipped, already validated per plan §1) but does
  NOT yet trust LLM-generated narrative prose (the exact risk this whole
  plan's guardrail exists to manage) has no way to keep one and disable the
  other. That's a real, foreseeable operational split, not a hypothetical
  — it is the same distinction plan §1 itself draws between "already
  validated" (deterministic narrative, 399 tests) and "new, riskier"
  (LLM narrative). Decision #14 (a scoped `--no-narrative` flag,
  independent of the env var) closes this without reopening Decision #11's
  actual point, which was "don't add a second env-var-driven kill switch
  for the same failure mode" — a flag is not a second env var, it's a
  narrower override for a narrower decision.
- Migration/deprecation warnings: N/A, nothing being deprecated by this
  plan.

A 10 here is: `--no-narrative` ships alongside `--narrative-review`, so the
escape hatch exists on day one rather than being retrofitted after the
first operator asks for it in production.

### Pass 6: Developer Environment & Tooling (Valuable + Accessible) — 8/10

Examined: no CI/CD references to `generate_report` or `analyze` exist
anywhere in the repo (no `.github/workflows`, no CI config referencing
these CLIs) — this is a manually-run internal batch tool, consistent with
`README.md`'s framing throughout, and this plan doesn't change that.
Examined: cross-platform concerns — plan introduces no new OS-specific
dependency (reuses the already-vendored `openai` SDK, CEO Section 3).
Examined: testability — plan §7 and CEO Section 6 already require mocked
LLM clients per `Rules.md` §9's existing convention, extended correctly to
the new module. Nothing flagged beyond what CEO Section 6 already covers.

### Pass 7: Community & Ecosystem (Findable + Desirable) — 7/10

Internal tool, no external community — most of this dimension's usual
checks (OSS license, plugin ecosystem, pricing transparency) are not
applicable and are weighted accordingly, per this run's persona (internal
operator, not an external adopter). Examined: `TODOS.md` and `CLAUDE.md`
function as this repo's "where do I ask/track things" mechanism — adequate
for a solo/internal shop, consistent with how the rest of the codebase
already operates. Nothing new flagged; the plan's own TODOS.md updates
(CEO phase, "TODOS.md updates" section) correctly extend this existing
pattern rather than inventing a new one.

### Pass 8: DX Measurement & Feedback Loops (Implement + Refine) — 7/10

- `narrative_review.json` (Decision #3, CEO phase) already carries
  `reviewed_at`/`reviewed_by` (nullable) fields — this functions as a
  lightweight, already-in-scope measurement of whether the D5 spot-check
  cadence (every run for 2 weeks, then 1-in-5) is actually being followed,
  without needing a separate instrumentation pass. Examined for gaps: none
  found — this sidecar answers "is the runbook cadence being followed" as
  a byproduct of its existing schema, once Decision #17's runbook task
  makes the cadence discoverable in the first place.
- No TTHW-specific instrumentation exists or is planned, but per Pass 1's
  TTHW discussion, mechanical TTHW isn't the metric that matters for this
  persona — nothing further to flag here.

### DX Scorecard

```
+====================================================================+
|              DX PLAN REVIEW — SCORECARD                             |
+====================================================================+
| Dimension            | Score  | Prior  | Trend  |
|----------------------|--------|--------|--------|
| Getting Started      |  7/10  |   —    |   —    |
| API/CLI/SDK          |  6/10  |   —    |   —    |
| Error Messages       |  6/10  |   —    |   —    |
| Documentation        |  6/10  |   —    |   —    |
| Upgrade Path         |  5/10  |   —    |   —    |
| Dev Environment      |  8/10  |   —    |   —    |
| Community            |  7/10  |   —    |   —    |
| DX Measurement       |  7/10  |   —    |   —    |
+--------------------------------------------------------------------+
| TTHW (mechanical)    | < 2 min  | —     |   —    |
| TTHW (trusted signal)| not reliably achievable pre-fix | — | — |
| Competitive Rank     | N/A — internal ops tool, not benchmarked against public SDKs |
| Magical Moment       | N/A — internal ops tool, no adoption-funnel magical moment applies |
| Product Type         | CLI Tool (internal)                          |
| Mode                 | DX POLISH                                    |
| Overall DX           | 6.5/10 |   —    |   —    |
+====================================================================+
| DX PRINCIPLE COVERAGE                                               |
| Zero Friction      | covered (persona already past install/config) |
| Learn by Doing     | covered (README code block is copy-paste-real)|
| Fight Uncertainty  | gap — closed by Decisions #16, #18             |
| Opinionated + Escape Hatches | gap — closed by Decision #14         |
| Code in Context    | covered (reuses real .env/CLI conventions)     |
| Magical Moments    | N/A for this product type                      |
+====================================================================+
```

No dimension is below 5 — nothing here is a blocking DX gap, consistent
with DX POLISH mode's remit (make every touchpoint bulletproof, not gate
shipping). The two dimensions at 5-6 (Upgrade Path, Error Messages, API/CLI
Design, Documentation) are all closed by Decisions #14-#18, which are all
<1 day, in-blast-radius fixes folded directly into this plan per the
boil-the-ocean principle — none deferred to TODOS.md.

### DX Implementation Checklist

```
DX IMPLEMENTATION CHECKLIST (calibrated to internal-CLI persona, not public SDK)
============================
[x] Time to hello world < target — persona already at the CLI; one flag added to a known command
[x] Installation is one command — no new dependency (D2 reuses vendored openai SDK)
[x] First run produces meaningful output — HTML + sanity-check block, existing pattern reused
[ ] Magical moment delivered — N/A, no adoption funnel for an internal ops tool
[ ] Every error message has: problem + cause + fix + docs link — behavior specified, message TEXT is not (Decision #18)
[x] API/CLI naming is guessable without docs — `--narrative-review` matches existing kebab-case flag grammar
[ ] Every implied flag has a name that matches the suite's existing verbs — `--fresh-narrative`/`--no-narrative` don't exist yet (Decisions #14, #15)
[ ] Docs have copy-paste examples that actually work — README/runbook not yet updated for this flag (Decision #17)
[x] Examples show real use cases — existing README/runbook already model this well; this plan should extend, not replace, that pattern
[x] Upgrade path documented with migration guide — CEO Section 9 covers rollback fully (revert commit, no migration)
[ ] Escape hatch exists independent of shared config — `LLM_API_KEY` currently gates two unrelated features at once (Decision #14)
[ ] TypeScript types included — N/A, Python project
[x] Works without special CI configuration — no CI exists for these CLIs today; plan doesn't need to add any
[x] Free tier / no credit card — N/A, internal tool, no billing surface
[ ] Changelog exists and is maintained — no CHANGELOG.md found in repo root; out of this plan's blast radius, not folded in
[ ] Search works in documentation — README/runbook are single flat files, findable by grep; no search tooling exists or is expected for a repo this size
[x] Community channel exists and is monitored — TODOS.md/CLAUDE.md function as this repo's tracking mechanism, consistent with its existing scale
```

### TTHW Assessment

**Current:** mechanical TTHW is Champion tier (< 2 min) for this persona —
they already run the underlying command; `--narrative-review` is a one-flag
addition with no new install, no new config beyond what `analyze`'s LLM
escalation already requires. Time-to-*trusted-signal* (can the operator
tell whether they're looking at LLM-verified or silently-fallback-produced
narrative) is currently not reliably achievable from the flag's own output
— it requires correlating terminal output with scrollback log lines whose
message content isn't yet specified (Pass 3).

**Target:** keep the < 2 min mechanical TTHW (no regression — this plan
should never make the existing two-command flow slower or add a new
required step), and make time-to-trusted-signal equal to
"read line 1 of `--narrative-review`'s output" via Decision #16's
narrative-source banner. Both targets are achievable inside this plan's
existing blast radius; neither requires new infrastructure.

### "NOT in scope" section

- Public-SDK-tier DX investment (interactive playground, magical-moment
  funnel, competitive TTHW benchmarking against Stripe/Vercel) — wrong bar
  for an internal ops CLI with an already-onboarded, captive persona; noted
  explicitly rather than silently applying an inapplicable rubric.
- CHANGELOG.md — none exists in the repo today; adding a changelog process
  is a repo-wide convention question, not something this feature-scoped
  plan should introduce unilaterally.
- Full competitive DX benchmark (Step 0C's usual output) — skipped per this
  run's explicit "internal ops tool, not a public API/SDK product"
  framing; the Community/Ecosystem pass (7/10) already notes most of that
  dimension is N/A for the same reason.

### "What already exists" section

- `README.md:325-384` — the current, working, copy-paste-real getting
  started path for both `analyze` and `generate_report`, including the
  `.env`/LLM-config convention this plan reuses. This is the doc surface
  Decision #17 extends, not replaces.
- `docs/runbook.md:15-22` — existing LLM-config operational notes, the
  natural home for the spot-check cadence plan §6 already promises.
- `cli/analyze.py:169-186`'s "LLM_MODEL/LLM_API_KEY belum diisi..." message
  and its model-load-failure message — this codebase's own existing
  problem+cause+fix bar, which Decision #18 asks the new module to match
  rather than reinvent independently.
- `cli/analyze.py:332-337`'s `--fresh` flag — the existing naming
  precedent Decision #15 reuses for the narrative cache-bypass flag.
- `cli/generate_report.py:51-70`'s `_print_tier_sanity_check()` — already
  the correct precedent for `--narrative-review`'s print-to-terminal shape
  (confirmed again in this phase, consistent with the CEO phase's finding).

### Dream state delta

Nothing new beyond the CEO phase's Dream State Mapping (0C) — this phase's
findings are refinements to the DX surface of the same trajectory (a
narrative system that's both numerically/causally verifiable AND legible
to the operator verifying it in real time), not a new destination.

### TODOS.md updates

No new TODOS.md items from this phase — every finding (Decisions #14-#18)
is <1 day and inside this plan's existing blast radius, so per the
boil-the-ocean principle all five are folded directly into plan scope
rather than deferred. The CEO phase's two existing TODOS.md items
(`[inferensi]` tagging, narrative quality scoring against D1) are
unchanged and not re-litigated here.

### Implementation Tasks (DX phase additions)

- [ ] **T8 (P2, human: ~30min / CC: ~5min)** — `cli/generate_report.py` —
  Add `--no-narrative` boolean flag that skips `llm_insights.py` entirely
  - Surfaced by: Pass 5 (Decision #14)
  - Files: `sosmed_sentiment/cli/generate_report.py`
  - Verify: test — flag set skips the LLM call even when `LLM_API_KEY` is
    configured; report still renders with deterministic narrative
- [ ] **T9 (P3, human: ~15min / CC: ~5min)** — `cli/generate_report.py` —
  Name the narrative-cache-bypass flag `--fresh-narrative` (matching
  `analyze.py`'s `--fresh`), when Decision #4's cache-bypass mechanism is
  implemented
  - Surfaced by: Pass 2 (Decision #15)
  - Files: `sosmed_sentiment/cli/generate_report.py`
  - Verify: code review only — naming convention, no independent test
- [ ] **T10 (P1, human: ~1h / CC: ~10min)** — `report/llm_insights.py` +
  `cli/generate_report.py` — Print a one-line narrative-source banner
  (`llm-accepted` / `llm-retried-then-fallback` / `no-llm-configured`) as
  the first line of `--narrative-review`'s output
  - Surfaced by: Pass 1, Pass 3 (Decision #16)
  - Files: `sosmed_sentiment/report/llm_insights.py`,
    `sosmed_sentiment/cli/generate_report.py`
  - Verify: integration test — each of the 3 states produces the matching
    banner line before the sentence dump
- [ ] **T11 (P2, human: ~30min / CC: ~10min)** — `README.md`,
  `docs/runbook.md` — Document `--narrative-review` (and `--no-narrative`,
  once T8 lands) in the existing "Running it" code block, and write the
  2-week/1-in-5 spot-check cadence into `docs/runbook.md`
  - Surfaced by: Pass 4 (Decision #17)
  - Files: `README.md` (~line 375-378), `docs/runbook.md`
  - Verify: manual — instructions present, cadence matches plan §6
- [ ] **T12 (P2, human: ~1h / CC: ~15min)** — `report/llm_insights.py` —
  Write literal problem+cause+fix message templates for the transport-
  failure and guardrail-reject log lines, matching `analyze.py`'s existing
  message-quality bar
  - Surfaced by: Pass 3 (Decision #18)
  - Files: `sosmed_sentiment/report/llm_insights.py`
  - Verify: code review against `analyze.py:182-186`'s message shape as
    the reference bar; no new test needed beyond existing log-level tests

### Unresolved Decisions

NO UNRESOLVED DECISIONS

## GSTACK REVIEW REPORT — Eng Phase (2026-09-04)

Auto-mode run, no interactive user available. codex CLI confirmed absent on
this machine — the "Codex eng voice" step is skipped entirely per this run's
instruction. Only the Claude eng subagent pass ran: an independent senior-
engineer read of the amended plan (architecture, edge cases, test coverage,
security/input-validation, hidden complexity), performed cold — with no
inherited agreement with the CEO or DX phases' reasoning, though their prior
findings and Decisions #1-#18 were read in full first, since the plan is now
theirs to build on, not to re-litigate from zero. Every AskUserQuestion this
skill would have fired was auto-decided per the 6 principles (completeness,
boil-the-ocean within blast radius, pragmatic, DRY, explicit-over-clever —
dominant for this phase alongside pragmatic — bias-to-action); every
decision is logged as rows 19-26 in the Decision Audit Trail above.

**Pre-review system audit (Eng-specific, code read in full before forming
any opinion):** `sosmed_sentiment/report/insights.py` (938 lines — all of
`build_narrative()`, `_build_tier_deep_dive()`, `_build_tier_narrative()`,
and every metrics-dict-producing helper `build_metrics()` assembles),
`sosmed_sentiment/sentiment/llm_classifier.py` (85 lines — the exact
client/retry pattern D2 says `llm_insights.py` should mirror),
`sosmed_sentiment/cli/generate_report.py` (181 lines), `sosmed_sentiment/errors.py`
(41 lines), `docs/Rules.md` §§2-3, 7-9 (in full), the master plan's Layer 3
section (`docs/plans/2026-09-02-insight-driven-report.md` lines 90-165),
`sosmed_sentiment/report/charts.py` and `html_builder.py`'s Jinja environment
setup (confirming autoescape configuration — Decision #25), the full
`report.html.j2` narrative-rendering blocks (lines 275-401), and the test
files `tests/sosmed_sentiment/sentiment/test_llm_classifier.py`,
`tests/sosmed_sentiment/report/test_insights.py`,
`tests/sosmed_sentiment/report/test_report_integration.py`, and
`tests/sosmed_sentiment/cli/test_generate_report.py` for the mocking and
fixture conventions this plan's new tests must match.

### Dual Voices — Independent Challenge

| Voice | Ran? | Verdict |
|---|---|---|
| Claude eng subagent (self-performed, independent senior-engineer pass — architecture/coupling, edge cases, test coverage, security/input-validation, hidden complexity) | Yes | Issues found — folded into Sections 1-4 below and Decisions #19-#26 |
| Codex | N/A (codex unavailable) | N/A (codex unavailable) |

**Overall dual-voice status: [subagent-only]** — codex CLI confirmed absent
on this machine; no fallback subagent dispatch was spawned either, per this
run's explicit instruction to perform the independent pass directly.

**Eng Dual Voices consensus table** (Codex column N/A throughout, per this
run's setup):

| # | Dimension | Claude eng verdict | Codex | Consensus |
|---|---|---|---|---|
| 1 | Architecture soundness / coupling | Sound. Clean second-call-site pattern (D2), no new coupling between `report/` and `sentiment/` beyond the shared client-construction *shape* (duplication-by-necessity, matches CEO Section 1). One real addition this phase makes: `llm_insights.py` should own an explicit request timeout distinct from `llm_classifier.py`'s untimed pattern (Decision #24) — the two call sites are NOT interchangeable in blast radius (per-comment isolation vs. single-call-gates-the-whole-render) even though they share client-construction code | N/A (codex unavailable) | Sound, with one addition (Decision #24) — [subagent-only] |
| 2 | Edge cases (empty metrics, non-JSON, wrong-type JSON, timeout, all-zero tier) | 4 of 5 named edge cases already closed by CEO/DX (Sections 2, 4, T2, T5). One genuinely open: LLM returns **syntactically valid JSON with wrong field TYPES** (not just missing keys) — under-specified by CEO Section 2's error table, closed here by Decision #19/T13 | N/A (codex unavailable) | Gap found and closed — [subagent-only] |
| 3 | Retry-then-fallback race conditions | None found in the traditional sense — this is a synchronous, single-threaded, single-process CLI batch tool (confirmed: no `asyncio`, no threading, no multiprocessing anywhere in `report/` or `cli/`); D4's retry-then-fallback state machine has no concurrent caller. The one real "race"-shaped risk is an INTERRUPTED sidecar/cache write (Ctrl-C, disk full) leaving a corrupt file for the *next* run to read — closed by Decision #26 (atomic write) | N/A (codex unavailable) | No race condition found; one adjacent durability gap closed — [subagent-only] |
| 4 | Test coverage gaps | 39 codepaths/branches mapped against the plan's own scope (full diagram in the test-plan artifact, see Section 3 below); 35 already adequately specified, 4 genuine gaps found and folded into scope as T13-T16 | N/A (codex unavailable) | 4 gaps found, all folded into scope — [subagent-only] |
| 5 | Security / input-validation (LLM output → HTML, XSS risk) | Verified, not assumed: `html_builder.py:493`'s `select_autoescape(['html', 'j2'])` already escapes both narrative blocks (`report.html.j2` lines 282, 389, 396 — no `\|safe` on `item.title`/`item.body` anywhere in the template). The LLM-authored narrative text renders through the exact same unescaped-by-default path the existing deterministic narrative already uses. No new escaping code needed — but no test currently PROVES this, so a template edit could silently regress it (closed by Decision #25/T19) | N/A (codex unavailable) | Confirmed safe; one regression test added to prevent silent regression — [subagent-only] |
| 6 | Hidden complexity | None found beyond what CEO Section 5 already flagged (transport-retry vs. content-retry naming, T6). The plan stays a thin client + validator, matching Rules.md §11's explicit prohibition on premature abstraction; no additional factory/plugin-shaped complexity found in this pass | N/A (codex unavailable) | Clean — [subagent-only] |

**Consensus: 6/6** — every dimension resolves to a closed finding (fixed via
a folded-in task) or a confirmed-clean verdict; nothing left open or
contested. No dimension required a tie-break since only one voice ran.

### Section 1: Architecture Review

```
                    analysis_result.json (input, unchanged)
                              │
                    insights.py (Layer 1, deterministic - UNCHANGED)
                    build_metrics() ─┬─> build_narrative()
                                     │   _build_tier_narrative()
                                     │   (fallback target, D4)
                                     │
                    metrics dict (full)
                              │
                    generate_report.py (CLI orchestration only,
                    Rules.md §3's 2nd clause - no business logic added)
                              │
                    ┌─────────┴──────────────────────────┐
                    │                                      │
          metrics-dict SUBSET                     html_builder.build_report()
          (Decision #5: aggregates +               (existing render path,
           theme labels, NO raw quotes)             UNCHANGED - reads
                    │                                metrics['narrative'])
          report/llm_insights.py  (NEW - D2)                │
                    │                                        │
          ┌─────────┴──────────────┐                         │
          │  reuses CLIENT/RETRY    │                         │
          │  SHAPE from:            │                         │
          │  sentiment/             │                         │
          │  llm_classifier.py      │                         │
          │  (_client(), MAX_RETRIES,│                        │
          │   RETRY_BACKOFF_SECONDS,│                         │
          │   LLMCallError) - NOT   │                         │
          │  imported/called across │                         │
          │  the module boundary,   │                         │
          │  pattern mirrored only  │                         │
          └─────────┬───────────────┘                        │
                    │                                          │
          LLM call -> strict JSON                             │
          {headline, risk, actions}                           │
                    │                                          │
          [NEW - Decision #19/T13]                             │
          JSON-shape/type validation                           │
          (isinstance checks - FIRST                           │
          guardrail step, before                                │
          citation parsing)                                    │
                    │                                          │
          citation guardrail (§5 + F1                          │
          entity-binding + Decision #1                          │
          causal-connector allowlist)                          │
                    │                                          │
      ┌─────pass────┴────reject (D4)─────┐                     │
      │                                    │                    │
  accept, cache (Decision #4,       retry generate 1x            │
  hash-keyed, post-guardrail only,        │                     │
  ATOMIC write - Decision #26)    ┌───pass─┴──reject──┐          │
      │                            │                    │        │
      │                      accept, cache        fallback to    │
      │                            │              build_narrative()/│
      │                            │              _build_tier_narrative()│
      │                            │              (Layer 1, this run's│
      │                            │               fresh metrics - D4)│
      │                            │                    │        │
      │            [F2 belt-and-suspenders: top-level  │        │
      │             except Exception around the WHOLE  │        │
      │             generate-and-guardrail call, T2]   │        │
      └──────────────┬─────────────┴───────────────────┘        │
                     │                                            │
           metrics['narrative'] overwritten with the             │
           LLM (accepted) or fallback (deterministic)             │
           result before html_builder.build_report() runs  ──────┘
                     │
           report.html  +  narrative.json (cache, Decision #4)
                     +  narrative_review.json (audit sidecar,
                        Decision #3, updated by --narrative-review)
```

- **Component boundaries:** confirmed clean by direct code read, not just
  by the plan's own description — `llm_classifier.py` is 85 lines with zero
  imports from `report/`, and `insights.py` is 938 lines with zero imports
  from `sentiment/` or `openai`. `llm_insights.py` sits entirely inside
  `report/`, reached only from `generate_report.py` (CLI orchestration) and
  never from `insights.py` itself — `insights.py`'s own docstring already
  states "Layers 2/3's LLM half... out of scope for this module by design,"
  confirmed still true: this plan does not touch `insights.py` except to
  READ its metrics-dict shape and CALL `build_narrative()`/
  `_build_tier_narrative()` as the fallback target, matching CEO Section 1
  exactly.
- **Coupling concerns:** one genuine new one, not previously named — the
  point where `metrics['narrative']` gets overwritten (LLM-accepted or
  fallback) must happen BEFORE `html_builder.build_report()` reads it, and
  that ordering lives entirely in `generate_report.py`'s orchestration,
  meaning the new call site's position relative to the existing
  `build_report()` call is itself part of the contract, not just "call it
  somewhere in `run_generate_report()`." Recommend the implementer add a
  one-line comment at that call site pointing back to this diagram, since a
  future edit that reorders these two calls would silently ship a report
  whose narrative was never LLM-attempted at all, with no test failure
  unless T10's banner-state test (already scoped) happens to catch it.
- **Scaling:** confirmed via code read — `build_metrics()` is a single pass
  building one dict; `llm_insights.py` receives that dict's subset once per
  `generate_report` invocation, not once per video/comment. 10x/100x comment
  volume changes `build_metrics()`'s own O(n) cost (unchanged by this plan),
  not the LLM call count. Matches CEO Section 1's finding exactly.
- **Single point of failure:** the LLM endpoint — mitigated by D4, further
  hardened by Decision #24's explicit timeout (an unbounded hang was the one
  failure mode D4's retry/fallback machinery cannot rescue from, since it
  never gets control back until the call itself resolves).
- **Rollback posture:** confirmed trivial by code read — `build_narrative()`
  requires no network access (verified: no import of `openai`, `requests`,
  or any network library anywhere in `insights.py`), so reverting the
  `llm_insights.py` commit is a clean, no-migration rollback exactly as CEO
  Section 1 states.

No blocking architecture findings. Decision #24 (explicit timeout) is the
one genuine addition this phase makes to CEO Section 1's diagram.

### Section 2: Code Quality Review

- **Guardrail validation ordering (Decision #19/T13, CRITICAL-adjacent):**
  the plan's own `NarrativeGuardrailError` (CEO Section 2's error table)
  is triggered by "valid JSON, wrong shape (missing headline/risk/actions
  keys)" — but "wrong shape" as written covers only MISSING keys, not
  PRESENT-but-wrong-TYPE keys. A `parsed['headline']` that is a dict
  instead of a list, or a `body` field that is an int, will raise a raw
  `TypeError`/`AttributeError` inside the citation-parsing regex step
  itself — a real Python exception, not the guardrail's own controlled
  reject. F2's top-level `except Exception` catch (T2) DOES rescue this
  case (nothing crashes past `llm_insights.py`'s boundary), but it does so
  by logging ERROR and treating a routine malformed-LLM-response as
  "something is badly broken" — the wrong signal for a 3-weeks-later
  debugging session (CEO Section 8's own "can I reconstruct why" bar).
  **Fix (folded into scope, T13):** validate JSON shape/types as the FIRST
  step inside the guardrail, before any citation-parsing regex runs,
  raising `NarrativeGuardrailError` (WARNING-level, retry-then-fallback,
  same rescue outcome — just the correct log level and the correct
  exception class for a routine case).
- **Timeout gap (Decision #24):** `llm_classifier.py`'s `_client()`
  constructs `OpenAI(api_key=api_key, base_url=base_url or None)` with no
  `timeout` argument — confirmed by direct read, line 32. That's an
  accepted, out-of-blast-radius risk for `llm_classifier.py` itself (each
  hang is isolated to one comment by the existing per-comment try/except
  in the caller `sentiment.hybrid`, not built in this plan). Mirroring that
  SAME pattern verbatim into `llm_insights.py` would be a regression, not
  reuse — `llm_insights.py`'s one call gates the ENTIRE report render with
  no isolation boundary above it. **Fix (folded into scope, T18):**
  `llm_insights.py`'s `_client()` should pass an explicit `timeout=` (30s
  is a reasonable default — long enough for a real narrative-generation
  completion, short enough that a hung local endpoint doesn't block a
  human operator running `generate_report` interactively).
- **DRY / naming (confirms CEO Section 5's T6, no new finding):** agree
  with the transport-retry vs. content-retry naming split; nothing to add.
- **Over/under-engineering:** confirmed no over-engineering (thin client +
  validator, no factory/plugin abstraction — matches Rules.md §11). The one
  under-engineering item this phase adds beyond CEO's F2 is Decision #19
  above; everything else in D4's state machine is appropriately scoped for
  a ~150-comment-scale internal tool (Decision #9's own framing).
- **XSS / narrative-text escaping (verified, not a gap):** direct read of
  `sosmed_sentiment/report/html_builder.py:493` confirms
  `Environment(..., autoescape=select_autoescape(['html', 'j2']))`, and a
  direct read of `report.html.j2` lines 282, 389, and 396 confirms
  `{{ item.title }}` / `{{ item.body }}` render with no `\|safe` filter in
  any of the three narrative loops (headline/tier/risk/actions). LLM-
  authored narrative text flows through the exact same auto-escaping path
  the existing 100%-deterministic narrative already uses — **no new
  escaping code is required by this plan.** This is worth stating
  explicitly in the plan (not left implicit) precisely because the plan
  introduces the first LLM-authored text that reaches this render path;
  `charts.py`'s `Markup`-wrapped SVG builders are a structurally different,
  pre-existing case (deliberately raw HTML, escaped internally per-field via
  `markupsafe.escape()`) and must never be treated as precedent for
  wrapping narrative text in `Markup` — doing so WOULD reopen an XSS surface
  this plan currently has none of. Flagged here so no future edit "fixes"
  narrative rendering into looking like `charts.py`'s pattern by mistake.
  Regression test folded into scope as T19 (Decision #25).

### Section 3: Test Review

Full codepath × test-type diagram, fixture design notes, and the itemized
gap list live in the required separate artifact file (per this run's task
instructions — written to disk, not inline, so a 39-row matrix doesn't
bloat this plan file):

**Artifact:**
`C:\Users\asets\.gstack\projects\tiktok-comment-scrapper\romysaputrasihananda-feat-sentiment-model-cascade-and-report-review-test-plan-20260904-044718.md`

Built by reading the actual existing test files first (not from memory):
`tests/sosmed_sentiment/sentiment/test_llm_classifier.py` (the
`@patch('...OpenAI')` + `fake_response()` mocking pattern to mirror),
`tests/sosmed_sentiment/report/test_insights.py` (the `_comment(...)`
small-hand-built-fixture convention, matches Decision Audit Trail row #9),
and `tests/sosmed_sentiment/cli/test_generate_report.py` (`CliRunner`,
`write_result()`/`valid_result()` helpers) — every new test this plan needs
is specified to match these exact conventions, not a new testing style.

**Summary (full detail in the artifact):**
- **39 codepaths/branches** identified across every new module, flag, cache,
  and sidecar this amended plan introduces.
- **35 already have an adequate, specified test** somewhere in plan §7 /
  CEO Section 6 / DX Implementation Tasks.
- **4 genuine gaps found in this Eng pass**, all folded into scope (none
  deferred — all <1 day, all inside this plan's existing blast radius,
  matching the boil-the-ocean principle CEO/DX already applied
  consistently):
  1. JSON-valid-but-wrong-types guardrail path — **T13** (also a Section 2
     code-quality finding, not just a test gap).
  2. Numeric-collision-across-entities test for F1's binding fix — **T14**.
  3. `--no-narrative` + `--narrative-review` combined-flag behavior,
     currently undefined — **T15**.
  4. Message-content assertions for T12's log lines (T12's own verify line
     said "code review only," under-testing a content requirement) — **T16**.
- Two further Eng-phase test additions came from Section 1/2 findings, not
  the matrix itself: a cache/sidecar atomic-write test (**T17**, Decision
  #26) and an autoescape regression test (**T19**, Decision #25).

Rules.md §9's mock requirement (no test may call a real LLM API) is
confirmed to extend cleanly to every new test named above — all of them
mock `OpenAI` exactly as `test_llm_classifier.py` already does.

Test pyramid shape: unit-heavy (validator, cache-key, retry state machine,
JSON-shape validation) with mocked-client/CliRunner integration tests for
the CLI-flag and sidecar-write surface — matches the existing project's
pyramid (Rules.md §9's own "wajib test core logic / cukup test field
availability for rendering" split), confirmed consistent, not just assumed.

Flakiness risk: none newly introduced. The one determinism-sensitive spot
(cache-key hashing, already flagged by CEO 0E) needs sorted-key + fixed-
float serialization — a correctness requirement, not a flakiness risk per
se, and already scoped as part of T4.

### Section 4: Performance Review

- **LLM call cost:** confirmed via code read of `insights.py`'s
  `build_metrics()` — one call per `generate_report` invocation, entirely
  decoupled from comment/video volume (matches CEO Section 7 exactly; no
  new finding).
- **Timeout's performance implication (ties to Decision #24):** an explicit
  30s timeout bounds the WORST case added latency for a report render when
  the LLM is unreachable/hung — without it, `generate_report` has no
  contractual upper bound on how long a single run can take, which matters
  for an operator running this interactively and expecting the existing
  "generate a report" latency profile (dominated by `build_metrics()`'s
  O(n) pass over comments, not network I/O) to still hold.
- **Cache (Decision #4):** confirmed a net performance win, no new finding
  beyond CEO Section 7 — repeated CSS/template-only re-renders skip the LLM
  call entirely once a hash-keyed cache entry exists.
- **Memory:** confirmed negligible — the metrics-dict subset sent to the
  LLM (Decision #5: aggregates + theme labels, no raw quotes) is KB-scale;
  no new data structure this plan introduces scales with comment count.
- **Sidecar I/O (Decision #26):** atomic write (tmp + `os.replace()`) adds
  one extra filesystem operation per sidecar write — negligible at this
  project's scale (a handful of KB-sized JSON files per report render, not
  a hot path).
- **No N+1, no DB/index concerns** — confirmed, this project has no
  database (Rules.md §1).

No performance findings beyond the timeout note above, which is really a
robustness finding with a performance-shaped consequence (an unbounded
worst case), not a throughput/cost concern.

### "NOT in scope" section

Unchanged from CEO/DX phases (D1, D6, TD-7, Approach C's `[inferensi]`
tagging, `analysis_result.json` schema changes, public-SDK-tier DX
investment, CHANGELOG.md) — confirmed still correctly out of blast radius
after this phase's own architecture/edge-case/test/security pass; nothing
in this phase's findings reopens any of them. One addition:

- **A general-purpose request-timeout/circuit-breaker library or config
  system** — out of scope. Decision #24 is a single hardcoded `timeout=`
  value on one client construction call, not a new configurable timeout
  system; matches Rules.md §11's "don't add abstraction for what isn't
  asked for" and this plan's own "thin client + validator" shape.

### "What already exists" section

Unchanged from CEO/DX phases, confirmed again by this phase's own direct
code reads (not re-copied from memory):
- `sentiment/llm_classifier.py`'s client/retry SHAPE (not code) — mirrored,
  not imported, by `llm_insights.py` (confirmed via direct read: 85 lines,
  zero cross-imports with `report/`).
- `insights.py`'s `build_narrative()`/`_build_tier_narrative()` — confirmed
  network-free (no `openai`/`requests` import anywhere in the 938-line
  file), the fallback target D4 requires.
- `generate_report.py:51-70`'s `_print_tier_sanity_check()` — confirmed the
  exact precedent for `--narrative-review`'s print-to-terminal shape.
- `errors.py`'s `LLMCallError` — confirmed reused, not duplicated
  (Decision #8).
- `html_builder.py:493`'s Jinja `autoescape` configuration — confirmed
  (this phase's own new verification, Section 2/Decision #25) to already
  cover the new LLM-authored narrative text with no additional code needed.
- `tests/sosmed_sentiment/sentiment/test_llm_classifier.py`,
  `tests/sosmed_sentiment/report/test_insights.py`,
  `tests/sosmed_sentiment/cli/test_generate_report.py` — the three test
  files whose conventions every new test in T13-T19 must match, confirmed
  by direct read (Section 3).

### Failure Modes Registry (Eng phase — extends CEO Section 2's table)

```
  CODEPATH                              | FAILURE MODE                          | RESCUED? | TEST?         | USER SEES?           | LOGGED?   | CRITICAL?
  ----------------------------------------|----------------------------------------|----------|---------------|-----------------------|-----------|----------
  llm_insights JSON-shape validation      | headline/risk/actions present but     | Y (T13,  | Y (T13's own  | Nothing (fallback)    | WARNING   | Was a
  (NEW, Decision #19)                     | wrong type (dict not list, non-string | fixed)   | verify line)  |                       |           | silent
                                           | body, etc.) - previously fell through |          |               |                       |           | ERROR-
                                           | to F2's ERROR-level catch instead     |          |               |                       |           | level
                                           |                                        |          |               |                       |           | miscat-
                                           |                                        |          |               |                       |           | egoriz-
                                           |                                        |          |               |                       |           | ation
  citation guardrail entity-binding (F1)  | numeric collision across two entities | Y (D4)   | Y (T14, NEW)  | Nothing (fallback)    | WARNING   | No -
  under a tie (NEW test, Decision #20)    | (both cite the same number) - was     |          |               |                       |           | binding
                                           | untested whether binding resolves by  |          |               |                       |           | logic
                                           | nearest-label or silently first-match |          |               |                       |           | already
                                           |                                        |          |               |                       |           | specced
  llm_insights client call                | request hangs indefinitely (no       | Y (T18,  | Y (implicit - | Report render blocks  | N/A       | Yes -
  (NEW, Decision #24)                     | timeout previously set, unlike        | fixed)   | timeout       | indefinitely, no      | until     | genuine
                                           | llm_classifier.py's ACCEPTED but      |          | bounds the    | rescue path runs      | timeout   | new gap,
                                           | isolated risk there)                  |          | retry/        | until the call itself | fires     | now
                                           |                                        |          | fallback      | resolves               |           | closed
                                           |                                        |          | machinery's   |                        |           |
                                           |                                        |          | own tests)    |                        |           |
  narrative.json / narrative_review.json  | write interrupted mid-write (Ctrl-C,  | Y (T17,  | Y (T17, NEW)  | Next run treats it as | WARNING   | No -
  sidecar write (Decision #26)            | disk full) leaves a corrupt/partial   | fixed)   |               | corrupt/cache-miss    | (on next  | moder-
                                           | file for the NEXT run to read          |          |               | (Decision #4's own    | read)     | ate,
                                           |                                        |          |               | existing rescue)      |           | closed
  report.html.j2 narrative rendering      | a future template edit adds `\|safe`  | N/A -    | Y (T19, NEW)  | Nothing today - would | N/A       | No -
  (confirmed safe today, Decision #25)    | to the narrative blocks, reopening    | this is  |               | be an XSS regression  |           | preven-
                                           | the escaping this phase confirmed     | a        |               | if it ever happened   |           | tive
                                           | already exists                        | regres-  |               |                       |           | test,
                                           |                                        | sion     |               |                       |           | not a
                                           |                                        | test,    |               |                       |           | live
                                           |                                        | not a    |               |                       |           | gap
                                           |                                        | rescue   |               |                       |           |
```

No row is RESCUED=N with no fix — every genuinely new failure mode this
Eng phase found is closed by a folded-in task (T13, T14, T17, T18, T19).
The one CRITICAL-adjacent item (JSON-shape validation, row 1) is
CRITICAL-adjacent rather than CRITICAL outright: F2's existing
belt-and-suspenders catch (CEO's own fix) already prevents it from
crashing the run or violating D4's "narrative section is never empty"
guarantee — the gap was in OBSERVABILITY (wrong log level, wrong exception
class for a routine case), not in user-facing correctness or crash safety.
CEO Section 2's own F2 remains the true CRITICAL finding of this review
chain; this phase found nothing of that severity.

### TODOS.md updates

No new TODOS.md items from this phase's own findings — every gap found
(Decisions #19-#26) is <1 day and inside this plan's existing blast radius,
so per the boil-the-ocean principle all eight are folded directly into
scope (T13-T19) rather than deferred, consistent with how CEO and DX phases
already handled their own in-blast-radius findings. This phase's
contribution to `docs/TODOS.md` is instead the CONSOLIDATION of every item
already deferred across all three phases (CEO's `[inferensi]` tagging and
narrative-quality-scoring items, unchanged) into one new dated section —
see the separate `docs/TODOS.md` edit accompanying this review (below the
Completion Summary).

### Implementation Tasks (Eng phase additions)

- [ ] **T13 (P1, human: ~1h / CC: ~15min)** — `report/llm_insights.py` —
  Add JSON-shape/type validation (isinstance checks on headline/risk/
  actions structure) as the FIRST guardrail step, raising
  `NarrativeGuardrailError` directly rather than relying on F2's top-level
  catch
  - Surfaced by: Section 2 (CRITICAL-adjacent), Decision #19, test-plan
    artifact row 6
  - Files: `sosmed_sentiment/report/llm_insights.py`
  - Verify: new test — JSON with `headline` as a dict, an item missing
    `body`, and a `body` that's an int, all raise `NarrativeGuardrailError`
    (WARNING, retry-then-fallback), never fall through to F2's ERROR path
- [ ] **T14 (P2, human: ~30min / CC: ~10min)** — tests —
  Numeric-collision-across-entities fixture test proving F1's entity-
  binding resolves by nearest-label, not first-match
  - Surfaced by: Decision #20, test-plan artifact row 14
  - Files: `tests/sosmed_sentiment/report/test_llm_insights.py` (new)
  - Verify: fixture with two entities sharing an identical cited number;
    assert the validator binds correctly to the claim's actual subject
- [ ] **T15 (P2, human: ~30min / CC: ~10min)** — `cli/generate_report.py` —
  Define and test `--no-narrative` + `--narrative-review` combined-flag
  behavior explicitly
  - Surfaced by: Decision #21, test-plan artifact row 35
  - Files: `sosmed_sentiment/cli/generate_report.py`
  - Verify: new test — both flags passed together produce a defined,
    documented banner/output state, not whatever click's flag precedence
    happens to produce
- [ ] **T16 (P3, human: ~20min / CC: ~10min)** — tests —
  Add message-content substring assertions to T12's transport-failure/
  guardrail-reject log-line tests (T12 itself specified "code review only")
  - Surfaced by: Decision #22, test-plan artifact row 38
  - Files: `tests/sosmed_sentiment/report/test_llm_insights.py`
  - Verify: `caplog`-based assertion that the WARNING/ERROR message text
    names what happened, why, and what to do — not just the log level
- [ ] **T17 (P2, human: ~30min / CC: ~10min)** — `report/llm_insights.py` —
  Atomic write (tmp file + `os.replace()`) for `narrative.json` and
  `narrative_review.json` sidecar writes
  - Surfaced by: Decision #26
  - Files: `sosmed_sentiment/report/llm_insights.py`,
    `sosmed_sentiment/cli/generate_report.py`
  - Verify: new test — a write interrupted partway (simulated) never
    leaves a file the next run's cache-read would treat as valid-but-wrong;
    normal writes are byte-identical to the pre-atomic-write behavior
- [ ] **T18 (P1, human: ~15min / CC: ~5min)** — `report/llm_insights.py` —
  Explicit request timeout (e.g. 30s) on the `OpenAI()` client construction
  - Surfaced by: Section 1/2, Decision #24
  - Files: `sosmed_sentiment/report/llm_insights.py`
  - Verify: code review (asserting a mocked client was constructed with a
    `timeout=` kwarg is sufficient; a real hang is not worth testing against
    wall-clock time in the suite)
- [ ] **T19 (P3, human: ~20min / CC: ~10min)** — tests —
  Regression test confirming a narrative body containing HTML metacharacters
  renders escaped in `report.html` (confirms Section 2's verified-safe
  finding stays true after future template edits)
  - Surfaced by: Section 2, Decision #25
  - Files: `tests/sosmed_sentiment/report/test_report_integration.py`
  - Verify: metrics fixture with `<script>`-bearing narrative body text
    (LLM-sourced or fallback, doesn't matter which), assert the rendered
    HTML contains the escaped entity, not the raw tag
- [ ] **T20 (P3, human: ~10min / CC: ~5min)** — `MIN_NARRATIVE_VOLUME`
  constant — Define at value `30` in `llm_insights.py`, matching T5's
  existing skip-the-LLM-call floor
  - Surfaced by: Decision #23
  - Files: `sosmed_sentiment/report/llm_insights.py`
  - Verify: T5's existing test (CEO Section 4) parametrized at the
    concrete value 30, not left as an unspecified placeholder

### Completion Summary

```
+====================================================================+
|            ENG PLAN REVIEW — COMPLETION SUMMARY                    |
+====================================================================+
| Mode                  | Eng-phase full-depth review (per this      |
|                        | run's autoplan instructions)               |
| System Audit           | 9 files + 3 test files + template read in |
|                        | full before forming any opinion             |
| Dual Voices            | Claude eng subagent only (codex N/A);      |
|                        | 6/6 dimensions resolved, no contested item |
| Section 1  (Arch)     | 0 blocking issues; 1 addition (explicit    |
|                        | timeout, Decision #24) to CEO's diagram     |
| Section 2  (Quality)  | 1 CRITICAL-adjacent finding (JSON-shape    |
|                        | validation, T13), 1 durability gap closed  |
|                        | (timeout, T18), XSS risk VERIFIED SAFE      |
|                        | (not assumed) with regression test added    |
| Section 3  (Tests)    | 39-codepath diagram in separate artifact;  |
|                        | 35/39 already adequate, 4 new gaps found,  |
|                        | all folded into scope (T13, T14, T15, T16) |
| Section 4  (Perf)     | 0 throughput/cost findings; 1 robustness-  |
|                        | shaped latency-bound finding (timeout)      |
| Failure Modes         | 5 new rows added to CEO's registry, all    |
|                        | rescued/closed, 0 remaining unrescued gaps |
| TODOS.md updates      | 0 new items from this phase's own findings |
|                        | (all folded into scope); consolidated ALL  |
|                        | three phases' deferred items into one new   |
|                        | TODOS.md section (see below)                |
| Test-plan artifact     | Written: romysaputrasihananda-feat-        |
|                        | sentiment-model-cascade-and-report-review- |
|                        | test-plan-20260904-044718.md                |
| Scope proposals        | 8 found (Decisions #19-#26), 8 accepted,   |
|                        | 0 deferred, 0 rejected                      |
| Unresolved decisions   | 0 — all auto-decided per the 6 principles  |
|                        | and logged in the Decision Audit Trail      |
+====================================================================+
```

### Unresolved Decisions

NO UNRESOLVED DECISIONS
