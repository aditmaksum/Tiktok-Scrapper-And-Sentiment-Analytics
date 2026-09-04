# Rules — Sosmed Sentiment Pipeline

| | |
|---|---|
| **Versi** | 0.2 |
| **Tanggal** | 2026-08-30 |
| **Status** | Draf |
| **Sumber** | `PRD.md`, `Architecture.md`, `Schema.md`, `DESIGN.md` (semua v0.1) |

## 1. Konteks Singkat
Dua CLI Python 3.12 yang terpisah: `analyze` (ingest → exclude filter → preprocessing Bahasa Indonesia → klasifikasi sentimen hybrid lexicon+LLM → ekstraksi keyword → JSON) dan `generate_report` (JSON → laporan HTML statis). Tidak ada server, tidak ada database. Kontrak data lihat `Schema.md`; keputusan stack & alasannya lihat `Architecture.md`; scope fitur lihat `PRD.md`; tampilan laporan lihat `DESIGN.md`.

## 2. Aturan Mutlak
- Jangan pernah menulis `LLM_API_KEY` atau kredensial lain langsung di kode atau file yang di-commit — hanya lewat environment variable (lihat `.env.example`).
- Jangan pernah mengubah urutan tahap preprocessing (`case_folding → cleaning → normalizing → tokenizing → filtering → stemming`) tanpa mendiskusikan dulu — urutan ini dipilih sengaja berdasar alasan teknis di `Architecture.md`/diskusi sebelumnya, bukan kebetulan.
- Jangan pernah menghapus kata negasi (`tidak`, `bukan`, `belum`, `jangan`, dll.) dari daftar stopword — ini akan merusak akurasi sentimen secara diam-diam tanpa error yang terlihat.
- Jangan pernah membiarkan kegagalan satu komentar (parsing/LLM call) menghentikan seluruh run — tangkap per-komentar, catat, lanjutkan (lihat `Architecture.md` §8).
- Jangan pernah menambah dependency baru (library) tanpa mencatatnya di `pyproject.toml` beserta alasan singkat di commit message.
- Jangan menonaktifkan type checking/linter untuk membuat kode lolos — perbaiki kodenya atau diskusikan aturan yang menghalangi.

## 3. Struktur & Penempatan Berkas
| Jenis kode | Lokasi | Konvensi nama berkas |
|---|---|---|
| Logika ingest per platform | `sosmed_sentiment/ingest/` | `<platform>_adapter.py` (mis. `tiktok_adapter.py`) |
| Tahap preprocessing | `sosmed_sentiment/preprocessing/` | satu file per tahap, nama = nama tahap (`cleaning.py`, dst) |
| Logika klasifikasi sentimen | `sosmed_sentiment/sentiment/` | `lexicon_classifier.py`, `llm_classifier.py`, `hybrid.py` |
| Ekstraksi keyword | `sosmed_sentiment/keywords/` | `tfidf_extractor.py` |
| Serialisasi output | `sosmed_sentiment/output/` | `serializer.py` |
| Rendering laporan | `sosmed_sentiment/report/` | `html_builder.py` + `templates/*.html.j2` |
| Entry point CLI | `sosmed_sentiment/cli/` | `analyze.py`, `generate_report.py` — **hanya** parsing argumen & orkestrasi, tidak boleh berisi logika bisnis |
| Konfigurasi | `config/` (root repo, bukan di dalam `sosmed_sentiment/`) | `exclude_accounts.yaml`, `thresholds.yaml`, `stopwords_custom.txt` |
| Tes | `tests/` (root repo yang sudah ada, dipakai bareng test scraper) | mirror struktur `sosmed_sentiment/`, prefix `test_` |

**Larangan tegas:** LLM calls only from dedicated `*_llm.py` client modules; never from `cli/`, never inline in business logic. Tidak boleh ada logika parsing/transformasi teks di file `cli/*.py`.

(Amended 2026-09-04 per `docs/plans/2026-09-04-llm-narrative-citation-guardrail.md`
Decision #12 - the original wording named `sentiment/llm_classifier.py` as
the only sanctioned LLM call site; `report/llm_insights.py` is a second,
legitimately different concern - metrics-dict-in/narrative-JSON-out, not
comment-in/label-out - so the rule now states the pattern it actually means
to enforce: one auditable call site per concern, each living in its own
`*_llm.py` module, never reached from `cli/` or inlined into business
logic.)

## 4. Penamaan
| Elemen | Konvensi | Contoh |
|---|---|---|
| Variabel & fungsi | `snake_case` | `extract_top_keywords()` |
| Kelas | `PascalCase` | `HybridSentimentClassifier` |
| Konstanta | `UPPER_SNAKE_CASE` | `DEFAULT_AMBIGUOUS_THRESHOLD` |
| Field JSON (input/output) | `snake_case` | sesuai `Schema.md` persis — jangan improvisasi nama field baru tanpa update `Schema.md` dulu |
| Berkas modul | `snake_case.py` | `lexicon_classifier.py` |
| Cabang git | `tipe/deskripsi-singkat` | `feat/hybrid-sentiment-classifier`, `fix/emoji-extraction-order` |

## 5. Gaya Kode
- Formatter: `black` (default config, line length 88).
- Linter: `ruff`.
- Type hints **wajib** di semua fungsi publik (parameter & return type) — proyek ini kecil, tidak ada alasan untuk `any`/tanpa tipe.
- Docstring gaya Google untuk setiap fungsi di luar `cli/` yang punya lebih dari 3 baris logika.
- Perintah sebelum commit:
  ```
  black src/ tests/
  ruff check src/ tests/
  pytest
  ```

## 6. Pola yang Diharapkan

**Menangani kegagalan per-item tanpa menghentikan batch (dipakai di preprocessing & sentiment):**
```python
def classify_batch(comments: list[Comment]) -> list[ClassifiedComment]:
    results = []
    for comment in comments:
        try:
            results.append(classify_one(comment))
        except LLMCallError as e:
            logger.warning(f"Gagal klasifikasi {comment.comment_id}: {e}")
            results.append(ClassifiedComment.as_failed(comment))
    return results
```

**Memuat config dengan default eksplisit (dipakai di semua tahap yang punya threshold/exclude-list):**
```python
def load_threshold_config(path: str | None) -> ThresholdConfig:
    if path is None:
        logger.info("Tidak ada threshold config, pakai default bawaan")
        return ThresholdConfig.default()
    return ThresholdConfig.from_yaml(path)
```

**Logging tahap pipeline (dipakai di setiap tahap Modul 1, sesuai NFR-05):**
```python
logger.info(f"{stage_name}: {len(input_data)} masuk -> {len(output_data)} keluar")
```

**Validasi skema input sebelum diproses lebih lanjut (dipakai di ingest):**
```python
def validate_input_schema(raw: list[dict]) -> None:
    for video in raw:
        if "aweme_id" not in video or "comments" not in video:
            raise InvalidInputSchemaError(
                f"Video tanpa 'aweme_id' atau 'comments': {video.get('aweme_id', '???')}"
            )
```

## 7. Penanganan Error & Log
- Exception kustom per lapisan: `InvalidInputSchemaError` (ingest), `LLMCallError` (sentiment), `ReportBuildError` (report) — semua turunan dari `PipelineError` dasar.
- `InvalidInputSchemaError` **selalu** menghentikan run (exit code 2) — tidak boleh dilewati diam-diam, karena data yang tidak sesuai skema bisa mencemari seluruh hasil analisis.
- `LLMCallError` per-komentar **tidak** menghentikan run (lihat §2 & pola di §6), tapi diakumulasi dan dilaporkan di akhir (lihat `Architecture.md` §8 soal ambang 10%).
- Log level: `INFO` untuk progres normal, `WARNING` untuk data yang di-skip/tidak lengkap tapi run tetap lanjut, `ERROR` untuk kegagalan yang dicatat, `CRITICAL` hanya untuk kegagalan yang menghentikan run sepenuhnya.
- **Tidak boleh masuk log:** isi penuh `LLM_API_KEY`, dan sebaiknya hindari mencatat teks komentar mentah secara berlebihan di level `INFO` (cukup `comment_id`) — teks lengkap cukup ada di `analysis_result.json`, bukan diduplikasi ke file log.

## 8. Keamanan
- Semua path file dari argumen CLI divalidasi eksis & bisa dibaca/ditulis sebelum proses utama mulai berjalan (fail fast, bukan gagal di tengah setelah banyak komentar sudah diproses).
- Tidak ada input dari pengguna luar (bukan aplikasi web) — permukaan risiko keamanan utama adalah file config (exclude-list, threshold) dan API key, yang sudah dicakup di §2.
- Kalau ke depan ditambah adapter platform lain yang butuh scraping/API pihak ketiga, kredensial baru mengikuti pola yang sama: env var, tidak pernah di file yang di-commit.

## 9. Testing
- Wajib punya test: seluruh fungsi di `preprocessing/`, `sentiment/lexicon_classifier.py`, `keywords/tfidf_extractor.py`, dan validasi skema di `ingest/` — ini logika inti yang menentukan benar/salahnya hasil analisis.
- Tidak wajib test detail: `cli/*.py` (orkestrasi tipis) dan `report/html_builder.py` bagian rendering visual (cukup test bahwa field yang dibutuhkan template tersedia, bukan test tampilan pixel-perfect).
- Test untuk `sentiment/llm_classifier.py` **wajib** mock panggilan API — tidak boleh ada test yang benar-benar memanggil LLM API (biaya & non-deterministik).
- Konvensi: `tests/preprocessing/test_cleaning.py` untuk `sosmed_sentiment/preprocessing/cleaning.py`, dst.
- Jalankan: `pytest` dari root repo (sama dgn test scraper yang sudah ada); `pytest --cov=sosmed_sentiment` untuk cek coverage kalau diperlukan.

## 10. Git & Commit
- Format: Conventional Commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`).
- Contoh: `feat: tambah eskalasi LLM untuk komentar dengan skor lexicon ambigu`
- Syarat sebelum merge ke branch utama: `black`, `ruff check`, dan `pytest` semua lolos tanpa error.

## 11. Aturan Khusus untuk AI Agent
- Baca `PRD.md` dan `Architecture.md` sebelum menambah fitur apa pun — jangan merancang ulang alur hybrid sentiment atau urutan preprocessing sendiri.
- Kalau kebutuhan ambigu (mis. nilai threshold eksak, format kartu di laporan), tanya dulu — jangan pilih tafsir termudah lalu diam-diam menuliskannya sebagai final.
- Kerjakan satu komponen per giliran sesuai tabel di `Architecture.md` §4 — jangan menyentuh berkas di luar yang diminta.
- Jangan membuat abstraksi tambahan (mis. plugin system, factory pattern berlapis) untuk kebutuhan yang belum diminta — `PRD.md` §5 sudah eksplisit soal apa yang tidak termasuk di rilis ini.
- Jangan menghapus kode yang tidak dipahami maksudnya — tandai dengan komentar `# TODO: perlu klarifikasi —` dan tanyakan ke user.
- Kalau sebuah aturan di dokumen ini ternyata menghalangi solusi yang benar secara teknis, sampaikan dulu ke user — jangan diam-diam melanggarnya.
- Setelah menyelesaikan satu bagian pekerjaan, sebutkan berkas apa saja yang berubah dan kenapa, termasuk apakah ada dampak ke `Schema.md` (field baru/berubah) yang perlu diupdate dokumennya juga.

## 12. Perintah Penting
| Tujuan | Perintah |
|---|---|
| Install dependency | `pip install -r requirements.txt` (repo satu dgn scraper, bukan `pip install -e .`) |
| Jalankan Modul 1 | `python -m sosmed_sentiment.cli.analyze --input comments.json --output analysis_result.json` |
| Jalankan Modul 2 | `python -m sosmed_sentiment.cli.generate_report --input analysis_result.json --output report.html` |
| Jalankan tes | `pytest` |
| Format & lint | `black sosmed_sentiment/ tests/ && ruff check sosmed_sentiment/ tests/` |

## Riwayat Perubahan
| Tanggal | Versi | Perubahan |
|---|---|---|
| 2026-08-30 | 0.2 | Sesi /plan-eng-review: path `src/sosmed_sentiment/` → `sosmed_sentiment/` (repo satu dgn scraper, Issue 2), `ANTHROPIC_API_KEY` → `LLM_API_KEY` (Premise 3), `pip install -e .` → `pip install -r requirements.txt` (Issue 2) |
| 2026-08-30 | 0.1 | Draf awal mengikuti PRD, Architecture, Schema, DESIGN v0.1 |
