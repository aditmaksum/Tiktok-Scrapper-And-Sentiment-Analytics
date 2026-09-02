# Architecture — Sosmed Sentiment Pipeline

| | |
|---|---|
| **Versi** | 0.5 |
| **Tanggal** | 2026-08-30 |
| **Status** | Draf |
| **Sumber** | `PRD.md` v0.1 |

## 1. Gambaran Sistem
Dua skrip CLI berdiri sendiri (bukan layanan/server), dijalankan berurutan secara manual oleh analis, terhubung lewat satu kontrak file JSON. Tidak ada komponen jaringan permanen kecuali panggilan keluar ke API LLM saat Modul Analisis butuh eskalasi klasifikasi. Bentuk ini dipilih karena skala pemakaian kecil (satu analis, one-off per file) — server/API/DB akan jadi biaya perawatan tanpa manfaat nyata di skala ini.

```
[comments.json]
      │
      ▼
[Modul 1: analyze]  ──(komentar ambigu)──HTTPS──> [LLM API via router]
      │  ingest → exclude filter → preprocessing →
      │  klasifikasi hybrid → ekstraksi keyword
      ▼
[analysis_result.json]   <── KONTRAK ANTARA MODUL 1 & 2 (lihat Schema.md)
      │
      ▼
[Modul 2: generate_report]
      │  baca JSON → susun HTML (Jinja2 template)
      ▼
[report.html]
```

## 2. Stack Teknologi
| Lapisan | Pilihan | Versi | Alasan |
|---|---|---|---|
| Bahasa | Python | 3.12 | Ekosistem NLP Bahasa Indonesia (Sastrawi, dsb.) paling lengkap di Python; kedua modul tidak butuh keunggulan bahasa lain |
| Stemming | `Sastrawi` (nama paket PyPI-nya, bukan "PySastrawi") | 1.0.1 | Library stemming Bahasa Indonesia paling umum dipakai di studi/produksi lokal. **Catatan performa (koreksi 0.5, verified langsung ke kode):** dokumen versi sebelumnya bilang ada `functools.lru_cache` per-token — TIDAK ADA di `preprocessing/stemming.py`, itu keliru (docstring modulnya sendiri mencatat cache per-token sempat dicoba lalu ditolak karena vocabulary informal terlalu luas buat cache efektif). Yang benar: `stem()` dipanggil SEKALI per komentar (semua token digabung jadi satu string), bukan per token — itu yang mengurangi overhead pemanggilan. Lihat §10 |
| Model sentimen lokal (revisi 0.5, menggantikan lexicon) | `mdhugol/indonesia-bert-sentiment-classification` (IndoBERT, HuggingFace, pinned ke commit `80ccb4c`) — pass pertama klasifikasi hybrid, gantiin `lexicon_classifier.py` sepenuhnya | `torch` 2.13.0 + `transformers` 5.16.1 (~600MB, departure sadar dari konvensi "stay light" repo ini — lihat catatan di bawah) | **Diputuskan lewat pengukuran langsung, bukan model card**: `/autoplan` review (2026-08-30) nemuin bug negasi fatal di rencana kamus InSet (`tidak bagus` → positif confidence 1.0). Model pretrained diuji langsung terhadap sampel 200 komentar berlabel (Tahap B): kandidat pertama (`w11wo/indonesian-roberta-base-sentiment-classifier`) cuma 53,5% akurasi (kalah dari baseline tebak-netral 69%, bias sistemik ke "negatif" buat teks santai/emoji-only — SmSA training data-nya review aplikasi formal, bukan komentar TikTok santai). Diganti ke `mdhugol/...` setelah dibandingkan langsung (`scripts/compare_models.py`): 71,0% akurasi mentah, dan lolos gate 80% (81,9%, threshold eskalasi 0,95, lihat `config/thresholds.yaml`) setelah lapis eskalasi LLM dihitung. `sentiment/lexicon_classifier.py` ditinggal di kode (tidak dihapus, buat referensi) tapi TIDAK dipanggil lagi di `cli.analyze` |
| Ekstraksi keyword | scikit-learn (`TfidfVectorizer` + `CountVectorizer`) | 1.9.0 | Sudah teruji, cukup untuk TF-IDF unigram+bigram tanpa perlu implementasi manual |
| LLM eskalasi | Client OpenAI-compatible (`base_url` configurable — mis. OpenRouter atau router lain) | `openai` python SDK terbaru stabil, dipakai dgn `base_url` custom | Direvisi dari draf awal (Anthropic API spesifik) di sesi /office-hours 2026-08-30: user butuh provider-agnostic karena akses LLM lewat router pihak ketiga, bukan Anthropic langsung. Kontrak prompt tidak berubah, hanya client & konfigurasi endpoint |
| Templating laporan | Jinja2 | terbaru stabil | Memisahkan struktur HTML dari logika Python, memudahkan siapa pun mengubah tampilan tanpa menyentuh Modul 1 |
| CLI | `click` | sama dgn `requirements.txt` yang ada | Direvisi dari draf awal (argparse) di sesi /plan-eng-review: repo ini (`main.py`, `batch.py`) udah pakai `click` konsisten — dua CLI library beda di satu repo cuma nambah cognitive load tanpa manfaat |
| Logging | `loguru` | sama dgn `requirements.txt` yang ada | Direvisi bareng baris CLI di atas — `tiktokcomment/errors.py` & `main.py` udah pakai `loguru`, ikutin pola yang sama |
| Config | file `.env` (env var) + file `.yaml`/`.json` untuk exclude-list & threshold | — | Rahasia (API key) terpisah dari config yang aman di-commit |
| Database | Tidak ada | — | Sesuai keputusan one-off per run (lihat PRD §5) |
| Hosting / Deploy | Tidak ada — dijalankan lokal dari command line | — | Sesuai keputusan bentuk sistem: CLI manual |

## 3. Keputusan Arsitektur (ADR)

### ADR-01 — Dua modul terpisah, dihubungkan lewat file JSON, bukan dipanggil langsung sebagai fungsi
- **Konteks:** User eksplisit ingin analisis dan penyusunan laporan terpisah agar masing-masing bisa dioptimalkan/diganti sendiri.
- **Pilihan yang dipertimbangkan:**
  - A. Satu proses, dua fungsi dipanggil berurutan dalam satu skrip.
  - B. Dua proses/CLI terpisah, terhubung lewat file JSON di disk.
  - C. Dua proses terpisah dengan komunikasi lewat pipe/stdin-stdout tanpa file perantara.
- **Keputusan:** B.
- **Konsekuensi:** Lebih mudah — bisa regenerasi laporan tanpa mengulang NLP yang mahal (termasuk biaya LLM), bisa ganti implementasi salah satu modul tanpa menyentuh yang lain, hasil antara bisa diperiksa manual (debugging lebih mudah). Lebih sulit — ada file perantara yang harus dijaga skemanya tetap kompatibel (`Schema.md` jadi kontrak yang harus dipatuhi kedua sisi); perlu disiplin versi skema kalau berubah nanti.

### ADR-02 — Sentimen hybrid: lexicon dulu, LLM hanya untuk kasus ambigu (REVISI 0.5: lexicon → model lokal)
- **Konteks:** Keputusan user: hybrid, bukan lexicon murni atau LLM murni.
- **Pilihan yang dipertimbangkan:**
  - A. Lexicon murni — cepat & murah, tapi coverage rendah untuk slang TikTok dan tidak menangkap sarkasme/konteks.
  - B. LLM murni — akurat untuk nuansa, tapi mahal & lambat untuk ribuan komentar per run.
  - C. Hybrid — lapis murah untuk mayoritas kasus jelas, LLM hanya untuk kasus ambigu.
- **Keputusan:** C. Bentuk cascade-nya tetap (lapis murah → eskalasi LLM), tapi lapis murahnya **direvisi 2026-08-30** dari kamus lexicon jadi model klasifikasi lokal — lihat `docs/designs/sentiment-model-cascade.md` (APPROVED) untuk kronologi lengkap kenapa (bug negasi di rencana InSet-lexicon, lalu dua kandidat model diuji langsung terhadap data nyata sebelum salah satu dipilih).
- **Konsekuensi:** Biaya API terkendali (hanya subset yang dieskalasi), tapi butuh logika tambahan untuk mendefinisikan "ambigu" dan hasil akhir gabungan dua metode punya karakteristik confidence yang berbeda-beda — harus ditandai (`sentiment_method`) di output supaya transparan saat dianalisis lebih lanjut. Konsekuensi baru dari revisi 0.5: `torch`+`transformers` (~600MB) jadi dependency baru, departure sadar dari konvensi "stay light" repo ini — diterima karena bug negasi di lexicon terbukti fatal dan biaya LLM murni yang tadinya dianggap mahal ternyata di bawah $3/bulan di skala ini (jadi bukan LLM murni yang dihindari, tapi lapis murahnya perlu akurat).
- **Aturan eskalasi (revisi 0.5 — signature `is_ambiguous()` berubah dari `(score, oov_ratio)` jadi `confidence` tunggal, model tidak punya konsep OOV):**
  - Komentar dieskalasi ke LLM kalau `sentiment_confidence` model < `ambiguous_confidence_threshold`.
  - **Tidak ada angka default ditulis di kode** — nilai ini WAJIB dikalibrasi terhadap sampel berlabel (Tahap B) lewat `scripts/calibrate_threshold.py`, ditulis ke `config/thresholds.yaml`, dan dipassing eksplisit lewat `--threshold-config`. Alasan: dua asumsi tertulis sebelumnya di proyek ini (cache Sastrawi, estimasi biaya LLM) sama-sama terbukti salah pas akhirnya diukur — jadi tidak ada placeholder angka lagi.
  - Nilai terkalibrasi saat ini (model `mdhugol/indonesia-bert-sentiment-classification`, sampel 200 komentar 2026-08-30): `0.95` → 81,9% akurasi lapisan model, 48% komentar dieskalasi. Detail penuh (kenapa bukan 0.90 yang secara teknis udah lolos target) ada di `config/thresholds.yaml`.

### ADR-03 — Exclude-list akun internal: manual untuk pola perilaku, otomatis khusus akun pengunggah video
- **Konteks:** Ditemukan akun brand/admin (`dokterrizkimrd`, `yayleindonesia`, `yaylesupport`) mendominasi balasan pada data contoh.
- **Pilihan yang dipertimbangkan:**
  - A. Deteksi heuristik otomatis berbasis pola perilaku (mis. akun yang X% aktivitasnya adalah reply, bukan comment top-level).
  - B. Daftar manual di file config, diisi/diperbarui analis per proyek.
  - C. Auto-exclude khusus akun pengunggah video (identitas video itu sendiri), terpisah dari heuristik pola perilaku.
- **Keputusan:** B untuk kasus umum, **+ C untuk akun pengunggah video** (revisi 2026-08-30, sesi /office-hours — lihat FR-11).
- **Kenapa C beda dari A yang ditolak:** A ditolak karena heuristik pola perilaku (rasio reply, dst) bisa salah mengecualikan pelanggan asli yang kebetulan polanya mirip. C tidak punya risiko itu — akun pengunggah video diketahui identitasnya secara pasti dari metadata video itu sendiri (bukan ditebak dari pola perilaku), jadi tidak ada false-positive yang mungkin terjadi.
- **Konsekuensi:** Exclude-list manual tetap dibutuhkan untuk akun staff/admin lain yang BUKAN pengunggah video tapi ikut membalas (mis. `yaylesupport` kalau itu bukan akun pengunggah) — FR-10 (transparansi top pengirim komentar) tetap jadi jaring pengaman untuk kasus ini.
- **Sumber `video_author_username` (revisi 2026-08-30, sesi /plan-eng-review):** BUKAN dari panggilan API TikTok baru — sempat dipertimbangkan (endpoint video-detail per video) tapi ditolak karena dobelin request volume ke TikTok per video dan naikin resiko block, sementara `comment/list/` (endpoint yang dipakai sekarang) memang tidak pernah mengembalikan info uploader (dicek langsung ke data asli & semua test fixture scraper — tidak ada satupun yang punya field author). Solusi yang dipakai: analis sudah punya data ini di CSV order-mirror mereka sendiri — kolom baru `nama_pengguna_kreator` ditambah ke `id_konten,account_type` yang sudah ada, dibaca `tiktokcomment/runner.py` (pola sama dengan `account_type` yang sudah ada), ditempel ke tiap entry sebagai `video_author_username` di `comments.json`. Zero request tambahan ke TikTok, zero resiko block baru.

### ADR-04 — HTML report statis dengan Jinja2, tanpa framework frontend
- **Konteks:** Output berupa satu file HTML yang harus bisa dibuka offline tanpa server; tidak ada kebutuhan interaktivitas kompleks (bukan dashboard).
- **Pilihan yang dipertimbangkan:**
  - A. String formatting manual Python untuk HTML.
  - B. Jinja2 template terpisah dari kode Python.
  - C. Framework frontend (React dsb.) yang di-build jadi statis.
- **Keputusan:** B.
- **Konsekuensi:** Lebih mudah dibaca & diubah dibanding string formatting manual, tanpa beban toolchain build seperti opsi C yang berlebihan untuk laporan statis satu halaman. Konsekuensinya: perlu dependency Jinja2 di lingkungan Modul 2 (ringan, tidak bermasalah).

## 4. Struktur Komponen
| Komponen | Tanggung jawab | Melayani FR | Bergantung pada |
|---|---|---|---|
| `ingest.tiktok_adapter` | Baca & flatten `comments.json` sesuai skema TikTok | FR-01 | — |
| `filters.exclude_accounts` | Buang komentar dari akun di exclude-list (manual) DAN dari akun pengunggah video kalau `video_author_username` tersedia (FR-11); hitung frekuensi kemunculan akun untuk `excluded_accounts_detected` | FR-02, FR-10, FR-11 | `ingest.*` |
| `preprocessing.pipeline` | Jalankan cleaning→normalizing→case folding→tokenizing→filtering→stemming berurutan | FR-03 | `filters.exclude_accounts` |
| `sentiment.model_classifier` (revisi 0.5, gantiin `sentiment.lexicon_classifier`) | Label & confidence sentimen dari model lokal (`text_raw` langsung, tanpa preprocessing 7-tahap — model punya tokenizer subword sendiri) | FR-04 | `transformers` |
| `sentiment.llm_classifier` | Klasifikasi via LLM API (router OpenAI-compatible) untuk kasus ambigu | FR-04 | `sentiment.model_classifier` (confidence untuk deteksi ambigu) |
| `sentiment.hybrid` | Orkestrasi keputusan model vs LLM per komentar | FR-04 | `sentiment.model_classifier`, `sentiment.llm_classifier` |
| `keywords.tfidf_extractor` | Hitung top keyword keseluruhan & per label sentimen | FR-05 | `preprocessing.pipeline`, `sentiment.hybrid` |
| `output.serializer` | Rakit & simpan `analysis_result.json` | FR-06 | seluruh komponen Modul 1 di atas |
| `cli.analyze` | Entry point Modul 1, parsing argumen, orkestrasi keseluruhan alur | FR-01–FR-06, FR-08, FR-09 | seluruh komponen Modul 1 |
| `report.html_builder` | Baca JSON, render template Jinja2 | FR-07 | `output.serializer` (skema) |
| `report.templates` | Berkas `.html.j2` untuk struktur laporan | FR-07 | — |
| `cli.generate_report` | Entry point Modul 2, parsing argumen | FR-07, FR-08 | `report.html_builder` |

## 5. Struktur Folder
**Revisi sesi /plan-eng-review:** hidup DALAM repo `tiktok-comment-scrapper` yang sudah ada, sebagai package baru sejajar `tiktokcomment/` — bukan repo/proyek terpisah seperti draf awal. Alasan: `comments.json` yang jadi input Modul 1 memang output langsung scraper ini (`runs/{bulan}/comments.json`), 1 repo = 1 `requirements.txt`/venv, tidak perlu copy-paste data antar repo.
```
tiktok-comment-scrapper/          # repo yang sudah ada
├── tiktokcomment/                 # scraper, sudah ada — TIDAK disentuh
├── main.py, batch.py              # CLI scraper, sudah ada — TIDAK disentuh
├── sosmed_sentiment/               # BARU — package pipeline sentimen
│   ├── ingest/
│   │   ├── base.py                # interface adapter, siap ditambah platform lain
│   │   └── tiktok_adapter.py
│   ├── filters/
│   │   └── exclude_accounts.py
│   ├── preprocessing/
│   │   ├── emoji.py
│   │   ├── cleaning.py
│   │   ├── normalizing.py
│   │   ├── case_folding.py
│   │   ├── tokenizing.py
│   │   ├── filtering.py
│   │   └── stemming.py
│   ├── sentiment/
│   │   ├── lexicon_classifier.py   # revisi 0.5: ditinggal, TIDAK dipanggil cli.analyze lagi
│   │   ├── model_classifier.py     # BARU 0.5 — gantiin lexicon_classifier di jalur produksi
│   │   ├── llm_classifier.py
│   │   ├── threshold_config.py
│   │   └── hybrid.py
│   ├── keywords/
│   │   └── tfidf_extractor.py
│   ├── output/
│   │   └── serializer.py
│   ├── report/
│   │   ├── html_builder.py
│   │   └── templates/
│   │       └── report.html.j2
│   └── cli/
│       ├── analyze.py
│       └── generate_report.py
├── config/                         # BARU
│   ├── exclude_accounts.yaml
│   ├── thresholds.yaml
│   └── stopwords_custom.txt
├── tests/                          # sudah ada — tests sentimen ditambah di sini, mirror struktur sosmed_sentiment/
├── .env.example                    # BARU (repo belum punya file ini, `.env` sudah di .gitignore) — LLM_API_KEY/LLM_BASE_URL/LLM_MODEL kosong
└── requirements.txt                # sudah ada — ditambah scikit-learn, Sastrawi, jinja2, openai, torch, transformers
```

## 6. Kontrak "API" (CLI, bukan HTTP)
Karena tidak ada server, kontrak antar-modul berupa argumen CLI dan skema file, bukan endpoint HTTP.

| Perintah | Fungsi | Argumen wajib | Argumen opsional |
|---|---|---|---|
| `python -m sosmed_sentiment.cli.analyze` | Jalankan Modul 1 | `--input <path comments.json>`, `--output <path analysis_result.json>` | `--exclude-config <path>`, `--threshold-config <path>`, `--dry-run` (FR-09), `--verbose` |
| `python -m sosmed_sentiment.cli.generate_report` | Jalankan Modul 2 | `--input <path analysis_result.json>`, `--output <path report.html>` | `--template <path .html.j2 custom>`, `--verbose` |

**Format keluaran standar:** kedua CLI menulis progres ke stderr (log), hasil akhir hanya berupa file di `--output`. Tidak ada output ke stdout selain ringkasan akhir singkat (jumlah diproses, path file hasil).

**Kode keluar (exit code):**
| Kode | Arti |
|---|---|
| 0 | Sukses |
| 1 | Error umum (exception tak terduga) |
| 2 | Input tidak valid / tidak sesuai skema |
| 3 | Kegagalan panggilan LLM yang tidak bisa dipulihkan (bukan per-komentar, tapi kegagalan total, mis. API key tidak valid) |

## 7. Autentikasi & Otorisasi
Tidak relevan — tidak ada login atau multi-role. Satu-satunya "kredensial" adalah `LLM_API_KEY` yang dibaca dari environment variable, tidak pernah ditulis ke file config yang di-commit.

## 8. Alur Data untuk Kasus Kritis

**Alur kritis: eskalasi ke LLM saat panggilan API gagal**
1. `sentiment.hybrid` menentukan komentar perlu dieskalasi (skor ambigu).
2. `sentiment.llm_classifier` memanggil LLM API (router OpenAI-compatible).
3. Jika sukses → label & confidence dari LLM disimpan, `sentiment_method = "llm"`.
4. Jika gagal (timeout, rate limit, error API) → **retry maksimal 2x dengan backoff**; jika tetap gagal, komentar ditandai `sentiment_label = "tidak_terklasifikasi"`, `sentiment_method = "llm_failed"`, dan dicatat di log. Run **tidak dihentikan** karena satu komentar gagal — kegagalan per-komentar tidak boleh menggagalkan seluruh batch.
5. Di akhir run, total kegagalan dilaporkan; jika rasio kegagalan melebihi ambang (default 10% dari total eskalasi), CLI keluar dengan exit code 3 supaya analis sadar ada masalah sistemik (bukan sekadar noise acak), meski file JSON tetap tersimpan sebagian.

## 9. Integrasi Eksternal
| Layanan | Fungsi | Cara autentikasi | Perilaku saat layanan mati |
|---|---|---|---|
| LLM API (via router, OpenAI-compatible) | Klasifikasi sentimen untuk komentar ambigu | API key via env var `LLM_API_KEY`, endpoint via `LLM_BASE_URL` | Retry 2x lalu tandai komentar `tidak_terklasifikasi`, run tetap lanjut (lihat §8); tidak memblokir komentar yang sudah selesai lewat model lokal |
| HuggingFace Hub | Unduhan model sentimen lokal (`mdhugol/indonesia-bert-sentiment-classification`, ~500MB, sekali per mesin lalu dari cache lokal) | Tidak butuh auth (model publik) | Load gagal (no internet, HF down) → `ModelLoadError` fatal SEBELUM komentar manapun diproses (exit 2), rerun begitu internet hidup lanjut normal tanpa kehilangan data — tidak ada fallback offline (risiko diterima secara eksplisit, lihat `docs/plans/2026-08-30-model-cascade-implementation.md`) |

## 10. Pemenuhan Kebutuhan Non-Fungsional
| NFR | Cara dipenuhi arsitektur |
|---|---|
| NFR-01 (skala ±10.000 komentar) | Pemrosesan berbasis iterasi/batch, bukan memuat seluruh transformasi ke memori sekaligus untuk tahap yang berat |
| NFR-02 (biaya LLM terkendali) | ADR-02: eskalasi hanya untuk kasus ambigu; FR-09 dry-run menghitung estimasi sebelum panggilan sungguhan |
| NFR-03 (reproducibility) | Model sentimen lokal & preprocessing deterministik (tidak ada randomness); model dipin ke commit HuggingFace spesifik (`model_classifier.py:MODEL_REVISION`, bukan `main` — update bobot upstream tidak mengubah hasil diam-diam); versi model & model LLM dicatat di `meta.config_used` output JSON supaya bisa ditelusuri run mana pakai konfigurasi apa |
| NFR-04 (laporan portabel offline) | ADR-04: HTML statis, CSS inline dalam file yang sama, font fallback ke system font kalau tidak ada internet |
| NFR-05 (observability) | Setiap komponen di §4 mencatat jumlah data masuk/keluar ke log terstruktur (lihat `Rules.md` §7) |
| NFR-06 (Bahasa Indonesia) | Model sentimen lokal (fine-tuned di korpus Bahasa Indonesia), stopword custom, dan stemmer (Sastrawi, dipakai jalur keyword extraction) semuanya ditargetkan untuk Bahasa Indonesia informal |

## 11. Lingkungan & Deploy
Tidak ada lingkungan staging/produksi — dijalankan langsung dari lingkungan lokal analis (satu lingkungan: lokal).

**Variabel lingkungan (nama & fungsi, bukan nilai):**
| Variabel | Fungsi |
|---|---|
| `LLM_API_KEY` | Autentikasi ke LLM API (router) untuk eskalasi sentimen |
| `LLM_BASE_URL` | Endpoint router LLM (mis. OpenRouter atau kompatibel OpenAI lain) — kosong di `.env.example`, wajib diisi user sebelum run |
| `LLM_MODEL` | Nama model yang dipanggil lewat router tsb — kosong di `.env.example`, wajib diisi user sebelum run |

Instalasi: `pip install -r requirements.txt` di venv lokal yang sama dengan scraper (repo satu, bukan `pyproject.toml`/paket terpisah — lihat §5). Tidak ada alur rilis formal — versi kode dikelola lewat git tag manual kalau diperlukan.

## 12. Observability
- Log ditulis ke stderr dengan level (`INFO` untuk progres tahap, `WARNING` untuk data yang di-skip/dianggap tidak lengkap, `ERROR` untuk kegagalan yang dicatat tapi tidak menghentikan run).
- Setiap tahap pipeline (ingest, exclude, preprocessing, sentiment, keyword) mencatat jumlah data masuk dan keluar — memudahkan menelusuri di tahap mana angka akhir jadi tidak sesuai ekspektasi.
- Ringkasan akhir run (jumlah dianalisis, rasio eskalasi LLM, jumlah gagal) dicetak di akhir eksekusi Modul 1, juga disimpan di field `meta` pada `analysis_result.json` supaya tetap tertelusuri meski log terminal sudah hilang.

## Riwayat Perubahan
| Tanggal | Versi | Perubahan |
|---|---|---|
| 2026-08-30 | 0.4 | ADR-03 sumber `video_author_username` direvisi lagi: dari rencana API video-detail baru (ditolak, resiko block) jadi kolom CSV input baru `nama_pengguna_kreator` yang analis sudah punya — dibaca `tiktokcomment/runner.py` (perubahan kecil di scraper yang sudah ada, bukan endpoint baru) |
| 2026-08-30 | 0.3 | ADR-03 direvisi: exclude-list manual (pola perilaku) tetap, DITAMBAH auto-exclude khusus akun pengunggah video (FR-11) — butuh field baru `video_author_username` dari scraper (dependency terpisah, scraper belum punya endpoint video-detail) |
| 2026-08-30 | 0.2 | LLM eskalasi diubah dari Anthropic API spesifik jadi client OpenAI-compatible dgn `base_url` configurable (env: `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`) — keputusan sesi /office-hours, Premise 3. Kontrak prompt tidak berubah |
| 2026-08-30 | 0.1 | Draf awal mengikuti PRD v0.1 |
