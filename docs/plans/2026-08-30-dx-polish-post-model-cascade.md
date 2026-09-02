<!-- /autoplan restore point: /c/Users/asets/.gstack/projects/romysaputrasihananda-tiktok-comment-scrapper/master-autoplan-restore-20260830-225602.md -->

# Rencana — DX Polish Pasca Model Cascade (Approach C)

| | |
|---|---|
| **Versi** | 0.1 (draf, masuk `/autoplan`) |
| **Tanggal** | 2026-08-30 |
| **Branch** | `master` |
| **Sumber** | `docs/plans/2026-08-30-model-cascade-implementation.md` §6 ("24 temuan DX tetap berlaku") + verifikasi ulang terhadap kode SAAT INI (model cascade sudah diimplementasi dan model sudah di-swap dari w11wo ke mdhugol pasca gate G-08 gagal) |

## Konteks

Sesi sebelumnya (`docs/plans/2026-08-30-model-cascade-implementation.md`) diimplementasi
penuh: `sentiment/model_classifier.py`, `hybrid.py` rewrite, `serializer.py` breakdown fix,
`errors.py` (`ModelLoadError`/`ModelClassifyError`), kalibrasi threshold nyata terhadap
200 komentar berlabel Tahap B (`config/thresholds.yaml`, 0.95, 81.9% akurasi). 328 test
lulus. README, Architecture.md, Schema.md, PRD.md sudah diupdate.

24 temuan DX dari `/plan-devex-review` sesi sebelumnya (`tasks-devex-review-20260830-164423.jsonl`,
12 task P1/P2 tercatat di sana) ditulis terhadap rencana **lexicon InSet** yang sudah
DIBATALKAN oleh pivot ke model. Task list itu sudah stale — sebagian item (D7, D8, D12)
mereferensikan file/konsep yang tidak lagi ada (`build_lexicon.py`, `lexicon_version`,
`--no-negation`). Plan ini memverifikasi ULANG tiap temuan terhadap kode SAAT INI sebelum
menugaskannya, bukan menyalin daftar lama mentah-mentah.

## Verifikasi Ulang Tiap Temuan Lama (terhadap kode saat ini, bukan asumsi)

| # | Temuan lama | Status terverifikasi hari ini |
|---|---|---|
| D1 | README gak nyebut `sosmed_sentiment` | **SUDAH BERES** (sesi ini) — bagian "## Sentiment analysis" ada di `README.md` |
| D2 | Nol input kecil, satu-satunya input di `runs/` (gitignored) | **MASIH BERLAKU** — `runs/2026-08/comments.json` gitignored, gak ada fixture kecil ter-commit |
| D3 | `.env.example` + `config/thresholds.yaml` gak ada | **SUDAH BERES** (sesi ini) — keduanya ada, `thresholds.yaml` di-commit dengan reasoning kalibrasi |
| D4 | Artefak pelabelan manual ditulis ke `runs/` (gitignored) | **MASIH BERLAKU** — `scripts/generate_labeling_sample.py` nulis ke `runs/2026-08/labeling_sample.xlsx`, sama masalahnya kayak temuan lama |
| D5 | `comment_id` 19 digit rusak di Excel | **SUDAH DITANGANI SEBAGIAN** — `generate_labeling_sample.py` sudah maksa `comment_id` jadi text (format `@` + prefix `'`), tapi levelnya masih ad-hoc, belum ada validasi "tolak file yang keburu rusak" |
| D6 | Codebook pelabelan gak ada, label ke-4 `tidak_yakin` gak ada | **MASIH BERLAKU** — `sentiment_label` cuma 3 opsi dropdown (positif/negatif/netral), gak ada dokumen definisi tiap label buat konsistensi antar-sesi labeling |
| D7 | `lexicon_version` implisit → gagal diam-diam | **OBSOLETE** — `lexicon_version` sudah gak dipakai, diganti `model_version` yang eksplisit di `model_classifier.py` (`MODEL_NAME`/`MODEL_REVISION` sebagai konstanta, bukan implisit) |
| D8 | `--no-negation` + `--lexicon-config` starter escape hatch | **OBSOLETE** — bug negasi itu spesifik ke arsitektur lexicon (`score_tokens()` gak konsumsi kata negasi), sudah gak relevan sejak model classifier dipakai (model handle negasi bawaan, terverifikasi G-07 2/2) |
| D9 | `--month`, `--output` opsional, command lengkap dicetak | **MASIH BERLAKU** — `cli/analyze.py` gak punya `--month`, `--output` tetap wajib, gak ada dry-run |
| D10 | `--price-input`/`--price-output` + `--escalation-budget` | **MASIH BERLAKU, TAPI BERGANTUNG FR-09** — FR-09 (dry-run cost estimator) BELUM PERNAH diimplementasi sama sekali di kode saat ini (diverifikasi: `cli/analyze.py` gak punya flag `--dry-run`) — ini bukan "polish", ini fitur yang belum dibangun |
| D11 | `--force`, partial merge, `--validate` buat kalibrasi | **SEBAGIAN BERUBAH KONTEKS** — `generate_labeling_sample.py` pakai SEED TETAP (`20260830`), jadi re-run generate ulang 200 baris SAMA PERSIS ke `labeling_sample.xlsx` (bukan `_labeled.xlsx` yang user isi manual) — risiko re-run overwrite label manual JAUH lebih kecil dari rencana lama, tapi belum ada guard eksplisit kalau user re-run generator setelah mulai labeling |
| D12 | Progress log pas `build_lexicon` diam 4 menit | **OBSOLETE (file gak ada), TAPI ANALOG BARU SUDAH ADA** — `model_classifier.py:load_model()` sudah log baris "unduhan pertama kali ~500MB..." sebelum proses mulai; **belum ada progress log per-batch** pas `analyze.py` jalanin ribuan komentar (bisa diam 8-24 menit tanpa sinyal) |

## Item Baru (ditemukan verifikasi ulang, gak ada di daftar lama)

- **FR-09 dry-run TIDAK PERNAH dibangun.** `PRD.md` menyebutnya sebagai FR wajib, tapi
  `cli/analyze.py` gak punya jalur dry-run sama sekali — analis gak bisa lihat estimasi
  biaya LLM sebelum run beneran. Ini gap fungsional, bukan cuma DX polish.
- **Gak ada progress indicator selama batch run.** Proyeksi waktu sekarang (stemming
  ~15-16 menit + model inferensi ~8,5 menit = ~24 menit) berjalan tanpa log per-N-komentar
  — analis liat layar diam lama, resiko dikira macet (kejadian ini persis yang bikin
  D12/DX F12 ada di plan lama).
- **`runs/2026-08/analysis_result.json` end-to-end belum pernah dijalankan penuh** dengan
  model+kalibrasi baru (percobaan sebelumnya timeout 10 menit karena background job, bukan
  karena gagal) — belum ada bukti run lengkap sukses di data asli.

## Yang Harus Dikerjakan (draft awal, akan direview)

1. Commit `docs/examples/comments.sample.json` (~20 komentar representatif dari data asli,
   di-strip PII berlebih kalau perlu) supaya ada input kecil buat testing manual/onboarding.
2. Pindah output `generate_labeling_sample.py` ke path yang di-track git (bukan `runs/`),
   ATAU dokumentasikan eksplisit kenapa TIDAK dipindah (lihat pertimbangan privasi di bawah).
3. Tulis `docs/calibration/codebook.md`: definisi operasional tiap label (`positif`,
   `negatif`, `netral`) + opsi ke-4 `tidak_yakin` buat kasus analis sendiri ragu, supaya
   kalibrasi ulang di masa depan konsisten walau dikerjakan orang lain.
4. `cli/analyze.py`: tambah `--month` (baca `runs/YYYY-MM/comments.json` tanpa perlu ketik
   path lengkap), `--dry-run` (FR-09 — estimasi jumlah komentar yang bakal dieskalasi +
   estimasi biaya LLM dari distribusi confidence model, TANPA panggilan API sungguhan),
   cetak command lengkap yang dipakai di ringkasan akhir run.
5. Progress log per-N-komentar (mis. tiap 500) selama loop preprocessing+klasifikasi di
   `cli/analyze.py`, supaya run 24 menit gak diam total.
6. Guard di `generate_labeling_sample.py`: refuse overwrite kalau file target udah ada,
   kasih pesan jelas (`--force` buat sengaja timpa).
7. Jalankan `analyze.py` penuh end-to-end di `runs/2026-08/comments.json` (6.158 komentar)
   sampai selesai (di-background, bukan foreground yang bisa timeout), verifikasi
   `analysis_result.json` valid & `generate_report.py` menghasilkan HTML yang bisa dibuka.

## Pertimbangan yang Perlu Diputuskan (bukan auto-decide, taste/privasi)

- **Item 2 (pindah label sample ke path ter-track):** `Schema.md` §8 sendiri mencatat teks
  komentar pelanggan itu data publik TikTok tapi masih berpotensi sensitif (nama anak, usia,
  kondisi kesehatan disebutkan). Nge-commit 200 komentar mentah + label manual ke git history
  (permanen, gak bisa dihapus bersih) beda konsekuensinya dari nge-commit kode. Alternatif:
  biarkan di `runs/` (gitignored) tapi WAJIB backup manual (dokumentasikan di README), atau
  simpan di direktori terpisah yang di-gitignore secara eksplisit tapi bukan `runs/` biar gak
  ketimpa scraper baru.

## NOT in Scope

- Fine-tuning ulang model atau ganti model lagi (sudah settled sesi ini, G-08 lulus).
- Threshold recalibration (sudah final di `config/thresholds.yaml` sampai ada alasan baru).
- Perubahan lexicon (dead code, sengaja ditinggal, lihat `Architecture.md` ADR-02).

---

## /autoplan Review (versi ringkas — 1 reviewer independen, bukan full gauntlet, disepakati user)

Codex tidak terpasang. Satu subagent Claude independen (belum lihat percakapan
sebelumnya) memverifikasi ulang tiap item langsung ke kode. Semua 7 klaim
**dikonfirmasi benar** — nol item ternyata sudah beres atau salah scope.

### Temuan tambahan dari subagent (semua diterima)

- **Item 1 (fixture):** tambah — strip PII (usia/kondisi anak) eksplisit, dan
  bentuknya harus match skema `flatten_input()` beneran, bukan cuma dekoratif.
- **Item 2 (lokasi label sample):** subagent nemuin opsi ke-3 yang lebih baik
  dari 2 opsi asli — **commit cuma `comment_id`+`sentiment_label`+`notes`**
  (tanpa teks komentar/username) sebagai "kunci jawaban" ter-track git,
  sementara file lengkap (isi teks asli) tetap gitignored terpisah dari `runs/`.
  Kalibrasi tetap reproducible dari file ter-commit, teks pelanggan gak pernah
  masuk git history.
- **Item 3 (codebook):** tambah — dokumentasikan cara menangani disagreement
  antar-annotator kalau nanti dilabel ulang orang lain.
- **Item 4 (--month/--dry-run):** **PISAH jadi 2 task** — `--month` cuma
  convenience flag kecil (ship cepat), `--dry-run`/FR-09 butuh desain sendiri
  (estimasi biaya dari distribusi confidence model). Digabung berisiko scope
  creep. Juga: `sample.py` (README) udah punya konvensi `--dry-run` sendiri
  ("print split & estimasi, tulis nothing") — pakai pola yang sama, jangan
  bikin konvensi baru.
- **Item 5 (progress log):** upgrade — reuse pola checkpoint `.partial.jsonl`
  yang udah dipakai `batch.py` buat scraping, bukan cuma log biasa. Efeknya:
  run yang keputus di tengah jalan (kayak percobaan kemarin yang timeout) bisa
  di-resume, bukan cuma "kelihatan gak macet".
- **Item 7 (full run):** tambah kriteria selesai eksplisit — paste ringkasan
  run + konfirmasi `generate_report.py` bisa buka hasilnya, biar gak ambigu
  kapan "selesai".

### Keputusan (6 prinsip)

| # | Item | Keputusan | Prinsip |
|---|---|---|---|
| 1 | Fixture + strip PII | Approve, + syarat subagent | P4 DRY (skema asli) |
| 2 | Lokasi label sample | **TASTE — ke gate user** | privasi vs reproducibility, bukan mekanis |
| 3 | Codebook + disagreement handling | Approve, + syarat subagent | P1 completeness |
| 4 | `--month` vs `--dry-run` | **Dipisah 2 task**, `--month` masuk scope ini, `--dry-run`/FR-09 didaftar terpisah (blast radius lebih besar dari 1 hari CC) | P2 boil lakes (bukan boil ocean sekaligus) |
| 5 | Progress log → checkpoint `.partial.jsonl` | Approve upgrade | P2 boil lakes (efek sama, value lebih besar) |
| 6 | Overwrite guard | Approve apa adanya | Mekanis |
| 7 | Full run + kriteria selesai | Approve + syarat subagent | Mekanis |

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|---|---|---|---|---|---|
| Review ringkas (1 subagent, bukan full CEO+DX+Eng) | `/autoplan` (versi ringkas, disepakati user) | Plan kecil (~7 item polish), full gauntlet gak sepadan | 1 | issues_open | 7/7 klaim dikonfirmasi, 5 penambahan diterima, 1 taste decision ke gate |

**VERDICT:** Scope final = 7 task (item 4 pecah jadi `--month` + FR-09 dry-run
terpisah, FR-09 didefer ke `TODOS.md`). Item 2: **user pilih opsi hybrid** —
commit `comment_id`+`sentiment_label`+`notes` ke `config/calibration/`, file
lengkap (teks komentar) pindah ke direktori gitignored baru `local/` (bukan
`runs/`, biar gak ketimpa scraper).

**STATUS: APPROVED, lanjut implementasi.**

## Status Implementasi (2026-08-30, sesi sama)

| # | Task | Status |
|---|---|---|
| 1 | Fixture `docs/examples/comments.sample.json` | ✅ Selesai — 9 komentar sintetis, PII-free, tervalidasi lolos `flatten_input()` + FR-11 auto-exclude |
| 2 | Hybrid storage (`local/` gitignored + `config/calibration/tahap-b-labels.csv` ter-commit) | ✅ Selesai — `.gitignore` diupdate, file lama dipindah, `calibrate_threshold.py` export answer-key otomatis |
| 3 | `docs/calibration/codebook.md` + label `tidak_yakin` + disagreement handling | ✅ Selesai |
| 4a | `--month` flag | ✅ Selesai, test lulus |
| 4b | `--dry-run`/FR-09 | ⏸️ Didefer ke `TODOS.md` (butuh desain sendiri) |
| 5 | Progress log + checkpoint resume (`.analyze-partial.jsonl`, pola sama `runner.py`) | ✅ Selesai, `--fresh` buat clear, test lulus |
| 6 | Overwrite guard `generate_labeling_sample.py` (`--force`) | ✅ Selesai, diverifikasi manual |
| 7 | Full end-to-end run 6.158 komentar | ✅ Selesai — exit 0, ~28 menit (`runs/2026-08/analysis_result.json`), `generate_report.py` berhasil bikin `report.html` (12,9KB, angka cocok, blok Metodologi ada) |

Test suite: **332 passed** (naik dari 328 — 4 test baru buat `--month`,
checkpoint resume, `--fresh`, usage-error tanpa `--month`/`--input`).

**Hasil run nyata (mode model-only, tanpa LLM eskalasi — `.env` belum diisi):**
6.158 komentar dianalisis, 0 dikecualikan. Sentimen: **positif 1.731 (28%),
negatif 1.005 (16%), netral 3.422 (56%)**. Beda dari distribusi sampel Tahap B
(69% netral) — wajar, sampel 200 itu quota-stratified per tier akun
(50/30/20), bukan representative random dari seluruh populasi komentar.

**SEMUA 7 ITEM SELESAI. Plan APPROVED dan DIEKSEKUSI penuh.**
