# Architecture — Sosmed Sentiment Pipeline

| | |
|---|---|
| **Versi** | 0.4 |
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
| Stemming | `Sastrawi` (nama paket PyPI-nya, bukan "PySastrawi") | 1.0.1 | Library stemming Bahasa Indonesia paling umum dipakai di studi/produksi lokal. **Catatan performa (implementasi):** pure-Python, lambat per-panggilan — di-cache per token unik (`functools.lru_cache`) di `preprocessing/stemming.py`, lihat §10 |
| Lexicon sentimen | InSet Lexicon (atau lexicon Indonesia setara) — **implementasi awal pakai starter lexicon ~25 kata di kode** (`sentiment/lexicon_classifier.py: STARTER_LEXICON`), BUKAN InSet asli (butuh sumber terpisah, lihat PRD §9 ASUMSI) | — | Lexicon Indonesia yang tersedia publik untuk pass pertama klasifikasi hybrid |
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

### ADR-02 — Sentimen hybrid: lexicon dulu, LLM hanya untuk kasus ambigu
- **Konteks:** Keputusan user: hybrid, bukan lexicon murni atau LLM murni.
- **Pilihan yang dipertimbangkan:**
  - A. Lexicon murni — cepat & murah, tapi coverage rendah untuk slang TikTok dan tidak menangkap sarkasme/konteks.
  - B. LLM murni — akurat untuk nuansa, tapi mahal & lambat untuk ribuan komentar per run.
  - C. Hybrid — lexicon untuk mayoritas kasus jelas, LLM hanya untuk kasus ambigu.
- **Keputusan:** C.
- **Konsekuensi:** Biaya API terkendali (hanya subset yang dieskalasi), tapi butuh logika tambahan untuk mendefinisikan "ambigu" (lihat threshold di bawah) dan hasil akhir gabungan dua metode punya karakteristik confidence yang berbeda-beda — harus ditandai (`sentiment_method`) di output supaya transparan saat dianalisis lebih lanjut.
- **Aturan eskalasi default (bisa diubah lewat config, perlu dikalibrasi dengan data nyata sebelum dipakai produksi):**
  - Komentar dieskalasi ke LLM jika: skor absolut lexicon berada dalam zona netral sempit (default: `-0.15` s.d. `0.15` pada skala lexicon yang dinormalisasi ke `-1..1`), **atau** lebih dari 50% token hasil stemming tidak ditemukan di lexicon (out-of-vocabulary).
  - Komentar dengan skor jelas di luar zona itu langsung diberi label dari lexicon, tanpa panggilan API.
  - > **ASUMSI:** Angka `0.15` dan `50%` di atas adalah nilai awal yang masuk akal secara umum, bukan hasil kalibrasi terhadap data ini. Wajib direview setelah run pertama terhadap sampel data nyata sebelum dipakai untuk laporan final.

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
| `sentiment.lexicon_classifier` | Skor & label sentimen berbasis lexicon | FR-04 | `preprocessing.pipeline` |
| `sentiment.llm_classifier` | Klasifikasi via LLM API (router OpenAI-compatible) untuk kasus ambigu | FR-04 | `sentiment.lexicon_classifier` (hasil skor untuk deteksi ambigu) |
| `sentiment.hybrid` | Orkestrasi keputusan lexicon vs LLM per komentar | FR-04 | `sentiment.lexicon_classifier`, `sentiment.llm_classifier` |
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
│   │   ├── lexicon_classifier.py
│   │   ├── llm_classifier.py
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
└── requirements.txt                # sudah ada — ditambah scikit-learn, PySastrawi, jinja2, openai
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
| LLM API (via router, OpenAI-compatible) | Klasifikasi sentimen untuk komentar ambigu | API key via env var `LLM_API_KEY`, endpoint via `LLM_BASE_URL` | Retry 2x lalu tandai komentar `tidak_terklasifikasi`, run tetap lanjut (lihat §8); tidak memblokir komentar yang sudah selesai lewat lexicon |

## 10. Pemenuhan Kebutuhan Non-Fungsional
| NFR | Cara dipenuhi arsitektur |
|---|---|
| NFR-01 (skala ±10.000 komentar) | Pemrosesan berbasis iterasi/batch, bukan memuat seluruh transformasi ke memori sekaligus untuk tahap yang berat |
| NFR-02 (biaya LLM terkendali) | ADR-02: eskalasi hanya untuk kasus ambigu; FR-09 dry-run menghitung estimasi sebelum panggilan sungguhan |
| NFR-03 (reproducibility) | Lexicon & preprocessing deterministik (tidak ada randomness); versi lexicon & model LLM dicatat di `meta` output JSON supaya bisa ditelusuri run mana pakai konfigurasi apa |
| NFR-04 (laporan portabel offline) | ADR-04: HTML statis, CSS inline dalam file yang sama, font fallback ke system font kalau tidak ada internet |
| NFR-05 (observability) | Setiap komponen di §4 mencatat jumlah data masuk/keluar ke log terstruktur (lihat `Rules.md` §7) |
| NFR-06 (Bahasa Indonesia) | Lexicon, stopword custom, dan stemmer (Sastrawi) semuanya ditargetkan untuk Bahasa Indonesia informal |

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
