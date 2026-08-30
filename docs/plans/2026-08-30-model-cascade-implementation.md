<!-- /autoplan restore point: /c/Users/asets/.gstack/projects/romysaputrasihananda-tiktok-comment-scrapper/master-autoplan-restore-20260830-195752.md -->

# Rencana — Implementasi Sentiment Model Cascade (Approach C)

| | |
|---|---|
| **Versi** | 0.1 (draf, masuk `/autoplan`) |
| **Tanggal** | 2026-08-30 |
| **Branch** | `master` |
| **Sumber** | `docs/designs/sentiment-model-cascade.md` (APPROVED, sesi /office-hours 2026-08-30) |

## Ringkasan

Design doc APPROVED memilih **Approach C**: model Indonesia terlatih
(`w11wo/indonesian-roberta-base-sentiment-classifier`, MIT, lokal) menggantikan
seluruh rencana kamus InSet+negasi sebagai lapis gratis pertama. LLM router (UC1,
sudah ada) tetap jadi lapis eskalasi untuk komentar yang model-nya ragu.

**Ini MEMBATALKAN sebagian besar rencana sebelumnya**
(`docs/plans/2026-08-30-open-items-lexicon-fr09-kalibrasi.md`, 40 tugas):
- **Dibatalkan seluruhnya:** build InSet lexicon, penanganan negasi di
  `score_tokens()`, lookup dua-kunci, rescaling confidence kamus, lisensi InSet
  (T1, T1b, T1c, T1d, T3-sebagian, T4, T4b, T4c, E1-E9, E12-E16 dari plan lama)
- **Tetap berlaku:** T0 (commit ke git — masih paling prioritas), FR-09 dry-run
  (T6, sekarang mengestimasi biaya LLM dari confidence model bukan OOV lexicon),
  kalibrasi Tahap B (T9 — sekarang mengukur akurasi MODEL, bukan lexicon), seluruh
  temuan DX (F1-F24 — CSV Excel, README, `.env.example`, dll — tidak bergantung
  lexicon vs model)
- **Baru:** integrasi model lokal, penulisan ulang `is_ambiguous()` untuk terima
  confidence tunggal (bukan score+oov_ratio), instalasi `torch`+`transformers`

## Yang Harus Dikerjakan (draft awal, akan direview)

### 1. Prasyarat keras (tidak bisa ditunda)
- Commit seluruh kerja 2 sesi yang belum di-track (masih berlaku dari plan lama)
- **Probe langsung:** jalankan model terhadap `tidak bagus` dan `tidak kecewa`
  sebelum menulis kode integrasi — buktikan klaim "model paham negasi", jangan
  percaya deskripsi model card begitu saja (disiplin yang sama dipakai buat
  klaim Sastrawi cache dan biaya LLM sebelumnya)
- Ukur waktu inferensi model untuk batch 6.158 komentar di CPU analis (tidak ada
  asumsi GPU) — satu angka nyata, bukan tebakan

### 2. Integrasi model (`sosmed_sentiment/sentiment/model_classifier.py`, baru)
- Muat model + tokenizer sekali per proses (pola sama seperti `_STEMMER` di
  `stemming.py` — instansiasi sekali, dipakai ulang)
- `classify(text_raw) -> {label, confidence}` — input teks mentah (BUKAN token
  hasil stemming/filter — model punya tokenizer subword sendiri, tidak perlu
  pipeline preprocessing 7-tahap yang ada sekarang di jalur ini)
- Tulis versi model ke `meta.config_used` (ganti `lexicon_version`)

### 3. `hybrid.is_ambiguous()` — tulis ulang, bukan tambal
- Signature baru: terima `confidence: float` tunggal, bukan
  `(score, oov_ratio)`. Ini perubahan breaking yang disebut eksplisit di
  Feasibility Note design doc — dikerjakan sebagai penulisan ulang terencana,
  bukan hack di atas signature lama.
- `classify_comment()` di `hybrid.py` disesuaikan mengikuti

### 4. FR-09 dry-run — disesuaikan
- Estimasi eskalasi sekarang dari distribusi confidence model, bukan OOV lexicon
- Sisanya (estimasi token, estimasi biaya, tanpa panggilan API) tetap sama seperti
  rencana lama

### 5. Kalibrasi Tahap B — disesuaikan
- Threshold confidence untuk eskalasi dikalibrasi terhadap sampel 200 komentar
  berlabel (kerja manual yang sama, sekarang mengukur model bukan lexicon)
- **Tidak ada angka default ditulis di kode** sebelum kalibrasi ini jalan —
  sesuai keputusan eksplisit di design doc

### 6. Temuan DX yang tetap berlaku (dari plan lama, tidak berubah)
Semua 24 temuan DX (README, `.env.example`, CSV Excel-safe, codebook pelabelan,
`--month`, dll) tetap relevan — tidak satupun bergantung pada lexicon vs model.

### 7. Dependensi baru
- `torch`, `transformers` ditambah ke `requirements.txt`
- Dicatat eksplisit sebagai penyimpangan dari konvensi repo "tetap ringan" —
  `Architecture.md` §2 diperbarui menjelaskan kenapa

## Rejection Gate (dari design doc, wajib dihormati)

Kalau akurasi model terukur di bawah target (setelah Tahap B) → Approach C
DITOLAK, kembali ke Approach A (model + lexicon starter sebagai fallback) atau
rencana InSet-lexicon lama. Rencana ini TIDAK final sampai pengukuran itu ada.

## NOT in scope

- Membangun kamus InSet — dibatalkan oleh Approach C
- Penanganan negasi manual di `score_tokens()` — dibatalkan, model diklaim
  menangani ini bawaan (BELUM DIVERIFIKASI — lihat prasyarat #1)
- Fine-tuning model — di luar cakupan, pakai model pretrained apa adanya

---

## BUKTI TERUKUR (dijalankan langsung di venv repo, 2026-08-30)

| Klaim | Hasil |
|---|---|
| `torch` CPU-only ukurannya | **122 MB** (bukan 2,5 GB — dugaan sebelumnya salah, itu buat build CUDA) |
| Model paham negasi tanpa tambalan manual | `tidak bagus` → negatif (99,9%); `tidak kecewa` → positif (98,5%) — **G-07 LULUS 2/2** |
| Test suite (315 test) setelah `click` ke-upgrade 8.1.8→8.5.0 | **Tetap hijau**, exit 0 |
| Waktu inferensi | 45,6 ms/komentar sekuensial → **4,7 menit** buat 6.158 komentar (lebih cepat dari stemming 15-16 menit) |
| Unduhan pertama kali | ~5 menit (475 MB), habis itu **2,4 detik** dari cache |
| `requirements.txt` vs realita | **Bohong ke diri sendiri**: masih tertulis `click==8.1.8`, yang kepasang `8.5.0` |

## FASE CEO — Temuan

1. **[HIGH]** Tidak ada target akurasi numerik di 5 dokumen manapun — rejection gate G-08 gak bisa ditegakkan tanpa angka. **Fix:** pin angka (mis. ≥85% cocok dengan label Tahap B) sebelum nulis kode integrasi.
2. **[MEDIUM]** Footprint 122 MB + model 475 MB = ~600 MB, dikonfirmasi tapi belum di-sign-off eksplisit — design doc sendiri minta ini diputuskan sebelum `/autoplan` build. **Fix:** minta persetujuan eksplisit sekarang.
3. **[MEDIUM]** Regret 6 bulan: model tidak di-pin ke revisi/commit hash spesifik — kalau HuggingFace update bobotnya, hasil klasifikasi bisa diam-diam berubah. **Fix:** pin revisi model.
4. **[MEDIUM]** Regret 6 bulan: unduhan runtime dari HuggingFace = titik kegagalan tunggal baru (gak ada internet pas run day, proxy kantor, HF down). **Fix:** dokumentasikan jalur offline (vendor bobot model) sekarang.
5. **[LOW-MEDIUM]** Cuma satu model dipertimbangkan (`w11wo/...`), dipilih karena ketersediaan bukan perbandingan. **Fix:** bandingin 1-2 model lain terhadap 7 kasus tes + sebagian sampel Tahap B — murah (beberapa jam).

## FASE DX — Temuan (10, disaring ke yang penting)

- **[HIGH] F1-F2** — Gak ada instruksi install `torch`/`transformers` di README; run pertama diam 5 menit tanpa progress log, analis bisa Ctrl+C kirain macet.
- **[HIGH] F4** — Approach C **menghapus fallback offline** yang dimiliki Approach A (lexicon starter). Kalau internet mati pas run day, seluruh batch gak bisa mulai — bukan degradasi, berhenti total.
- **[HIGH] F8** — Gak ada rencana error-handling buat model load, padahal pola `errors.py`/`LLMCallError` sudah ada buat dicontoh. Gagal load = traceback mentah ke analis yang bukan programmer.
- **[MEDIUM] F3, F5, F6, F7, F9** — cache path gak terdokumentasi, rate-limit HF (udah kejadian pas probe barusan), proxy kantor, ruang disk, kegagalan DLL torch di Windows.
- **[LOW] F10** — `click==8.1.8` di `requirements.txt` gak sesuai realita (8.5.0), verified.

## FASE ENG — Temuan (arsitektur: BUKAN swap lurus)

1. **[CRITICAL]** Model keluarin label Inggris (`positive`/`negative`/`neutral`), **seluruh pipeline** (`serializer.py:5` `SENTIMENT_LABELS`, `_sentiment_summary`, `_per_video`) hardcode label Indonesia (`positif`/`negatif`/`netral`). **Tanpa mapping eksplisit, komentar berlabel model MENGHILANG DIAM-DIAM dari laporan** — bukan crash, data hilang tanpa error. **VERIFIED** langsung ke `serializer.py`.
2. **[HIGH]** `sentiment_method_breakdown` (`serializer.py:93-97`) hardcode key `'lexicon'` — kalau model pakai `sentiment_method='model'`, breakdown-nya `lexicon: 0` selamanya, hitungan asli hilang dari `meta`. **VERIFIED**.
3. **[HIGH]** Tidak ada isolasi kegagalan per-komentar buat panggilan model — beda dari `LLMCallError` yang udah ada. Model exception (OOM, token >512, dll) BISA menjatuhkan seluruh batch, bukan cuma satu komentar — lebih parah dari arsitektur yang mau dihindari.
4. **[MEDIUM]** Truncation gak diatur — komentar >512 token bikin pipeline crash.
5. **[MEDIUM]** Input kosong/emoji-only/whitespace belum diuji di jalur model (lexicon punya penanganan eksplisit, model belum).
6. **[MEDIUM]** Jaring pengaman eskalasi lebih lemah dari lexicon buat teks non-Indonesia — OOV ratio dulu selalu nangkep teks Inggris/campur, confidence model bisa PERCAYA DIRI SALAH buat teks di luar training-nya (bukan sekadar "gak ada OOV setara", ini regresi cakupan nyata).
7. **[MEDIUM]** Signature `classify(text_raw)` skalar mengunci keputusan sekuensial vs batch sebelum dievaluasi — 4,7 menit oke buat volume sekarang tapi ini keputusan diam-diam, bukan disengaja.
8. **[LOW-MEDIUM]** Gak ada fallback kalau bobot model gak bisa diunduh (beda dari Approach A).
9. **[LOW]** Versi `torch`/`transformers`/revisi model belum di-pin — melanggar "reproducible where possible".

## Tugas Wajib Sebelum Kode Ditulis

- [ ] Mapping label Inggris→Indonesia eksplisit + test (CRITICAL #1)
- [ ] Rename/perbaiki `sentiment_method_breakdown` key (HIGH #2)
- [ ] `ModelClassifyError` + isolasi kegagalan per-komentar (HIGH #3)
- [x] ~~Tentukan target akurasi numerik~~ **DIPUTUSKAN: >=80%** akurasi terhadap sampel 200 komentar Tahap B (bukan angka 93,2% dari paper w11wo/SmSA - itu benchmark data lebih formal, dipakai sebagai konteks bukan target langsung, domain shift ke slang TikTok diperkirakan turun 5-15 poin). Revisi model dipin ke commit `e402e46` (dari citation resmi model card).
- [ ] `requirements.txt`: pin `click`, `torch`, `transformers`, revisi model (Eng #9, DX F10)
- [ ] README: bagian install + footprint ~600MB + baris log "downloading model (~475MB, one-time)" (DX F1-F2)
- [ ] Error handling model-load dengan pesan actionable, bukan traceback mentah (DX F8)
- [ ] `truncation=True, max_length=...` di panggilan pipeline (Eng #4)
- [ ] Test: label mapping, empty/emoji input, >512 token, singleton-load, escalation boundary (Eng #10)
- [x] ~~Keputusan eksplisit: sekuensial vs batch~~ **DIPUTUSKAN: sekuensial.** 4,7 menit untuk 6.158 komentar sudah cukup cepat; batching menambah restrukturisasi `analyze.py` yang tidak sepadan untuk volume ini.
- [x] ~~Dokumentasikan risiko no-fallback-offline~~ **DIPUTUSKAN: diterima, tanpa fallback lexicon.** Model dimuat sekali di awal proses, bukan per-komentar — kalau load gagal (no internet), belum ada satu komentar pun terproses, jadi rerun begitu internet hidup = lanjut normal tanpa kehilangan apa pun. Kegagalan jaringan pas fase eskalasi LLM (model lokal sudah jalan) sudah tertangani arsitektur yang ada (`llm_failed` per-komentar, batch tidak jatuh).

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | issues_open | 5 findings, 0 critical |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | codex CLI not installed |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | issues_open | 9 findings, 1 critical (verified against live code) |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | skipped | no UI scope |
| DX Review | `/plan-devex-review` | Developer experience gaps | 1 | issues_open | 10 findings, 3 high |

- **VERDICT:** NOT CLEARED — eng review found 1 CRITICAL (silent data loss from label vocabulary mismatch, verified directly against `serializer.py`). Core premise of Approach C is now strongly evidenced (real model probe: G-07 negation test passes 2/2 with high confidence, torch is 122MB not 2.5GB, inference is faster than the stemming step it replaces) — the plan is sound, the integration code is not yet written and must not be written until the CRITICAL and the two HIGH eng findings are addressed.

**UNRESOLVED DECISIONS (2026-08-30, resolved):**
- ~~Accuracy target for G-08~~ RESOLVED: >=80% against Tahap B 200-comment sample.
- ~~600MB dependency footprint sign-off~~ RESOLVED: user approved.
- ~~Sequential vs batch inference~~ RESOLVED: sequential.
- ~~No-fallback-offline risk~~ RESOLVED: accepted, no engineering work needed — model loads once at process start, a load failure means zero comments were processed yet, so a rerun once internet is back resumes cleanly with no lost state; a mid-batch LLM-escalation network failure is already handled per-comment (`llm_failed`, batch does not abort).

NO UNRESOLVED DECISIONS
