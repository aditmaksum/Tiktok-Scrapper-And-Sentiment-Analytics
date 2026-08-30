<!-- /autoplan restore point: /c/Users/asets/.gstack/projects/romysaputrasihananda-tiktok-comment-scrapper/master-autoplan-restore-20260830-160001.md -->

# Rencana — Menutup 3 Open Item Sentiment Pipeline

| | |
|---|---|
| **Versi** | 0.1 (draf, belum direview) |
| **Tanggal** | 2026-08-30 |
| **Branch** | `master` |
| **Status** | Draf — masuk `/autoplan` |
| **Sumber** | `docs/PRD.md` v0.5, `docs/Architecture.md` v0.4, session summary 2026-08-30 |

## Ringkasan

Vertical slice pipeline sentimen sudah jalan end-to-end di data asli (6.158 komentar,
315 test lulus). Tiga open item tersisa sebelum hasilnya bisa dipercaya untuk laporan
produksi. Ketiganya saling terkait dan harus dikerjakan berurutan:

1. **Ganti starter lexicon (~28 kata) dengan InSet asli** — tanpa ini, hampir semua
   komentar out-of-vocabulary, jadi semua skor mendekati 0 dan semua label jadi
   "netral" atau dieskalasi ke LLM.
2. **Implementasi FR-09 `--dry-run`** — hitung berapa komentar akan dieskalasi ke LLM
   dan perkiraan biayanya, tanpa memanggil API.
3. **Kalibrasi threshold ambigu** (`0.15` / OOV `50%`) terhadap data nyata — angka
   sekarang adalah tebakan yang ditandai eksplisit sebagai ASUMSI di `PRD.md` §9.

Urutan wajib: lexicon dulu (item 1 mengubah distribusi skor secara fundamental),
lalu dry-run (item 2 adalah alat ukurnya), lalu kalibrasi (item 3 memakai alat itu).
Mengkalibrasi threshold terhadap starter lexicon 28 kata akan menghasilkan angka yang
langsung basi begitu lexicon diganti.

---

## Item 1 — Ganti starter lexicon dengan InSet

### Kondisi sekarang

`sosmed_sentiment/sentiment/lexicon_classifier.py` punya `STARTER_LEXICON`, 28 kata
hand-picked, ditandai PLACEHOLDER di komentar kodenya. `get_lexicon(None)` memakainya
sebagai default. Format file lexicon yang sudah didukung: CSV `word,score` dengan skor
sudah dinormalisasi ke `-1..1` (`load_lexicon()`).

### Sumber

InSet Lexicon — https://github.com/fajri91/InSet (Koto & Rahmaningtyas, 2017).
Sudah diprobe langsung hari ini, dua file dapat diakses:

| File | Entri unik | Rentang bobot |
|---|---|---|
| `positive.tsv` | 3.609 | +1 s.d. +5 |
| `negative.tsv` | 6.607 | -5 s.d. -1 |
| **Total baris** | **10.216** | |
| Kata muncul di kedua file | 1.142 | |
| **Kata unik** | **9.074** | |

Bentuk data: TSV `word<TAB>weight`, ada baris header.

### Masalah yang ditemukan saat probe (bukan konversi lurus)

**A. Ketidakcocokan bentuk kata — ini yang paling penting.**
Pipeline melakukan stemming Sastrawi SEBELUM lookup lexicon
(`cli/analyze.py:112-125`: `stem(filtered_tokens)` lalu `classify(stemmed, lexicon)`).
InSet berisi banyak bentuk berimbuhan (`merekam`, `membantu`, `keberhasilan`).
Kalau InSet dimuat mentah-mentah, token `rekam` hasil stemming tidak akan pernah
cocok dengan kunci `merekam` di lexicon. Akibatnya OOV ratio melambung, semua
komentar dianggap ambigu, dan seluruh batch dieskalasi ke LLM — kebalikan persis dari
tujuan ADR-02 (kontrol biaya).

**Sudah diukur, bukan dugaan.** 8.395 entri unigram InSet dijalankan lewat stemmer
Sastrawi yang persis dipakai pipeline: **3.217 dari 8.395 (38,3%) berubah bentuk**.
Contoh nyata: `merekam`→`rekam`, `dibantu`→`bantu`, `penerangan`→`terang`,
`banyaknya`→`banyak`, `pengembangan`→`kembang`. Artinya kalau InSet dimuat mentah,
38% isinya adalah kunci mati yang tidak akan pernah cocok dengan satu pun token.

**Solusi:** kunci lexicon di-stem dengan stemmer Sastrawi yang sama pada saat build,
bukan pada saat runtime. 8.395 entri menyusut jadi **5.960 stem berbeda**, dengan
**1.550 stem menerima lebih dari satu kata asal** (mis. `maaf` ← `maaf`, `pemaafan`,
`maafkan`, `memaafkan`). Bobot untuk stem yang bertabrakan digabung dengan rata-rata.
Biaya build: ~4 menit sekali jalan (233 detik terukur), bukan biaya runtime.

**B. Entri multi-kata tidak akan pernah cocok.**
740 entri (240 positif + 500 negatif, 7,2% dari total) berisi spasi
(mis. `putus tali gantung`). Tokenizer memecah teks jadi unigram, jadi kunci
multi-kata mati di lookup. Dibuang di tahap build, jumlahnya dicatat di log.

**C. Anotasi dalam kurung.**
19 entri negatif punya anotasi seperti `tersentuh (perasaan)`. Bagian kurung dibuang,
sisanya diperlakukan sebagai kata biasa.

**D. Kata yang muncul di dua file — 1.142 kasus, jauh lebih banyak dari dugaan.**
Terukur: 1.142 kata (12,6% dari kata unik) muncul di `positive.tsv` DAN
`negative.tsv` sekaligus, termasuk kata sehari-hari seperti `ada`, `adil`, `aduh`,
`abis`. Ini bukan kasus tepi yang bisa diabaikan diam-diam. Bobotnya dijumlahkan
(net), jumlah kasus dan daftar 20 konflik terbesar dicetak di log build supaya
bisa diperiksa mata manusia.

**E. Normalisasi skala.**
InSet memakai skala -5..+5, `load_lexicon()` mengharapkan -1..+1 (ADR-02).
Konversi: `score = weight / 5.0`, dibulatkan 4 desimal.

### Yang akan dibangun

- `scripts/build_lexicon.py` — skrip build sekali-jalan. Membaca dua TSV InSet
  (path lokal atau URL), menerapkan aturan A-E di atas, menulis
  `config/lexicon_inset.csv` dalam format `word,score` yang sudah didukung
  `load_lexicon()`. Mencetak ringkasan: entri masuk, dibuang karena multi-kata,
  digabung karena tabrakan stem, konflik pos/neg, entri akhir.
- `config/lexicon_inset.csv` — hasil generate, **di-commit ke repo**. Alasan: NFR-03
  (reproducibility) dan agar run bulanan tidak butuh koneksi internet ke GitHub.
  Skrip build hanya dijalankan ulang kalau InSet diperbarui.
- `config/lexicon_inset.SOURCE.md` — catatan asal: URL, commit hash InSet saat
  di-generate, tanggal, lisensi, dan perintah persis untuk generate ulang.
- Ubah default: `get_lexicon(None)` tetap mengembalikan `STARTER_LEXICON`, tetapi
  `cli/analyze.py` memberi default `--lexicon-config config/lexicon_inset.csv`
  kalau file itu ada. `STARTER_LEXICON` tetap dipertahankan sebagai fixture test
  dan fallback offline, tidak dihapus.
- `DEFAULT_LEXICON_VERSION` → `inset-v1.0-stemmed`, dicatat di `meta.config_used`
  output JSON (sudah ada mekanismenya di `analyze.py:151`).

### Test

- Build script: fixture TSV kecil yang memicu tiap aturan (multi-kata, kurung,
  tabrakan stem, konflik pos/neg, bobot di luar rentang, baris rusak).
- `config/lexicon_inset.csv` hasil generate: test smoke yang memastikan file ada,
  bisa di-load `load_lexicon()`, semua skor ada di `-1..1`, tidak ada kunci berspasi,
  dan jumlah entri di atas ambang minimal.
- Regresi: kata Indonesia umum yang sudah di-stem (`bagus`, `kecewa`, `bantu`)
  menghasilkan skor bertanda benar lewat `score_tokens()`.

### Risiko

- **Stemming lexicon merusak sebagian makna.** Sastrawi salah stem sebagian kata:
  `mengawal` (mengiringi) → `awal` (permulaan), `silahkan` → `silah`. Setelah
  digabung, stem `awal` mewarisi bobot dari kata yang maknanya beda. Ini harga yang
  dibayar untuk mencocokkan bentuk kata, dan tidak bisa dihindari selama pipeline
  melakukan stemming sebelum lookup. Mitigasi: build script menulis
  `config/lexicon_inset.collisions.txt` berisi 1.550 stem bertabrakan beserta kata
  asalnya, supaya bisa diaudit dan dikecualikan manual kalau ada yang jelas salah.
- Bobot InSet dikalibrasi untuk teks berita/formal Indonesia, bukan slang TikTok.
  Slang tetap OOV. Ini diterima untuk v1 — jalur eskalasi LLM memang ada untuk itu,
  dan item 3 akan mengukur seberapa besar sisa OOV-nya.
- Lisensi InSet perlu dikonfirmasi sebelum file hasil generate di-commit.

---

## Item 2 — FR-09 `--dry-run` estimasi biaya

### Spesifikasi (dari dokumen yang ada)

`PRD.md` FR-09: "Mode opsional yang menghitung berapa komentar akan dieskalasi ke LLM
tanpa benar-benar memanggil API, supaya biaya bisa diperkirakan dulu."
`Architecture.md` §7 sudah mencantumkan flag `--dry-run` di tabel CLI.
`docs/designs/sentiment-pipeline-design.md` menjadikannya kontrol proses:
dry-run wajib dijalankan dan direview manual SEBELUM run produksi penuh pertama.

### Perilaku

`python -m sosmed_sentiment.cli.analyze --input ... --dry-run` menjalankan seluruh
pipeline sampai keputusan ambigu, lalu berhenti:

- ingest → exclude → preprocessing → skor lexicon → `is_ambiguous()` per komentar
- **tidak ada satu pun panggilan API LLM** (jalur ke `classify_via_llm` tidak pernah
  disentuh, bukan dipanggil lalu hasilnya dibuang)
- tidak menulis `analysis_result.json` (mencegah file setengah jadi disangka hasil run
  asli); menulis laporan terpisah ke `--dry-run-report` (default:
  `<output>.dryrun.json`)
- exit code 0

### Isi laporan

- Jumlah komentar mentah, dikecualikan, dianalisis
- Jumlah & rasio yang akan dieskalasi ke LLM
- Pemecahan alasan eskalasi: berapa karena skor di zona netral, berapa karena OOV
  di atas ambang, berapa karena keduanya — ini yang langsung menjawab
  "threshold mana yang perlu digeser" di item 3
- Estimasi token: karakter prompt (SYSTEM_PROMPT + teks komentar) dibagi 4,
  dijumlahkan untuk seluruh komentar yang akan dieskalasi. Ditandai eksplisit
  sebagai perkiraan kasar, bukan hitungan tokenizer.
- Estimasi biaya: hanya kalau `--price-per-1m-input` / `--price-per-1m-output`
  diberikan. Tanpa flag itu, laporan mencetak jumlah token saja plus catatan
  "tarif router belum diketahui — kirimkan tarif untuk mendapat angka rupiah/dolar".
  Alasan: pipeline ini provider-agnostic secara sengaja (ADR revisi, sesi
  2026-08-30), jadi tidak ada tarif tetap yang benar untuk dipatok di kode.

### Masalah biaya waktu

Dry-run harus melakukan preprocessing penuh (satu-satunya cara mengetahui rasio
eskalasi), dan preprocessing = ~15 menit untuk 10.000 komentar (NFR-01, keputusan
2026-08-30). Jadi dry-run lalu run sungguhan = ~30 menit.

**Usulan:** dry-run menulis cache hasil preprocessing (`<output>.preprocess.json`,
berisi `comment_id → tokens_stemmed`), dan run sungguhan memakainya kembali kalau
hash file input cocok. Menghilangkan 15 menit kedua. Kalau hash tidak cocok, cache
diabaikan diam-diam dan preprocessing jalan seperti biasa.

Ini penambahan di luar tulisan FR-09 dan perlu keputusan eksplisit — lihat
"Keputusan Terbuka" di bawah.

### Test

- Dry-run tidak pernah memanggil LLM: mock `classify_via_llm`, tegaskan
  `assert not called`, termasuk saat `LLM_API_KEY` terisi di environment.
- Dry-run tidak menulis `analysis_result.json`.
- Pemecahan alasan eskalasi berjumlah benar (netral-saja + OOV-saja + keduanya =
  total eskalasi).
- Estimasi biaya nol kalau tidak ada komentar yang dieskalasi.
- Flag tarif tidak diberikan → laporan tetap terbit, bagian biaya berisi catatan.
- Cache preprocessing (kalau disetujui): hash cocok → dipakai; hash beda → diabaikan;
  cache rusak/tidak bisa di-parse → diabaikan, bukan crash.

---

## Item 3 — Kalibrasi threshold ambigu

### Kondisi sekarang

`DEFAULT_AMBIGUOUS_THRESHOLD_SCORE = 0.15`, `DEFAULT_AMBIGUOUS_THRESHOLD_OOV_RATIO = 0.5`
(`sentiment/hybrid.py:8-9`). Keduanya ditandai ASUMSI eksplisit di `PRD.md` §9 dan
`Architecture.md` ADR-02: "bukan hasil kalibrasi terhadap data ini. Wajib direview
setelah run pertama."

### Kenyataan yang harus diakui

Kalibrasi akurasi yang sebenarnya butuh ground truth berlabel. Kita tidak punya.
Jadi ini dipecah dua tahap: satu yang bisa diselesaikan kode sekarang, satu yang
butuh kerja manual analis.

### Tahap A — sweep distribusi (tidak butuh label, dikerjakan sekarang)

`scripts/calibrate_thresholds.py`: baca cache preprocessing atau `comments.json`,
skor semua komentar dengan lexicon InSet, lalu cetak:

- Histogram skor lexicon (bucket 0,05) dan histogram OOV ratio (bucket 0,05)
- Tabel sweep: untuk tiap pasangan `threshold_score` ∈ {0,05 0,10 0,15 0,20 0,30} ×
  `threshold_oov` ∈ {0,3 0,4 0,5 0,6 0,7 0,8}, berapa persen komentar yang dieskalasi
- Baris rekomendasi: pasangan threshold terlonggar yang tetap menjaga rasio eskalasi
  di bawah anggaran yang diberikan lewat `--escalation-budget` (default 20%)

Yang ini mengubah "0,15 itu tebakan" menjadi "0,15 mengeskalasi N% dari data nyata,
dan inilah angka yang menahannya di anggaran". Itu bukan kalibrasi akurasi, dan
laporannya harus mengatakan begitu dengan jelas.

### Tahap B — sampel berlabel (butuh kerja manual analis)

- `scripts/sample_for_labeling.py`: ambil sampel acak berstrata (default 200 komentar,
  seed tetap agar reproducible) mencakup semua band skor, tulis
  `runs/<bulan>/calibration_sample.csv` dengan kolom kosong `label_manual`.
- Analis mengisi kolom itu dengan `positif`/`negatif`/`netral`.
- `scripts/score_calibration.py`: baca CSV terisi, laporkan akurasi lexicon per band
  skor dan per bucket OOV. Band tempat akurasi lexicon jatuh di bawah ambang yang
  bisa diterima adalah band yang seharusnya dieskalasi — itulah threshold yang
  benar-benar terkalibrasi.

Tahap B menghasilkan angka final yang ditulis ke `config/thresholds.yaml` dan
`Architecture.md` ADR-02, mengganti tanda ASUMSI. Sampai itu terjadi, tanda ASUMSI
tetap berdiri.

### Test

- Sweep menghasilkan tabel yang benar untuk skor sintetis yang sudah diketahui
  hasilnya.
- Sampling berstrata deterministik untuk seed yang sama, dan menyentuh semua band
  yang ada di data.
- Skoring kalibrasi menangani label kosong (dilewati, dihitung) dan label tidak
  dikenal (peringatan, dilewati) tanpa crash.
- Rekomendasi threshold menghormati `--escalation-budget`.

---

## Yang TIDAK termasuk cakupan

- Mengganti Sastrawi atau mem-parallelkan stemming — ditutup sebagai keputusan sadar
  2026-08-30 (`PRD.md` NFR-01 v0.5).
- Menambahkan lexicon slang TikTok buatan sendiri — jalur eskalasi LLM adalah
  jawaban v1 untuk slang. Pertimbangkan lagi setelah tahap B menunjukkan seberapa
  besar sisa OOV-nya.
- Menjalankan run produksi penuh dengan LLM aktif — butuh `LLM_API_KEY` dan tarif
  router yang belum ada.
- Fine-tune atau training model — di luar cakupan v1 seluruhnya.
- Mengubah urutan tahap preprocessing (Aturan Mutlak `Rules.md`).

## Yang SUDAH ada dan dipakai ulang

- `load_lexicon()` sudah menerima CSV `word,score` — item 1 tidak butuh loader baru.
- `get_lexicon()`/`load_threshold_config()` sudah mengikuti pola default-config
  `Rules.md` §6 — skrip baru mengikuti pola yang sama.
- `is_ambiguous()` sudah memisahkan keputusan eskalasi dari eksekusinya — dry-run
  memakai fungsi yang sama persis, bukan menyalin logikanya.
- `stem()` sudah punya cache `lru_cache` per token unik — build script memakainya
  kembali, tidak membuat stemmer sendiri.
- `_preprocess()` di `analyze.py` adalah pipeline tahap tetap — dry-run dan skrip
  kalibrasi memanggilnya, tidak menulis ulang urutannya.

## Keputusan Terbuka

1. **Cache preprocessing untuk dry-run** — menghemat 15 menit per siklus
   dry-run-lalu-run, dengan biaya satu file cache dan pengecekan hash.
   Di luar tulisan FR-09.
2. **Ukuran sampel tahap B** — 200 komentar (kerja manual ~1-2 jam) vs 500
   (interval kepercayaan lebih sempit, kerja manual jauh lebih berat).
3. **Meng-commit `config/lexicon_inset.csv`** (~10.000 baris, ~200 KB) ke git vs
   men-generate-nya saat setup. Meng-commit menang untuk reproducibility dan
   kemampuan jalan offline; harganya adalah file data besar di repo.

---
---

# FASE 1 — CEO REVIEW (Strategi & Cakupan)

Mode: **SELECTIVE EXPANSION** (auto-decided, `/autoplan`).
Codex: tidak tersedia (binary tidak ditemukan) — `[subagent-only]`.

## Audit Sistem Pra-Review

| Item | Temuan |
|---|---|
| Branch / base | `master` / `master` (fork dari `romysaputrasihananda/tiktok-comment-scrapper`) |
| Commit terakhir | `db50a79 chore: add gstack skill routing rules to CLAUDE.md` |
| Kerja belum di-commit | 6 file dimodifikasi, 12 path baru belum di-track — **seluruh pipeline sentimen (`sosmed_sentiment/`, 315 test, 5 dokumen) ada di working tree, nol di git** |
| Stash | kosong |
| TODOS.md | tidak ada (`Rules.md` dan design doc merujuknya; file-nya tidak pernah dibuat) |
| TODO/FIXME di kode | nol di `sosmed_sentiment/` |
| Design doc | `docs/designs/sentiment-pipeline-design.md` — APPROVED, dibaca sebagai sumber kebenaran |

**Temuan repo (REPO_MODE unknown — dilaporkan, tidak diperbaiki sendiri):** seluruh
hasil kerja dua sesi ada di working tree yang belum di-commit, di atas `master`
sebuah fork. Satu `git checkout` yang salah menghapus semuanya. Ini bukan bagian
dari plan ini, tapi risikonya nyata dan berlaku sekarang.

**Prior learning applied: `design-doc-can-go-stale-mid-session` (confidence 8/10, 2026-08-30).**
Sudah kejadian lagi: `docs/designs/sentiment-pipeline-design.md:99` masih menyatakan
FR-11 butuh "panggilan API video-detail per video dulu", padahal baris 42 di dokumen
yang sama sudah mencatat itu SUPERSEDED oleh pendekatan kolom CSV. Bagian Dependencies
tidak ikut diperbarui waktu bagian Premises diperbarui. Sebuah dokumen yang berdebat
dengan dirinya sendiri lebih buruk daripada dokumen yang usang, karena pembaca tidak
tahu bagian mana yang menang.

## 0A. Premise Challenge

| # | Premis yang dipegang plan ini | Putusan |
|---|---|---|
| P1 | InSet adalah lexicon yang tepat | **DITERIMA.** `Architecture.md` §2 sudah menamainya, ia lexicon sentimen Indonesia yang paling banyak dipakai, dan sudah diverifikasi hidup hari ini (10.216 baris terunduh). |
| P2 | **Lexicon lebih besar = klasifikasi lebih baik** | **SALAH — dibantah dengan probe langsung.** Lihat di bawah. |
| P3 | Ketiga item bisa dikerjakan berurutan lexicon lalu dry-run lalu kalibrasi | **DIREVISI.** Urutan benar, tapi ada langkah nol yang hilang: negasi. |
| P4 | Tidak melakukan apa-apa itu tidak bisa diterima | **DITERIMA.** Dengan 28 kata, hampir semua komentar OOV, jadi hampir semua jatuh ke netral. Laporan yang bilang "90% netral" bukan hasil analisis, itu lexicon yang kosong. |
| P5 | Lapisan lexicon layak diperbaiki (vs LLM-only) | **DITERIMA dengan catatan.** ADR-02 adalah keputusan user yang sudah punya alasan; tidak dibuka ulang. Tapi angka biayanya sekarang bisa dihitung — masuk 0C-bis sebagai pembanding, bukan usulan pembatalan. |

### P2 gagal — dan ini temuan terpenting seluruh review

Constraint di design doc baris 31 berbunyi: "Kata negasi (`tidak`, `bukan`, `belum`,
`jangan`) tidak boleh masuk stopword — krusial untuk akurasi sentimen."

Constraint itu **dipatuhi secara harfiah dan diabaikan secara makna.**
`preprocessing/filtering.py:8` menjaga `NEGATION_WORDS` mati-matian, bahkan
mengabaikan file config yang keliru mendaftarkannya. `preprocessing/normalizing.py:10`
rajin memetakan `gak`, `ga`, `gk`, `ngga`, `nggak`, `kaga`, `tdk` semuanya jadi
`tidak`. Kata negasi selamat melewati seluruh preprocessing.

Lalu `sentiment/lexicon_classifier.py:77` merata-ratakan skor token yang cocok dan
**tidak melakukan apa pun terhadap kata negasi itu.** Dijalankan langsung terhadap
kode yang ada:

```
tokens                 hasil
['bagus']              positif, confidence 1.0, score  0.8
['tidak', 'bagus']     positif, confidence 1.0, score  0.8   <-- TERBALIK
['tidak', 'kecewa']    negatif, confidence 1.0, score -0.8   <-- TERBALIK
['bukan', 'penipu']    negatif, confidence 1.0, score -0.9   <-- TERBALIK
```

Label terbalik, dengan confidence maksimum. Dan jaring pengaman LLM tidak
menangkapnya: `['tidak','bagus']` menghasilkan `oov_ratio` tepat `0.5`, sementara
`hybrid.py:23` mengeskalasi hanya kalau `oov_ratio > 0.5`. Skornya `0.8`, jauh di
luar pita netral. Komentar itu **tidak pernah dikirim ke LLM.** Ia keluar sebagai
positif, percaya diri penuh, dan masuk ke laporan.

**Kenapa ini belum meledak:** starter lexicon cuma 28 kata, jadi `tidak bagus`
hampir tidak pernah punya kata kedua yang cocok. Bug-nya tertidur karena
lexicon-nya kosong.

**Kenapa plan ini membangunkannya:** mengganti 28 kata dengan 5.960 stem menaikkan
tingkat kecocokan secara drastis. Setiap komentar bernegasi yang sebelumnya lolos
sebagai netral sekarang keluar sebagai label terbalik dengan confidence 1.0.
**Item 1, seperti tertulis sekarang, membuat output pipeline lebih buruk, bukan
lebih baik** — bukan karena lexicon-nya salah, tapi karena scorer-nya belum siap
menerima lexicon yang benar-benar cocok.

Ini juga membatalkan sebagian item 3: distribusi skor yang akan disapu oleh
kalibrasi threshold dihasilkan oleh scorer yang membalik komentar bernegasi.
Mengkalibrasi terhadap distribusi itu berarti menyetel threshold ke sinyal yang
sebagiannya salah tanda.

**Konsekuensi untuk plan:** penanganan negasi masuk ke Item 1 sebagai prasyarat,
bukan peningkatan opsional. Tidak ada gunanya membahas item 2 dan 3 sebelum ini beres.

## 0B. Existing Code Leverage

| Sub-masalah | Kode yang sudah ada | Bangun baru? |
|---|---|---|
| Muat lexicon dari file | `lexicon_classifier.load_lexicon()` — CSV `word,score`, sudah menangani baris rusak | Tidak. Format build script menyasar loader ini. |
| Pola default-config | `get_lexicon()`, `load_threshold_config()`, `load_stopwords()` — pola `Rules.md` §6 | Tidak. Skrip baru meniru pola yang sama. |
| Keputusan eskalasi | `hybrid.is_ambiguous()` — sudah terpisah dari eksekusinya | Tidak. Dry-run memanggil fungsi yang sama persis. |
| Stemming dengan cache | `preprocessing/stemming.py` — `lru_cache` per token unik | Tidak. Build script memakainya kembali. |
| Urutan tahap preprocessing | `cli/analyze.py:_preprocess()` | **Ya, sebagian** — sekarang fungsi privat di dalam modul CLI. Tiga skrip baru membutuhkannya. Lihat 0D. |
| Normalisasi slang ke baku | `normalizing.SLANG_MAP` sudah memetakan 7 varian ke `tidak` | Tidak. Penanganan negasi memakai `NEGATION_WORDS` yang sudah ada. |
| Kata negasi selamat sampai scorer | `filtering.NEGATION_WORDS` | **Ya** — token-nya sampai, tapi tidak ada yang mengonsumsinya. Itu kerja barunya. |

Plan ini tidak membangun ulang apa pun. Satu-satunya kode betul-betul baru adalah
penanganan negasi, build script lexicon, jalur dry-run, dan skrip kalibrasi.

## 0C. Dream State Mapping

```
  KONDISI SEKARANG              PLAN INI                      IDEAL 12 BULAN
  ----------------              --------                      --------------
  Pipeline jalan end-to-end     Lexicon 5.960 stem InSet      Threshold hasil
  di 6.158 komentar asli.       plus penanganan negasi.       kalibrasi label
                          --->                          --->  nyata, tercatat.
  Lexicon 28 kata =             Biaya LLM bisa dilihat
  hampir semua netral.          sebelum dibelanjakan.         Kamus slang TikTok
                                                              menutup sisa OOV.
  Threshold ditebak,            Threshold dipilih dari
  ditandai ASUMSI.              distribusi nyata plus         Laporan yang berani
                                sampel berlabel.              dipakai ambil
  Negasi diawetkan lalu                                       keputusan, dengan
  dibuang diam-diam.            Negasi dihitung.              akurasi terukur.
```

Plan ini bergerak ke arah ideal itu. Yang membuatnya bergerak ke arah sebaliknya
adalah mengerjakan item 1 tanpa penanganan negasi: itu menaikkan cakupan lexicon
sambil menurunkan akurasi, dan menghasilkan angka yang lebih meyakinkan sekaligus
lebih salah. Justru versi itu yang paling berbahaya, karena kelihatannya seperti
kemajuan.

## 0C-bis. Alternatif Implementasi

```
APPROACH A: Konversi InSet lurus (rencana awal, apa adanya)
  Ringkas: Ubah TSV InSet jadi CSV, stem kuncinya, pasang jadi default. Tanpa
           perubahan scorer.
  Effort:  S (human ~0,5 hari / CC ~20 menit)
  Risk:    High
  Pros:    Diff terkecil; tidak menyentuh logika klasifikasi sama sekali.
  Cons:    Mengubah bug negasi yang tertidur jadi bug yang aktif menyala di
           setiap komentar bernegasi, dengan confidence 1.0. Membuat item 3
           mengkalibrasi terhadap sinyal yang sebagian salah tanda.
  Reuses:  load_lexicon(), stemming.stem()

APPROACH B: InSet plus penanganan negasi di scorer (DIREKOMENDASIKAN)
  Ringkas: Sama seperti A, plus score_tokens() membalik tanda skor token yang
           didahului kata negasi dalam jendela 1-2 token, dan sisa negasi yang
           tidak terpakai menaikkan sinyal ambigu supaya jatuh ke LLM.
  Effort:  M (human ~1,5 hari / CC ~45 menit)
  Risk:    Low
  Pros:    Menutup satu-satunya cacat correctness yang terbukti di pipeline;
           memenuhi constraint negasi design doc secara makna, bukan cuma huruf;
           membuat kalibrasi item 3 mengukur sesuatu yang nyata.
  Cons:    Menyentuh score_tokens(), yang dipakai bersama jalur lexicon dan jalur
           hybrid — butuh test regresi di keduanya.
  Reuses:  load_lexicon(), stemming.stem(), filtering.NEGATION_WORDS,
           normalizing.SLANG_MAP, hybrid.is_ambiguous()

APPROACH C: Lewati lexicon, LLM-only
  Ringkas: Buang lapisan lexicon, kirim semua komentar ke LLM.
  Effort:  S (human ~0,5 hari / CC ~20 menit)
  Risk:    Med
  Pros:    Negasi, sarkasme, dan slang ditangani model tanpa kode kita; menghapus
           tiga item open sekaligus.
  Cons:    Membatalkan ADR-02, keputusan user yang sudah beralasan; membuat setiap
           run bergantung jaringan dan tidak reproducible (melanggar NFR-03);
           6.158 komentar per run tiap bulan dengan tarif router yang belum
           diketahui — persis ketidakpastian biaya yang ADR-02 hindari.
  Reuses:  llm_classifier.classify_via_llm()
```

**REKOMENDASI: Approach B.** Approach A adalah diff terkecil yang membuat produk
lebih buruk, dan "explicit over clever" tidak berarti "diam-diam biarkan salah".
Approach C membuang keputusan arsitektur yang sudah dibuat user dengan alasan yang
masih berlaku. B satu-satunya yang membuat lexicon layak dipercaya sebelum dua item
lain menumpang di atasnya.

*(Auto-decided — P1 completeness dan P2 boil lakes. Bukan taste decision: A terbukti
salah lewat probe, bukan kalah selera.)*

## 0D. Analisis Mode — SELECTIVE EXPANSION

### Complexity check

Plan menyentuh: 1 file kode diubah (`lexicon_classifier.py`), 1 CLI diubah
(`analyze.py`), 4 file baru (3 skrip plus 1 modul negasi), 3 artefak config.
Di bawah ambang 8 file. Tidak ada kelas/service baru. Tidak ada smell kompleksitas.

### Perubahan minimum yang mencapai tujuan

Item 1 plus penanganan negasi adalah lantai dasarnya. Item 2 dan 3 tidak bisa
menghasilkan angka bermakna tanpa itu.

### Scan ekspansi (kandidat, diputuskan di bawah)

1. **Ekstrak `_preprocess()` dari `cli/analyze.py` ke `preprocessing/pipeline.py`.**
   Tiga skrip baru butuh urutan tahap yang sama persis. Menyalinnya tiga kali
   melanggar DRY tepat di tempat yang `Rules.md` sebut Aturan Mutlak — urutan
   tahap yang tidak boleh menyimpang justru akan hidup di empat salinan.
2. **Cache preprocessing dipakai bersama dry-run dan run sungguhan.** Menghemat
   ~15 menit per siklus.
3. **`config/lexicon_slang_tiktok.csv`** — kamus slang buatan sendiri di atas InSet.
4. **Menulis `TODOS.md`** yang selama ini dirujuk `Rules.md` dan design doc tapi
   tidak pernah ada.
5. **Membenahi `docs/designs/sentiment-pipeline-design.md:99`** yang masih
   mengklaim FR-11 butuh panggilan API video-detail.

### Cherry-pick ceremony (auto-decided)

| # | Kandidat | Effort | Blast radius | Putusan | Prinsip |
|---|---|---|---|---|---|
| 1 | Ekstrak `_preprocess()` ke modul bersama | S (CC ~10 mnt) | 2 file plus 3 pemanggil baru | **DITERIMA** | P4 DRY — alternatifnya menyalin Aturan Mutlak empat kali |
| 2 | Cache preprocessing | S-M (CC ~20 mnt) | 2 file | **TASTE DECISION** ke gate | P2 lawan P5 — jelas di blast radius, tapi di luar tulisan FR-09 |
| 3 | Kamus slang TikTok | L | file baru plus kerja manual | **DITUNDA ke TODOS.md** | P3 — tidak bisa diukur sebelum item 3 menunjukkan sisa OOV |
| 4 | Buat `TODOS.md` | XS (CC ~2 mnt) | 1 file baru | **DITERIMA** | P2 — dua dokumen merujuk file yang tidak ada; item 3 butuh tempat menaruh yang ditunda |
| 5 | Perbaiki kontradiksi design doc baris 99 | XS (CC ~2 mnt) | 1 file | **DITERIMA** | Prior learning `design-doc-can-go-stale-mid-session` — persis pola yang sudah tercatat |

## 0E. Temporal Interrogation

Skala: jam manusia; dengan CC plus gstack sekitar 10-20x lebih cepat.

```
  JAM 1 (fondasi)       Jendela negasi berapa token? Keputusan: 2 token ke depan,
                        berhenti di batas klausa. Sekarang, bukan nanti.
                        Bobot InSet dinormalisasi dibagi 5 — dikonfirmasi.

  JAM 2-3 (inti)        Tabrakan stem: rata-rata atau bobot terbesar? Keputusan:
                        rata-rata, dengan 1.550 tabrakan ditulis ke file audit.
                        Negasi plus skor nol (kata tidak ada di lexicon): jangan
                        balik nol jadi nol, tandai ambigu.

  JAM 4-5 (integrasi)   Kejutan: mengganti lexicon mengubah rasio eskalasi jauh
                        lebih besar dari dugaan siapa pun. Jalankan dry-run
                        SEBELUM menetapkan threshold apa pun. Cache preprocessing
                        menentukan apakah loop ini 15 menit atau 30.

  JAM 6 ke atas         Yang akan disesali kalau tidak direncanakan: tidak ada
  (poles/test)          test regresi yang mengunci "tidak bagus" jadi negatif.
                        Itu satu-satunya test yang membuktikan review ini berguna.
```

## 0F. Konfirmasi Mode

**SELECTIVE EXPANSION**, dengan **Approach B**. Cakupan dasar (3 item) dipegang,
plus 3 ekspansi diterima (ekstrak preprocessing, `TODOS.md`, perbaikan design doc),
1 taste decision naik ke gate (cache preprocessing), 1 ditunda (kamus slang).

## Step 0.5 — Dual Voices

Codex: **tidak tersedia** (binary tidak terpasang). Jalan `[subagent-only]`.

### CLAUDE SUBAGENT (CEO — strategic independence)

Subagent membaca plan, PRD, Architecture, design doc, kode, dan **mengukur sendiri
dataset asli**. Temuannya diverifikasi ulang secara independen sebelum dicatat di sini.

**Verifikasi angka subagent terhadap `runs/2026-08/comments.json` (dijalankan ulang):**

| Klaim subagent | Hasil verifikasi | Status |
|---|---|---|
| 6.158 komentar | 6.158 | COCOK |
| 321.636 karakter, rata-rata 52 | 321.636, rata-rata 52,2 | COCOK |
| 1.334 komentar (21,7%) berisi ≤3 kata | 1.334 (21,7%) | COCOK |
| ~11% duplikat persis | 5.496 unik dari 6.158 = 10,7% duplikat | COCOK |

Angkanya bukan retorika. Diverifikasi.

**CRITICAL 1 — Seluruh plan ini adalah penghindaran biaya untuk biaya di bawah $3/bulan,
dan angka itu tidak pernah dihitung siapa pun.**
510k token input + 92k token output untuk LLM-only sekali run. Kelas model kecil
(mini/flash): **~$0,13 per run**. Kelas Sonnet: **~$2,90 per run**. Dengan batching 25
komentar per panggilan: **~$0,02-$0,30**. Tool jalan sekali sebulan. ADR-02 menyatakan
"LLM murni mahal untuk ribuan komentar" — premis itu **diasumsikan, tidak pernah
dihitung**, dan pada skala ini kemungkinan besar salah. Naik ke Final Gate sebagai
User Challenge.

**CRITICAL 2 — Tidak ada target akurasi di mana pun dalam kelima dokumen.**
G-01 cakupan, G-02 spot-check keyword, G-04 rasio eskalasi tercatat. Tidak satu pun
berbunyi "label sentimen benar N% dari waktu". Item 3 Tahap A memilih threshold
berdasarkan *rasio eskalasi terhadap anggaran biaya* — memilih seberapa sering boleh
salah berdasarkan berapa mahal jadi benar. Tanpa definisi "cukup baik", tidak ada cara
menyatakan proyek ini selesai. Naik ke Final Gate.

**CRITICAL 3 — Ruang opsi cuma {lexicon kecil, lexicon besar, LLM}. Jawaban 2026 yang
paling jelas tidak pernah ada di meja.** Model sentimen Indonesia terlatih
(keluarga IndoBERT) jalan lokal di CPU, offline, gratis, deterministik (lebih memenuhi
NFR-03 daripada lexicon), menangani negasi dan slang secara bawaan karena dilatih di
teks sosial Indonesia. Menghapus Item 1 dan Item 3 seluruhnya.

> **Diprobe langsung:** `w11wo/indonesian-roberta-base-sentiment-classifier` → HTTP 200,
> ada. `indobenchmark/indobert-base-p1` → HTTP 200, ada.
> `mdhugol/indonesia-bert-sentiment-classifier` → HTTP 401, tidak bisa dikonfirmasi.
> **Biaya yang subagent tidak sebutkan:** `torch` dan `transformers` **belum terpasang**
> di venv ini (diprobe: keduanya `MISSING`). torch sekitar 2,5 GB. Itu dependensi berat
> masuk ke repo yang seluruh arsitekturnya dipilih dengan alasan "tanpa infra berat".
> Nyata, tapi harganya bukan nol seperti yang tersirat.

Naik ke Final Gate sebagai User Challenge.

**CRITICAL 4 — Dua sesi kerja, 315 test, lima dokumen, nol commit.**
Audit Fase 1 di atas menemukan ini lalu menuliskan "ini bukan bagian dari plan ini".
Subagent benar mengembalikannya: ini dua menit dengan nilai harapan tertinggi di seluruh
dokumen, dan dilewati demi build script lexicon. **Diangkat jadi T0, prasyarat semua
kerja lain.**

**HIGH 5 — Plan merusak lexicon demi mempertahankan aturan yang tidak berlaku untuknya.**
Item 1 men-stem 8.395 entri jadi 5.960 kunci, menggabungkan 1.550, sengaja merusak makna
(`mengawal`→`awal`), lalu mengirim `collisions.txt` sebagai mitigasi — semuanya karena
"pipeline stem sebelum lookup" dianggap tidak bisa diganggu. Tapi Aturan Mutlak
`Rules.md` mengatur **urutan tahap preprocessing**, bukan kunci mana yang dicari
`score_tokens()`. **Lookup dua-kunci** (coba token hasil filter yang belum di-stem dulu,
jatuh ke token hasil stemming kalau meleset) mempertahankan 9.074 entri InSet apa adanya
dengan bobot masing-masing, dan tidak menyentuh urutan tahap sama sekali.

**DITERIMA — mengganti Approach B jadi Approach B-prime.** Ini lebih baik daripada
rencana asli maupun rekomendasi review sendiri: presisinya lebih tinggi, kehilangan
maknanya nol, dan diff-nya tidak lebih besar. Jalur fallback masih memakai indeks
stemmed, jadi `collisions.txt` tetap ditulis untuk audit, tapi sekarang ia mengaudit
jalur cadangan, bukan satu-satunya jalur.

**HIGH 6 — Item 2 dan 3 membangun instrumentasi anggaran untuk codepath yang belum
pernah jalan sekali pun.** `analyze.py:101` butuh `LLM_MODEL` dan `LLM_API_KEY`; keduanya
kosong. `classify_via_llm` belum pernah mengembalikan respons nyata, jadi tidak ada yang
tahu apakah router pilihan user menghasilkan JSON yang bisa di-parse. Dry-run akan
melaporkan jumlah token tanpa harga, dan kalibrasi akan menyetel anggaran dalam mata uang
yang belum ada. **Diterima — jadi T2, satu panggilan API nyata dengan 20 komentar
sebelum item 2 dan 3 dikerjakan.**

**HIGH 7 — Dua aturan penggabungan berbeda tanpa dasar, di artefak beku yang akan
di-commit.** Aturan D menjumlahkan konflik pos/neg (1.142 kata); aturan tabrakan stem
merata-ratakan (1.550 stem). Tidak konsisten, tidak dijelaskan, dan bobot InSet adalah
hitungan anotator, bukan magnitudo terkalibrasi. **Diterima sebagian** — dengan
B-prime, jalur utama tidak lagi menggabungkan apa pun (kunci mentah dipertahankan
apa adanya), jadi masalah ini menyusut ke indeks fallback saja. Aturan diseragamkan
jadi rata-rata di kedua tempat, dan alasannya ditulis di `SOURCE.md`.

**HIGH 8 — Sampel Tahap B tidak sanggup menjawab pertanyaannya sendiri.**
200 komentar dibaca per band skor × bucket OOV, dengan grid 5×6 = 30 sel, berarti ~7
komentar per sel. Interval kepercayaan lebih lebar dari keputusannya.
**Diterima.** Keputusan terbuka "200 vs 500" salah rumus. Yang benar: 200 sampel
menghasilkan **satu angka akurasi keseluruhan** (itu sah dan berguna), dan klaim
akurasi per-band dicoret dari cakupan. Tanpa ini, Tahap B menghasilkan angka yang
terlihat presisi dan tidak berarti.

**HIGH 9 — Bentuk data nyata mematahkan asumsi scorer.**
1.334 komentar (21,7%) berisi ≤3 kata. Setelah filter stopword, seperlima korpus tersisa
0-2 token. `score_tokens()` merata-ratakan token yang cocok, jadi komentar satu kata yang
kena satu entri lexicon mendapat bobot penuh kata itu dan `confidence = 1.0`.
`oov_ratio` jadi bimodal (0,0 atau 1,0), bukan distribusi yang bisa disapu threshold
0,3-0,8. **Diterima** — sapuan Item 3 harus melaporkan komentar pendek dan panjang
secara terpisah, kalau tidak ia menyapu distribusi degenerate dan menghasilkan
threshold yang tidak berarti untuk keduanya. Ditambah: dedup 10,7% memangkas kerja
hilir gratis.

**MEDIUM 10 — Penambal negasi akan disangka perbaikan.**
Jendela negasi 1-2 token plus satu test regresi tidak menyentuh `kurang bagus`,
`agak mahal`, `bagus tapi mahal` (dua-duanya cocok, rata-rata ~0, jatuh netral), atau
sentimen yang dibawa emoji (`extract_emoji` mencabut emoji sebelum scoring dan tidak
ada yang pernah menilainya). Tapi akan ada test hijau bernama "tidak bagus negatif"
yang orang tunjuk sebagai bukti negasi sudah beres. **Diterima sebagai batas eksplisit
yang harus tertulis**, bukan sebagai alasan tidak menambal.

**MEDIUM 11 — `--escalation-budget 20%` tidak berlabuh ke apa pun.** Bukan dari angka
biaya (tidak ada), bukan dari angka akurasi (tidak ada). Diterima; menyatu dengan
CRITICAL 2.

**MEDIUM 12 — Risiko kompetitif adalah laptop analis itu sendiri.**
Substitusinya: satu orang menempel CSV 320 KB ke ChatGPT/Gemini/Claude dan dapat rincian
sentimen dalam lima menit. Pipeline ini menawarkan 15 menit preprocessing, 30 menit kalau
dry-run dulu, PR manual pelabelan, dan laporan yang akurasinya tidak diketahui. Untuk
tool internal satu pengguna, adopsi oleh satu orang itu adalah seluruh pasarnya.
Risiko sekunder: scraper adalah fork; TikTok rutin mematahkan scraper; tidak ada rencana
kepemilikan untuk dependensi hulu itu di dokumen mana pun.

**MEDIUM 13 — Separuh produk yang lebih bernilai tidak dapat perhatian sama sekali.**
PRD §2 menyatakan kebutuhannya "bukan sekadar hitung persentase" tapi menangkap
*messaging*. TF-IDF di atas token yang sudah di-stem belum pernah direview kualitasnya:
stemming merusak keterbacaan keyword yang justru harus dibaca analis
(`pengembangan`→`kembang`), dan tabrakan stem menggabungkan topik yang berbeda. Tiga item
usaha pergi ke persentase sentimen; ekstraksi topik — bagian yang mungkin justru
ditindaklanjuti analis — tidak disentuh dan tidak divalidasi. **Diterima ke TODOS.md
sebagai P2.**

### CEO DUAL VOICES — CONSENSUS TABLE

```
CEO DUAL VOICES — CONSENSUS TABLE:
═══════════════════════════════════════════════════════════════
  Dimension                            Claude  Codex  Consensus
  ──────────────────────────────────── ─────── ────── ─────────
  1. Premises valid?                   NO      N/A    single-voice CRITICAL
  2. Right problem to solve?           NO      N/A    single-voice CRITICAL
  3. Scope calibration correct?        NO      N/A    single-voice HIGH
  4. Alternatives sufficiently explored? NO    N/A    single-voice CRITICAL
  5. Competitive/market risks covered? NO      N/A    single-voice MEDIUM
  6. 6-month trajectory sound?         PARTIAL N/A    single-voice MEDIUM
═══════════════════════════════════════════════════════════════
Codex tidak tersedia — tidak ada baris yang bisa CONFIRMED.
Aturan yang berlaku: "Single critical finding from one voice = flagged regardless."
4 temuan CRITICAL dari satu suara, tiga di antaranya diverifikasi ulang secara
independen terhadap data dan jaringan. Ditandai, bukan diabaikan.
```

### CROSS-MODEL TENSION

```
CROSS-MODEL TENSION:
  Stemming lexicon: Review bilang stem kunci InSet saat build (5.960 kunci, 1.550
  tabrakan, makna sebagian rusak). Outside voice bilang jangan sentuh lexicon —
  pakai lookup dua-kunci, pertahankan 9.074 entri utuh. Outside voice menang: ia
  menunjukkan Aturan Mutlak yang review anggap mengikat ternyata mengatur urutan
  tahap, bukan kunci lookup. Review mengukur masalahnya dengan teliti lalu tidak
  pernah menggugat constraint yang menyebabkannya.

  Nilai lapisan lexicon: Review menerima ADR-02 sebagai keputusan user yang tidak
  dibuka ulang. Outside voice menghitung premisnya dan mendapati premis itu salah
  di skala ini. Keduanya benar pada porsinya: menghormati keputusan user itu benar,
  tapi menghormati keputusan yang premisnya terbukti salah tanpa memberi tahu user
  bukan penghormatan, itu penyembunyian. Konteks yang mungkin luput dari kami
  berdua: user bisa saja punya alasan non-biaya untuk ADR-02 (kedaulatan data,
  keandalan tanpa jaringan, kebijakan kantor) yang tidak pernah tertulis. Naik ke
  gate, tidak diputuskan sendiri.
```

## Section 1: Architecture Review

### Diagram arsitektur setelah plan ini

```
  comments.json
       |
       v
  ingest.tiktok_adapter (flatten, validasi skema)
       |
       v
  filters.exclude_accounts (FR-02 manual + FR-11 uploader)
       |
       v
  preprocessing.pipeline  <-- BARU (diekstrak dari cli/analyze.py)
       |  emoji > case_fold > clean > normalize > tokenize > filter > stem
       |  mengembalikan DUA daftar token: tokens_filtered + tokens_stemmed
       |
       +----------------------------> cache preprocessing (TASTE, ke gate)
       |
       v
  sentiment.lexicon_classifier.score_tokens  <-- DIUBAH
       |  lookup dua-kunci: tokens_filtered lalu fallback tokens_stemmed
       |  negasi: balik tanda token dalam jendela setelah kata negasi
       |
       v
  sentiment.hybrid.is_ambiguous ---(ambigu)---> llm_classifier ---> router LLM
       |                                                              (belum
       | (jelas)                                                       pernah
       v                                                               jalan)
  keywords.tfidf_extractor --> output.serializer --> analysis_result.json
                                                            |
                                                            v
                                                     report.html_builder

  Jalur baru yang tidak menulis analysis_result.json:
  preprocessing.pipeline --> hybrid.is_ambiguous --> laporan dry-run (FR-09)
  preprocessing.pipeline --> sapuan threshold      --> tabel kalibrasi
```

### Empat jalur data untuk `score_tokens()` yang diubah

```
  HAPPY   tokens=['tidak','bagus']  lexicon punya 'bagus'
          -> negasi terdeteksi, tanda dibalik -> -0.8 -> negatif. BENAR.

  NIL     tokens=None
          -> GAP SEKARANG: score_tokens() melakukan `if not tokens` yang
             menangkap None dan [] sekaligus, mengembalikan (0.0, 0.0).
             Tidak crash. Aman, tapi None dan [] tidak dibedakan di log.

  EMPTY   tokens=[]  (komentar emoji-only setelah filter stopword)
          -> (0.0, 0.0) -> netral, confidence 1.0.
             GAP: komentar tanpa token apa pun keluar sebagai "netral dengan
             keyakinan penuh". Seharusnya ditandai ambigu, bukan netral yakin.
             21,7% korpus adalah komentar <=3 kata, jadi ini sering.

  ERROR   lexicon gagal dimuat (file hilang/rusak)
          -> load_lexicon() melempar dari open(); tidak ada rescue di analyze.py.
             GAP: exit dengan traceback Python, bukan pesan yang bisa dibaca.
```

### Coupling

Sebelum: `cli/analyze.py` memiliki `_preprocess()` secara privat. Sesudah:
`preprocessing/pipeline.py` dipakai bersama CLI dan 3 skrip. Coupling naik satu
tingkat dan itu **dibenarkan** — alternatifnya adalah empat salinan urutan tahap yang
`Rules.md` sebut tidak boleh menyimpang.

### Scaling

10x (60 ribu komentar): stemming ~2,5 jam. Di luar toleransi NFR-01, tapi di luar
skenario nyata (200 video/bulan). 100x: butuh keputusan arsitektur baru, bukan
penyetelan. Tidak diselesaikan sekarang, dicatat.

### Single point of failure

Scraper hulu adalah fork dari repo pihak ketiga terhadap platform yang rutin mematahkan
scraper. Kalau ingest mati, seluruh pipeline sentimen tidak ada gunanya. Tidak ada
monitoring, tidak ada pemilik, tidak disebut di dokumen mana pun. **Dicatat ke TODOS.md.**

### Rollback

Semua kerja plan ini aditif kecuali dua: default `--lexicon-config` dan perubahan
`score_tokens()`. Rollback = `git revert` satu commit. Tidak ada migrasi, tidak ada
state. Reversibility tinggi.

**Temuan Section 1: 3** (empty-token gap, lexicon-load error gap, SPOF hulu tanpa pemilik).

## Section 2: Error & Rescue Map

```
  METHOD/CODEPATH                  | WHAT CAN GO WRONG              | EXCEPTION CLASS
  ---------------------------------|--------------------------------|------------------
  build_lexicon.py (BARU)          | TSV InSet tidak ada / URL mati | FileNotFoundError / HTTPError
                                   | bobot bukan angka              | ValueError
                                   | file output tidak bisa ditulis | PermissionError
  score_tokens (DIUBAH)            | tokens kosong                  | (tidak ada - lihat GAP)
                                   | lexicon kosong                 | (tidak ada - lihat GAP)
  load_lexicon                     | CSV hilang/rusak               | FileNotFoundError
  dry_run (BARU)                   | cache preprocessing rusak      | JSONDecodeError
                                   | flag tarif negatif             | (tidak ada - lihat GAP)
  calibrate_thresholds.py (BARU)   | CSV label kosong               | (tidak ada - lihat GAP)
                                   | label tidak dikenal            | (tidak ada - lihat GAP)
  classify_via_llm (ADA)           | router balas non-JSON          | ditangkap Exception luas
                                   | router balas label asing       | ValueError, di-retry
                                   | router menolak (refusal)       | ditangkap Exception luas
  ---------------------------------|--------------------------------|------------------

  EXCEPTION CLASS        | RESCUED? | RESCUE ACTION                | USER SEES
  -----------------------|----------|------------------------------|---------------------------
  FileNotFoundError      | N  GAP   | -                            | traceback Python  BURUK
  (lexicon/TSV)          |          |                              |
  ValueError (bobot)     | Y        | lewati baris, warning         | jumlah baris dilewati
  JSONDecodeError        | N  GAP   | -                            | traceback Python  BURUK
  (cache)                |          |                              |
  tokens kosong          | N  GAP   | -                            | "netral, confidence 1.0"
                         |          |                              | DIAM-DIAM SALAH
  tarif negatif          | N  GAP   | -                            | estimasi biaya negatif
  label manual tidak     | N  GAP   | -                            | crash atau dihitung salah
  dikenal                |          |                              |
  Exception (LLM)        | Y        | retry 2x lalu llm_failed      | dicatat, batch lanjut
```

**GAP kritis: `tokens` kosong menghasilkan "netral, confidence 1.0".** Ini pelanggaran
Prime Directive 1 (nol kegagalan diam-diam) dan mengenai 21,7% korpus. Perbaikan:
daftar token kosong mengembalikan sinyal ambigu, bukan netral yakin — biarkan LLM
memutuskan atau tandai `tidak_terklasifikasi`.

**Temuan Section 2: 6 GAP**, 1 di antaranya kritis.

## Section 3: Security & Threat Model

| Ancaman | Kemungkinan | Dampak | Dimitigasi plan? |
|---|---|---|---|
| Build script mengunduh TSV dari GitHub lewat jaringan lalu di-commit | Med | Med | **Sebagian.** Mitigasi: skrip default membaca path lokal; unduhan butuh flag eksplisit; `SOURCE.md` mencatat commit hash sehingga isi bisa diverifikasi ulang. |
| Prompt injection lewat teks komentar ke `classify_via_llm` | Med | Low | **Tidak dimitigasi, dan tidak diperburuk plan ini.** Komentar TikTok dikirim mentah sebagai `user` message. Model bisa dibujuk mengembalikan label pilihan penyerang. Dampaknya satu label salah di laporan internal — rendah. Dicatat, tidak ditutup. |
| Kredensial LLM bocor ke laporan dry-run | Low | High | **Ditutup.** Laporan dry-run mencatat `llm_base_url` dan `llm_model`, tidak pernah `LLM_API_KEY`. Wajib jadi test. |
| CSV kalibrasi berisi username asli, ditulis ke `runs/` | Med | Low | `.gitignore` sudah menutup `runs/`. Diverifikasi. |
| Dependensi baru | — | — | Plan ini menambah **nol** dependensi runtime. (Jalur IndoBERT akan menambah torch, ~2,5 GB — bagian dari User Challenge, bukan cakupan sekarang.) |

**Temuan Section 3: 2** (unduhan build script, prompt injection dicatat-tidak-ditutup),
nol severity High yang belum dimitigasi.

## Section 4: Data Flow & Interaction Edge Cases

```
  INPUT ────▶ VALIDASI ────▶ TRANSFORM ────▶ SKOR ────▶ OUTPUT
    │             │              │             │           │
    ▼             ▼              ▼             ▼           ▼
  [nil?]      [skema     ]   [emoji-only?] [0 token?]  [semua
  [kosong?]   [salah -> 2]   [<=3 kata?]   [OOV 1.0?]   netral?]
  [duplikat?] [id hilang ]   [stem gagal?] [negasi   ]  [ada
                                           [menggantung] label?]
```

| Interaksi | Edge case | Ditangani? | Bagaimana |
|---|---|---|---|
| `analyze --dry-run` | dijalankan tanpa `LLM_API_KEY` | **Ya, sengaja** | Justru ini kasus utamanya — dry-run tidak butuh key |
| `analyze --dry-run` | dijalankan bersama `--output` yang sudah ada | **GAP** | Harus menolak menimpa `analysis_result.json`; sekarang belum ditentukan |
| `analyze` (normal) | dijalankan setelah dry-run, cache basi | **GAP** (kalau cache diterima) | Cek hash; hash beda = abaikan cache |
| Sapuan kalibrasi | data 0 komentar setelah exclude | **GAP** | Bagi nol di persentase sapuan |
| Sampling kalibrasi | band skor tidak berisi komentar apa pun | **GAP** | Sampling berstrata harus melewati band kosong, bukan gagal |
| Skoring kalibrasi | analis mengisi label campur huruf besar | **GAP** | Normalisasi case sebelum bandingkan |
| Komentar duplikat (10,7%) | dihitung berkali-kali di TF-IDF dan sapuan | **GAP** | Dedup sebelum sapuan, atau angkanya condong ke komentar yang disalin-tempel |

**Temuan Section 4: 6 gap belum ditangani.**

## Section 5: Code Quality Review

- **DRY:** pelanggaran terbesar sudah ditangkap di 0D — `_preprocess()` akan disalin tiga
  kali kalau tidak diekstrak. Diterima jadi cakupan.
- **Penamaan:** `score_tokens()` akan mengembalikan tiga nilai setelah negasi masuk
  (skor, oov_ratio, negasi menggantung). Nama masih benar. Tidak berubah.
- **Over-engineering:** tidak ada abstraksi baru. Tiga skrip adalah skrip, bukan kelas.
- **Under-engineering:** `score_tokens()` merata-ratakan token yang cocok tanpa peduli
  panjang komentar. Untuk komentar 1 kata, rata-rata itu adalah kata itu sendiri dengan
  confidence 1.0. Itu asumsi happy-path terhadap 21,7% data. Ditangkap di Section 2.
- **Kompleksitas siklomatik:** jendela negasi menambah 2-3 cabang ke `score_tokens()`.
  Masih di bawah 5. Aman.
- **Deviasi pola:** `scripts/` adalah direktori baru di repo yang belum punya. Repo pakai
  `main.py`/`batch.py`/`sample.py` di root. **Ikuti pola yang ada** — taruh skrip sebagai
  modul di bawah `sosmed_sentiment/tools/` yang bisa dipanggil `python -m`, konsisten
  dengan `cli/`, bukan direktori `scripts/` baru.

**Temuan Section 5: 2** (lokasi skrip menyimpang dari pola repo, under-engineering
komentar pendek).

## Section 6: Test Review

```
  CODEPATH BARU:
    - build lexicon: parse TSV, buang multi-kata, strip kurung, gabung
      konflik pos/neg, bangun indeks stemmed fallback, tulis CSV
    - score_tokens: lookup dua-kunci (raw hit / stemmed hit / dua-duanya meleset)
    - score_tokens: deteksi negasi (dalam jendela / di luar jendela / negasi
      menggantung tanpa kata bersentimen sesudahnya / negasi ganda)
    - dry-run: hitung eskalasi, pecah alasan, estimasi token, estimasi biaya
    - kalibrasi: histogram, sapuan grid, pilih rekomendasi
    - sampling: stratifikasi, seed tetap, lewati band kosong
    - skoring kalibrasi: baca label, akurasi keseluruhan

  INTEGRASI EKSTERNAL BARU:
    - unduhan TSV InSet (opsional, flag eksplisit)

  JALUR ERROR BARU:
    - 6 GAP dari Section 2

  ALUR UX BARU:
    - flag CLI --dry-run, --dry-run-report, --price-per-1m-input/output
```

| Yang diuji | Happy | Failure | Edge |
|---|---|---|---|
| Lookup dua-kunci | raw hit menang atas stemmed | dua-duanya meleset -> OOV | raw dan stemmed beda skor -> raw menang |
| Negasi | `tidak bagus` -> **negatif** | negasi menggantung -> tandai ambigu | `tidak tidak bagus` -> jangan balik dua kali diam-diam |
| Token kosong | — | `[]` -> ambigu, BUKAN netral 1.0 | komentar emoji-only end-to-end |
| Dry-run | rasio eskalasi benar | tanpa flag tarif -> laporan tetap terbit | **nol panggilan LLM walau `LLM_API_KEY` terisi** |
| Build lexicon | fixture kecil -> CSV benar | TSV rusak -> pesan jelas | konflik pos/neg, tabrakan stem, entri berkurung |
| Sapuan kalibrasi | grid benar untuk skor sintetis | 0 komentar -> bukan bagi nol | komentar pendek vs panjang dilaporkan terpisah |

**Test yang membuat berani rilis jam 2 pagi Jumat:** `tidak bagus` menghasilkan
`negatif`, dijalankan terhadap lexicon InSet asli, bukan fixture. Kalau test itu hijau,
temuan terpenting review ini benar-benar tertutup. Kalau tidak ada, review ini cuma prosa.

**Test yang ditulis QA yang bermusuhan:** jalankan `--dry-run` dengan `LLM_API_KEY` dan
`LLM_MODEL` terisi valid, lalu tegaskan nol permintaan HTTP keluar. Dry-run yang
diam-diam memanggil API adalah kegagalan yang persis dirancang untuk dicegah FR-09.

**Risiko flaky:** unduhan TSV InSet bergantung jaringan. Test harus memakai fixture
lokal; unduhan diuji terpisah dan ditandai boleh dilewati saat offline.

**Temuan Section 6: 0 gap** — rencana test menutup setiap codepath baru. Ini bukan
"tidak diperiksa"; tabel di atas adalah pemeriksaannya.

## Section 7: Performance Review

- Build lexicon: ~4 menit sekali seumur hidup (terukur 233 detik untuk 8.395 kata).
  Bukan biaya runtime.
- Lookup dua-kunci: satu pencarian dict tambahan per token yang meleset. Nol dampak
  terukur dibanding stemming yang mendominasi 99,98%.
- Jendela negasi: satu lintasan linear atas token per komentar. Nol dampak.
- Dry-run tanpa cache: menggandakan waktu siklus dari ~15 jadi ~30 menit. **Ini
  satu-satunya temuan performa nyata**, dan perbaikannya adalah taste decision yang naik
  ke gate.
- Memori: lexicon 9.074 entri plus indeks stemmed 5.960 = di bawah 1 MB. Tidak ada isu.

**Temuan Section 7: 1** (siklus dry-run ganda tanpa cache).

## Section 8: Observability & Debuggability Review

| Kebutuhan | Ada? | Aksi |
|---|---|---|
| Build lexicon mencatat entri masuk/dibuang/digabung | Belum | Wajib. Tanpa ini nobody tahu apa yang hilang saat build. |
| Rasio eskalasi tercatat per run | **Sudah** (`analyze.py` ringkasan run) | Tidak berubah |
| Berapa komentar dinilai lewat raw vs fallback stemmed | Belum | **Tambahkan.** Ini metrik yang memberi tahu apakah lookup dua-kunci benar-benar berguna, dan satu-satunya cara membuktikan HIGH 5 benar setelah dirilis. |
| Berapa komentar terpengaruh pembalikan negasi | Belum | **Tambahkan.** Kalau angkanya nol di data nyata, seluruh temuan CRITICAL review ini teoretis dan harus diakui begitu. |
| Berapa komentar berakhir dengan 0 token | Belum | **Tambahkan.** Langsung mengukur GAP kritis Section 2. |
| Versi lexicon tercatat di output | **Sudah** (`meta.config_used`) | Perbarui nilainya |
| Bisa merekonstruksi run 3 minggu kemudian dari log saja | Sebagian | `analysis_result.json` menyimpan `config_used`; ditambah tiga metrik di atas jadi cukup |

**Temuan Section 8: 4 gap**, semuanya baris log satu-satu, semuanya diterima ke cakupan.
Tiga di antaranya adalah instrumentasi yang **membuktikan atau membantah temuan review
ini sendiri** setelah dirilis. Itu observability yang benar: bukan cuma melihat sistem,
tapi melihat apakah alasan kita membangunnya masih berlaku.

## Section 9: Deployment & Rollout Review

Tidak ada server, tidak ada migrasi, tidak ada feature flag, tidak ada staging. "Deploy"
di sini berarti "analis menarik perubahan dan menjalankan CLI bulan depan".

- **Urutan:** commit dulu (T0), baru semua yang lain. Bukan formalitas — sekarang tidak
  ada satu pun commit yang menyelamatkan kerja ini.
- **Rollback:** `git revert`. Satu commit. Detik, bukan menit.
- **Risiko jendela deploy:** nol. Tidak ada kode lama dan baru jalan bersamaan.
- **Verifikasi pasca-deploy:** jalankan `--dry-run` di `runs/2026-08/comments.json`,
  bandingkan rasio eskalasi dengan angka yang dicatat review ini. Kalau menyimpang jauh,
  ada yang salah dengan build lexicon.
- **Smoke test:** `pytest` (315 test yang sudah ada harus tetap hijau — ini pagar
  regresi terpenting, karena `score_tokens()` dipakai bersama dua jalur klasifikasi).

**Temuan Section 9: 0.** Diperiksa: urutan, rollback, jendela deploy, verifikasi. Profil
risiko rilis proyek ini rendah karena tidak ada yang berjalan terus-menerus. Nol temuan
di sini benar, bukan malas.

## Section 10: Long-Term Trajectory Review

- **Utang teknis yang ditambahkan:** `config/lexicon_inset.csv` menjadi artefak beku
  yang di-commit dan hampir pasti tidak akan pernah diturunkan ulang. Kalau aturan
  penggabungannya salah, kesalahan itu ikut selamanya. Mitigasi: `SOURCE.md` plus
  build script yang deterministik dan bisa dijalankan ulang.
- **Ketergantungan jalur:** menambal bag-of-words satu fenomena linguistik pada satu
  waktu (negasi sekarang, intensifier nanti, klausa kontras setelahnya) adalah treadmill
  yang subagent identifikasi benar. Setiap tambalan mempersulit peralihan ke model
  terlatih nanti, karena tiap tambalan punya test yang membelanya.
- **Reversibility: 4/5.** Semua aditif kecuali dua baris; `git revert` mengembalikan.
  Bukan 5 karena `config/lexicon_inset.csv` yang di-commit akan bertahan di histori.
- **Pertanyaan 1 tahun:** insinyur baru membaca `sosmed_sentiment/` dalam 12 bulan akan
  bertanya "kenapa lexicon buatan tangan padahal ada model Indonesia terlatih?" Plan ini,
  apa adanya, tidak punya jawaban tertulis untuk itu. **Setelah gate, jawabannya harus
  ditulis** — entah "kami mengukur dan lexicon menang", atau "kami memilih lexicon karena
  X", tapi bukan diam.
- **Retrospektif cherry-pick:** ekstraksi `_preprocess()` yang diterima ternyata
  load-bearing untuk tiga skrip DAN untuk cache yang ditunda ke gate. Keputusan yang
  benar. Kamus slang yang ditunda tetap benar ditunda — Tahap B akan memberi tahu
  seberapa besar sisa OOV sebelum ada yang menulis satu entri pun.

**Temuan Section 10: 2** (artefak beku, ketergantungan jalur treadmill).

## Section 11: Design & UX Review

**SKIPPED — tidak ada UI scope.** Diperiksa: plan tidak menyentuh `report/html_builder.py`
maupun `templates/report.html.j2`. Satu-satunya kecocokan kata UI adalah `form` di dalam
kata "format". Tidak ada layar, komponen, atau alur interaksi yang berubah.

## Required Outputs (Fase 1)

### NOT in scope

| Item | Alasan ditunda/ditolak |
|---|---|
| Mem-parallelkan atau mengganti stemming Sastrawi | Ditutup sebagai keputusan sadar user 2026-08-30 (`PRD.md` NFR-01 v0.5): dipakai 1x/bulan, 15 menit murah. |
| Kamus slang TikTok buatan sendiri | Tidak bisa diukur nilainya sebelum Tahap B menunjukkan sisa OOV. Ke TODOS.md. |
| Review kualitas ekstraksi keyword TF-IDF | Nyata dan bernilai (CEO voice MEDIUM 13), tapi cakupan terpisah dari tiga item ini. Ke TODOS.md P2. |
| Menutup prompt injection lewat teks komentar | Dampak = satu label salah di laporan internal. Dicatat, tidak ditutup di v1. |
| Monitoring scraper hulu (fork, TikTok rutin patah) | SPOF nyata di luar cakupan pipeline sentimen. Ke TODOS.md. |
| Menangani intensifier, klausa kontras, sarkasme, sentimen emoji | Batas eksplisit dari tambalan negasi. Ditulis sebagai limitasi, bukan dikerjakan. |
| Model sentimen Indonesia terlatih (IndoBERT) | **Bukan ditolak — dinaikkan ke Final Gate sebagai User Challenge.** Bukan keputusan yang boleh diambil review. |
| Membuka ulang ADR-02 (hybrid vs LLM-only) | **Bukan ditolak — dinaikkan ke Final Gate sebagai User Challenge.** |
| Klaim akurasi per-band dari sampel 200 | Dicoret: n≈7 per sel, interval kepercayaan lebih lebar dari keputusannya. |

### What already exists

Lihat tabel 0B. Ringkas: `load_lexicon()`, `get_lexicon()`, `load_threshold_config()`,
`load_stopwords()`, `is_ambiguous()`, `stem()` dengan `lru_cache`, `NEGATION_WORDS`,
`SLANG_MAP` semuanya dipakai ulang apa adanya. Nol dibangun ulang. Satu-satunya
ekstraksi adalah `_preprocess()` dari privat CLI ke modul bersama.

### Dream state delta

Setelah plan ini (dengan B-prime dan gate diselesaikan): lexicon nyata dengan lookup
dua-kunci, negasi dihitung, biaya LLM terlihat sebelum dibelanjakan, threshold dipilih
dari distribusi terukur plus satu angka akurasi keseluruhan.

Yang masih memisahkan dari ideal 12 bulan: tidak ada target akurasi (naik ke gate),
tidak ada akurasi per-band (tidak layak dengan kerja manual), slang belum ditutup,
kualitas keyword belum divalidasi, dan pertanyaan terlatih-vs-lexicon belum dijawab
dengan pengukuran.

### Failure Modes Registry

```
  CODEPATH                  | FAILURE MODE              | RESCUED? | TEST? | USER SEES?      | LOGGED?
  --------------------------|---------------------------|----------|-------|-----------------|--------
  score_tokens              | 0 token -> netral conf 1.0| N        | N     | Diam-diam salah | N   <-- CRITICAL GAP
  score_tokens              | negasi diabaikan          | N        | N     | Label terbalik  | N   <-- CRITICAL GAP
                            | (kondisi sekarang)        |          |       | conf 1.0        |
  load_lexicon              | CSV hilang/rusak          | N        | N     | Traceback       | N   <-- GAP
  build_lexicon             | TSV InSet hilang          | N        | N     | Traceback       | N   <-- GAP
  dry_run                   | cache rusak               | N        | N     | Traceback       | N   <-- GAP
  dry_run                   | flag tarif negatif        | N        | N     | Biaya negatif   | N   <-- GAP
  dry_run                   | menimpa analysis_result   | N        | N     | Hasil palsu     | N   <-- GAP
  calibrate                 | 0 komentar -> bagi nol    | N        | N     | Traceback       | N   <-- GAP
  calibrate                 | label manual tak dikenal  | N        | N     | Dihitung salah  | N   <-- GAP
  sample_for_labeling       | band skor kosong          | N        | N     | Traceback       | N   <-- GAP
  classify_via_llm          | router balas non-JSON     | Y        | Y     | llm_failed      | Y
  classify_via_llm          | >10% eskalasi gagal       | Y        | Y     | exit 3          | Y
  flatten_input             | skema salah               | Y        | Y     | exit 2 + ID     | Y
  --------------------------|---------------------------|----------|-------|-----------------|--------
```

**10 GAP, 2 di antaranya CRITICAL** (keduanya di `score_tokens`, keduanya membuat
label salah tanpa jejak apa pun). Tiga baris terakhir menunjukkan kode yang sudah ada
menangani kegagalannya dengan benar — pola itu yang harus diikuti kode baru.

### TODOS.md (diusulkan — file belum ada, pembuatannya diterima di 0D)

| # | Item | Effort | Prioritas | Bergantung pada |
|---|---|---|---|---|
| 1 | Kamus slang TikTok di atas InSet | L → M (CC) | P3 | Tahap B menunjukkan sisa OOV |
| 2 | Review kualitas ekstraksi keyword TF-IDF (stem merusak keterbacaan, tabrakan menggabung topik) | M → S (CC) | P2 | — |
| 3 | Pemilik + monitoring untuk scraper hulu (fork, risiko patah TikTok) | S | P2 | — |
| 4 | Tutup prompt injection di jalur LLM | S | P3 | LLM benar-benar dipakai |
| 5 | Intensifier / klausa kontras / sentimen emoji | M | P3 | Keputusan gate soal lexicon vs model |

### Diagrams produced

1. Arsitektur sistem (Section 1)
2. Data flow empat jalur untuk `score_tokens()` (Section 1)
3. Shadow path INPUT→VALIDASI→TRANSFORM→SKOR→OUTPUT (Section 4)
4. Dream state CURRENT→PLAN→IDEAL (0C)
5. Temporal HOUR 1→6+ (0E)

### Stale Diagram Audit

Diperiksa `docs/Architecture.md` §1 (diagram alur dua modul) — masih akurat, plan ini
tidak mengubah bentuk dua-CLI-lewat-JSON. **Satu artefak basi ditemukan, bukan diagram:**
`docs/designs/sentiment-pipeline-design.md:99` masih mengklaim FR-11 butuh panggilan API
video-detail, bertentangan dengan baris 42 di file yang sama. Perbaikan sudah diterima
ke cakupan di 0D.

## Implementation Tasks — Fase 1 (CEO)

- [ ] **T0 (P1, human: ~2 mnt / CC: ~2 mnt)** — repo — Commit seluruh kerja yang belum di-track
  - Surfaced by: Audit Sistem + CEO voice CRITICAL 4 — 315 test dan 5 dokumen ada di working tree, nol di git
  - Files: seluruh working tree
  - Verify: `git log --stat -1` menunjukkan `sosmed_sentiment/` ter-commit
- [ ] **T1 (P1, human: ~4j / CC: ~25mnt)** — sentiment — Tangani negasi di `score_tokens()`
  - Surfaced by: 0A Premise Challenge — `['tidak','bagus']` menghasilkan positif confidence 1.0
  - Files: `sosmed_sentiment/sentiment/lexicon_classifier.py`, `tests/sosmed_sentiment/sentiment/`
  - Verify: `pytest -k negation` dan `tidak bagus` menghasilkan `negatif` terhadap lexicon InSet asli
- [ ] **T2 (P1, human: ~30mnt / CC: ~10mnt)** — llm — Satu panggilan router nyata dengan 20 komentar
  - Surfaced by: CEO voice HIGH 6 — `classify_via_llm` belum pernah mengembalikan respons nyata
  - Files: tidak ada (probe operasional); catat hasilnya di plan
  - Verify: JSON yang bisa di-parse kembali dari router, dan baris tagihan nyata tercatat
- [ ] **T3 (P1, human: ~1h / CC: ~10mnt)** — preprocessing — Ekstrak `_preprocess()` ke `preprocessing/pipeline.py`, kembalikan token filtered DAN stemmed
  - Surfaced by: 0D cherry-pick 1 + CEO voice HIGH 5 (lookup dua-kunci butuh keduanya)
  - Files: `sosmed_sentiment/preprocessing/pipeline.py`, `sosmed_sentiment/cli/analyze.py`
  - Verify: `pytest` 315 test tetap hijau
- [ ] **T4 (P1, human: ~4j / CC: ~30mnt)** — lexicon — Build InSet dengan lookup dua-kunci
  - Surfaced by: Item 1 + CEO voice HIGH 5 — pertahankan 9.074 entri, jangan turunkan ke 5.960
  - Files: `sosmed_sentiment/tools/build_lexicon.py`, `config/lexicon_inset.csv`, `config/lexicon_inset.SOURCE.md`
  - Verify: test smoke lexicon; metrik raw-hit vs stemmed-hit tercatat di run
- [ ] **T5 (P1, human: ~2j / CC: ~15mnt)** — sentiment — Token kosong menghasilkan ambigu, bukan netral confidence 1.0
  - Surfaced by: Section 2 CRITICAL GAP — mengenai 21,7% korpus
  - Files: `sosmed_sentiment/sentiment/lexicon_classifier.py`
  - Verify: komentar emoji-only end-to-end tidak menghasilkan "netral 1.0"
- [ ] **T6 (P2, human: ~3j / CC: ~20mnt)** — cli — FR-09 `--dry-run`
  - Surfaced by: Item 2
  - Files: `sosmed_sentiment/cli/analyze.py`
  - Verify: test bermusuhan — `LLM_API_KEY` terisi, nol permintaan HTTP keluar
- [ ] **T7 (P2, human: ~2j / CC: ~15mnt)** — observability — 3 metrik baru (raw vs stemmed hit, komentar terbalik negasi, komentar 0 token)
  - Surfaced by: Section 8 — instrumentasi yang membuktikan atau membantah temuan review ini
  - Files: `sosmed_sentiment/cli/analyze.py`, `sosmed_sentiment/output/serializer.py`
  - Verify: ketiga angka muncul di ringkasan run dan di `meta`
- [ ] **T8 (P2, human: ~4j / CC: ~30mnt)** — kalibrasi — Sapuan threshold, dipisah komentar pendek vs panjang, plus dedup
  - Surfaced by: Item 3 + CEO voice HIGH 9 — `oov_ratio` bimodal di komentar pendek
  - Files: `sosmed_sentiment/tools/calibrate_thresholds.py`
  - Verify: sapuan menghasilkan tabel benar untuk skor sintetis; 0 komentar bukan bagi nol
- [ ] **T9 (P2, human: ~2j / CC: ~15mnt)** — kalibrasi — Sampling berstrata + skoring label (satu angka akurasi keseluruhan)
  - Surfaced by: Item 3 Tahap B + CEO voice HIGH 8 — klaim per-band dicoret
  - Files: `sosmed_sentiment/tools/sample_for_labeling.py`, `sosmed_sentiment/tools/score_calibration.py`
  - Verify: seed sama menghasilkan sampel sama; label tidak dikenal jadi warning, bukan crash
- [ ] **T10 (P2, human: ~1j / CC: ~10mnt)** — errors — Tutup 8 GAP non-kritis dari Failure Modes Registry
  - Surfaced by: Section 2, Section 4
  - Files: seluruh modul baru
  - Verify: tiap GAP punya satu test
- [ ] **T11 (P3, human: ~10mnt / CC: ~3mnt)** — docs — Buat `TODOS.md`, perbaiki `sentiment-pipeline-design.md:99`
  - Surfaced by: 0D cherry-pick 4 dan 5 + prior learning `design-doc-can-go-stale-mid-session`
  - Files: `TODOS.md`, `docs/designs/sentiment-pipeline-design.md`
  - Verify: baris 99 tidak lagi bertentangan dengan baris 42

## Completion Summary — Fase 1 (CEO)

```
  +====================================================================+
  |            MEGA PLAN REVIEW — COMPLETION SUMMARY (CEO)             |
  +====================================================================+
  | Mode selected        | SELECTIVE EXPANSION                         |
  | System Audit         | 0 commit untuk 2 sesi kerja; TODOS.md hilang|
  | Step 0               | Premis P2 DIBANTAH probe; Approach B-prime  |
  | Section 1  (Arch)    | 3 issues found                              |
  | Section 2  (Errors)  | 13 error paths mapped, 6 GAPS               |
  | Section 3  (Security)| 2 issues found, 0 High belum dimitigasi     |
  | Section 4  (Data/UX) | 7 edge cases mapped, 6 unhandled            |
  | Section 5  (Quality) | 2 issues found                              |
  | Section 6  (Tests)   | Diagram produced, 0 gaps                    |
  | Section 7  (Perf)    | 1 issue found                               |
  | Section 8  (Observ)  | 4 gaps found                                |
  | Section 9  (Deploy)  | 0 risks flagged                             |
  | Section 10 (Future)  | Reversibility: 4/5, debt items: 2           |
  | Section 11 (Design)  | SKIPPED (no UI scope)                       |
  +--------------------------------------------------------------------+
  | NOT in scope         | written (9 items)                           |
  | What already exists  | written                                     |
  | Dream state delta    | written                                     |
  | Error/rescue registry| 13 methods, 2 CRITICAL GAPS                 |
  | Failure modes        | 13 total, 2 CRITICAL GAPS                   |
  | TODOS.md updates     | 5 items proposed                            |
  | Scope proposals      | 5 proposed, 3 accepted, 1 taste, 1 deferred |
  | CEO plan             | written (~/.gstack/.../ceo-plans/)          |
  | Outside voice        | ran (claude subagent; codex unavailable)    |
  | Lake Score           | 8/9 recommendations chose complete option   |
  | Diagrams produced    | 5 (arch, dataflow, shadow, dream, temporal) |
  | Stale diagrams found | 0 diagrams, 1 stale doc claim               |
  | Unresolved decisions | 4 (3 User Challenges + 1 taste, ke gate)    |
  +====================================================================+
```

**Phase 1 complete.** Codex: unavailable. Claude subagent: 13 issues (4 critical,
5 high, 4 medium); 3 verified independently against real data and the network.
Consensus: 0/6 confirmed (single-voice), 4 single-voice CRITICAL flagged regardless.
3 User Challenges + 1 taste decision queued for the Final Gate. Passing to Phase 2.5 (DX).

---
---

# FASE 2.5 — DX REVIEW (Developer Experience)

Mode: **DX POLISH** (auto-decided). Codex: tidak tersedia — `[subagent-only]`.

**Fase 2 (Design) SKIPPED** — tidak ada UI scope. Diperiksa di Fase 0: satu-satunya
kecocokan kata UI adalah `form` di dalam kata "format". Plan tidak menyentuh
`report/html_builder.py` maupun template Jinja.

## Step 0 — DX Scope Assessment

**Tipe produk:** CLI toolchain internal, satu pengguna.
**Persona:** analis internal di Windows, menjalankan tool **sekali sebulan**. Ini
persona yang paling tidak memaafkan: apa pun yang harus diingat antar-run, tidak akan
diingat; apa pun yang tidak ada di `README.md`, tidak akan ditemukan.

### Developer Journey Map (9 tahap)

| # | Tahap | Kondisi setelah plan ini (sebelum perbaikan DX) | Nilai |
|---|---|---|---|
| 1 | Menemukan | `README.md` tidak pernah menyebut `sosmed_sentiment` sama sekali | 1/10 |
| 2 | Memasang | `pip install -r requirements.txt` — jelas dan berfungsi | 8/10 |
| 3 | Konfigurasi | `.env.example` **tidak ada** padahal `Rules.md` §2 menyuruh melihatnya; `config/thresholds.yaml` tidak ada padahal `Rules.md` §3 menamainya | 2/10 |
| 4 | Hello world | Tidak ada input kecil. Satu-satunya input valid = 6.158 komentar, 15 menit, dan ada di direktori yang di-gitignore | 2/10 |
| 5 | Run pertama | 6 flag diketik dari ingatan yang tidak dimiliki | 3/10 |
| 6 | Saat rusak | Sepuluh jalur error; nol pesan error pernah ditulis di plan | 3/10 |
| 7 | Kerja manual (pelabelan) | 1-2 jam kerja manusia, 6 baris rencana, hasilnya ditulis ke direktori gitignore | 1/10 |
| 8 | Ulangi bulan depan | Tidak ada perintah yang tersimpan, tidak ada `--month`, tidak ada dokumentasi | 2/10 |
| 9 | Ubah keputusan | Tidak ada saklar mati untuk negasi; tidak ada jalan kembali ke starter lexicon | 3/10 |

**TTHW sekarang: tidak terukur** (tidak ada jalur hello world yang berfungsi dari clone
bersih — satu-satunya input valid tidak ada di git).
**TTHW target: < 5 menit** dengan fixture 20 komentar yang di-commit.

### Developer Empathy Narrative

> Bulan depan aku buka terminal. Aku tahu ada tool sentimen karena aku yang minta
> dibuat. `README.md` tidak menyebutnya. Aku buka `docs/Architecture.md`, ketemu tabel
> CLI, dan tabel itu menyebut flag `--verbose` yang ternyata tidak ada di kodenya. Aku
> akhirnya baca `analyze.py` dan menghitung dekorator `@click.option` untuk tahu flag
> apa saja yang nyata.
>
> Aku jalankan. Lima belas menit. Tidak ada yang tercetak selama itu selain satu baris
> di awal. Aku hampir Ctrl-C dua kali.
>
> Lalu ia menyuruhku "isi .env sebelum mempercayai hasil komentar ambigu". Aku cari
> `.env.example`. Tidak ada.
>
> Aku dapat sampel 200 komentar untuk dilabeli. Aku buka di Excel — itu yang ada di
> laptopku. Aku label satu jam, simpan, tutup. Besoknya aku jalankan skrip skoringnya
> dan ia bilang akurasi 41%. Aku tidak tahu bahwa Excel sudah mengubah
> `7679054640457581319` jadi `7.67905E+18` dan menghancurkan digit belakangnya, jadi
> sebagian besar labelku tidak bisa dijodohkan lagi ke komentarnya. Angka 41% itu bukan
> akurasi lexicon. Itu kerusakan Excel. Tidak ada yang memberitahuku.

Narasi ini bukan hipotetis. Setiap langkahnya diverifikasi ke file nyata di repo.

## Step 0.5 — DX Dual Voices

### CLAUDE SUBAGENT (DX — independent review)

24 temuan. **Enam klaim yang menopang temuan CRITICAL diverifikasi ulang sendiri:**

| Klaim | Verifikasi | Status |
|---|---|---|
| `.gitignore` mengabaikan `runs/` | baris 162 = `runs/` | **BENAR** |
| `comment_id` 19 digit (Excel merusaknya) | `'7679054640457581319'`, 19 digit | **BENAR** |
| `.env.example` tidak ada | tidak ada | **BENAR** |
| `config/thresholds.yaml` tidak ada | `config/` hanya berisi `exclude_accounts.yaml`, `stopwords_custom.txt` | **BENAR** |
| Tidak ada input kecil yang bisa dijalankan | `runs/.../comments.json` root = list (valid); `data/*.json` root = dict (**ditolak** `flatten_input`) | **BENAR** |
| `pyproject.toml` tidak ada padahal `Rules.md` §2 menyuruh mencatat dep di sana | tidak ada | **BENAR** |

Enam dari enam. Temuan DX ini berdiri di atas fakta, bukan gaya.

**CRITICAL F13 — CSV berlabel mendarat di direktori yang di-gitignore.**
`runs/<bulan>/calibration_sample.csv`, dan `.gitignore:162` mengabaikan `runs/`.
Artefak manusia paling mahal yang dihasilkan plan ini — satu-satunya hal yang bisa
mencabut tanda ASUMSI di `PRD.md` §9 — ditulis ke tempat yang git tidak akan pernah
lihat, di mesin yang audit Fase 1 sendiri sebut punya dua sesi kerja belum di-commit.
Satu `git clean -fdx` dan dua jam hilang tanpa cara membuatnya ulang.
**DITERIMA.** Output berlabel pindah ke path yang di-track.

**CRITICAL F15 — Excel akan merusak file itu, di mesin Windows analis ini.**
`comment_id` 19 digit jadi `7.67905E+18` saat Excel menyimpan, dan digit belakangnya
hilang permanen. Sebagian baris tetap cocok, jadi kerusakannya **sebagian** — yang
lebih buruk daripada gagal total, karena hasilnya berupa angka akurasi yang terlihat
masuk akal dan sepenuhnya salah. Ditambah UTF-8 tanpa BOM = emoji hancur.
**DITERIMA.** Tulis UTF-8 dengan BOM, paksa kolom id jadi teks, dan
`score_calibration.py` **menolak** file yang kolom id-nya berbentuk notasi ilmiah
dengan pesan yang menyebutkan penyebabnya.

**CRITICAL F14 — Tidak ada panduan pelabelan, dan cuma 3 label untuk pipeline
4-keluaran.** Analis disuruh mengisi `positif`/`negatif`/`netral` tanpa satu pun
definisi. Di 200 komentar TikTok pasti muncul: sentimen campur (`bagus tapi mahal` —
plan sendiri menyebutnya), sarkasme, off-topic (`pertamax`, `hadir`), emoji-only
(emoji-nya sudah dicabut, jadi analis melihat apa?), non-Indonesia, spam. Dan pipeline
bisa mengeluarkan label keempat `tidak_terklasifikasi` (`hybrid.py:53`) yang analis
tidak punya cara menyatakannya — jadi komentar ambigu dipaksa berlabel dan angka
akurasinya bias ke arah yang tidak diketahui. **DITERIMA.** Codebook 15 baris dengan
2-3 contoh per label, plus nilai keempat `tidak_yakin` yang dilaporkan terpisah,
bukan diskor.

**CRITICAL F4 — Plan bertentangan dengan dirinya sendiri soal lokasi tiga skrip baru.**
Item 1-3 menulis `scripts/build_lexicon.py`; Section 5 membatalkannya jadi
`sosmed_sentiment/tools/`; T4/T8/T9 memakai `tools/`. Bagian awal tidak pernah
diperbarui. **Persis pola yang prior learning `design-doc-can-go-stale-mid-session`
catat, terjadi di dalam dokumen yang mengutip prior learning itu.** Ironi yang mahal:
siapa pun yang mengimplementasi dari bagian Item membangun di tempat yang salah.
**DITERIMA — diperbaiki di plan sekarang juga**, lihat Amandemen di bawah.

**CRITICAL F1 — Nol tugas dokumentasi menghadap pengguna.** `README.md` (13 KB, bagus)
tidak pernah menyebut `sosmed_sentiment`. Plan menambah 6 flag baru dan 3 tool baru,
dan satu-satunya tugas docs (T11) menghasilkan `TODOS.md` plus perbaikan satu baris di
doc internal. **DITERIMA.** Tugas P1 baru: bagian `## Sentiment analysis` di
`README.md` dengan urutan copy-paste persis.

**HIGH F5 — `lexicon_version` distempel salah saat fallback — bug diam-diam.**
`analyze.py:151`: `DEFAULT_LEXICON_VERSION if not lexicon_config else lexicon_config`.
Dengan default implisit yang plan usulkan, kalau `config/lexicon_inset.csv` hilang,
kode jatuh ke `STARTER_LEXICON` **dan tetap menstempel
`meta.config_used.lexicon_version = "inset-v1.0-stemmed"`**. Run 28 kata yang melaporkan
dirinya sebagai run 9.074 entri. NFR-03 (reproducibility) rusak tanpa satu pun error.
**Plan melanggar arahan "nol kegagalan diam-diam"-nya sendiri.** **DITERIMA** —
`lexicon_version` diturunkan dari lexicon yang benar-benar dimuat, dan default implisit
yang hilang = gagal keras, bukan diam.

**HIGH F6 — Tidak ada saklar mati untuk negasi.** T1 mengubah `score_tokens()` yang
dipakai bersama dua jalur klasifikasi, atas dasar rantai penalaran, bukan pengukuran
terhadap data berlabel. Ia rilis tanpa cara mematikannya. Kalau meleset di teks TikTok
nyata (`kurang bagus`, `bukan main`, `nggak nyangka bagus banget`), satu-satunya obat
analis adalah `git revert` di tengah bulan, pada tool yang dijalankan sekali sebulan.
**DITERIMA** — `--no-negation` plus `negation_handling` di `config/thresholds.yaml`.
Dipasangkan dengan metrik T7 supaya analis bisa mengukur **dan** membalikkan.

**HIGH F20 — T5 berisi either/or yang belum diputuskan dan bisa melipatgandakan biaya
LLM, dan ia mendarat sebelum tool yang mengukurnya.** Plan menulis "biarkan LLM
memutuskan **atau** tandai `tidak_terklasifikasi`" dan tidak memilih. 21,7% korpus
adalah komentar ≤3 kata; setelah filter stopword sebagian besarnya nol token. Memilih
"eskalasi" berarti mengirim seperlima setiap run ke LLM — persis ledakan biaya yang
ADR-02, FR-09, dan seluruh plan ini ada untuk mencegah. Dan T5 (P1) rilis sebelum T6
(`--dry-run`, P2), jadi tidak ada yang mengukurnya lebih dulu.
**DITERIMA.** Default `tidak_terklasifikasi` **tanpa panggilan API** (komentar tanpa
token yang bisa diskor tidak punya apa pun untuk membuat keputusan *lexicon* ragu),
eskalasi jadi opt-in lewat `--escalate-empty`, dan **T6 dipindah ke depan T5**.

**HIGH F19 — T1 dan T4 saling memverifikasi (dependensi melingkar).** Verifikasi T1
butuh lexicon InSet asli dari T4; T4 butuh daftar token ganda dari T3; T1 mengonsumsinya.
**DITERIMA** — urutan dinyatakan eksplisit: T3 → T4 → T1, dengan T1 punya test fixture
lebih dulu dan cek lexicon-asli setelah T4.

**HIGH F11 — Cache preprocessing gagal diam-diam, pada kunci yang salah.** Cache di-hash
dengan file input saja, padahal isinya bergantung juga pada `stopwords_custom.txt`,
versi Sastrawi, dan urutan tahap. Ubah stopword antara dry-run dan run asli, dan diam-diam
kamu dapat hasil dari daftar stopword lama. **DITERIMA sebagai syarat** — cache
(kalau disetujui di gate) harus hash input + stopwords + konstanta versi pipeline, dan
mencatat `cache hit`/`cache miss (stopwords berubah)` di INFO, bukan diam.

**HIGH F10 — Sepuluh gap error dipadatkan jadi satu tugas 10 menit, dan nol pesan error
pernah ditulis.** Repo ini sudah menetapkan standarnya sendiri, dari `batch.py`:
`"mirror_orderan_aff_tiktok.csv holds 5049 videos, which is about 172h 30m of scraping.
Pass --sample N ... or --all if you really mean to scrape every one."` Masalah, sebab,
dua jalan keluar, tiga baris. Tidak ada di plan yang meraih standar itu.
**DITERIMA** — T10 dibubarkan; penanganan error jadi bagian definition-of-done tiap
tugas, dengan teks pesan literal wajib ditulis.

**HIGH F2 — Tidak ada input kecil; setiap hello world berbiaya 15 menit.**
**DITERIMA** — commit `docs/examples/comments.sample.json` berisi 20 komentar dengan
bentuk nyata (satu emoji-only, satu `tidak bagus`, satu duplikat). Ini juga memberi
test regresi T1 dan test error T10 sesuatu untuk dijalankan.

**HIGH F3 — `.env.example` tidak ada padahal kode menyuruh mengisinya.** `analyze.py`
mencetak peringatan "fill in .env" yang menunjuk file yang tidak pernah dikirim.
**DITERIMA** — masuk ke T2.

**HIGH F16/F17 — Pelabelan tidak bisa dilanjutkan, dan re-run menghancurkan kerja.**
Seed tetap berarti analis yang menjalankan ulang perintah untuk "kembali mengerjakan"
menghasilkan file identik dan menimpa label parsialnya. Nol umpan balik sampai akhir.
**DITERIMA** — menolak menimpa tanpa `--force`, merge parsial, dan mode `--validate`
yang melaporkan `142/200 dilabeli, 58 sisa`.

**MEDIUM F7/F8/F9/F12/F18/F21/F22/F23/F24 — diterima seluruhnya**, dirangkum di
Checklist di bawah. Yang paling menonjol: `--price-per-1m-*` ambigu (juta/menit) dan
tidak pernah menyebut mata uang; `--escalation-budget "20%"` bertentangan dengan
threshold pecahan di skrip yang sama; `build_lexicon` diam 4 menit tanpa progress;
duplikat 10,7% akan dilabeli manual berkali-kali; `analyze` mengabaikan konvensi
`--month` yang sudah ditetapkan `batch.py`.

### DX DUAL VOICES — CONSENSUS TABLE

```
DX DUAL VOICES — CONSENSUS TABLE:
═══════════════════════════════════════════════════════════════
  Dimension                            Claude  Codex  Consensus
  ──────────────────────────────────── ─────── ────── ─────────
  1. Getting started < 5 min?          NO      N/A    single-voice CRITICAL
  2. API/CLI naming guessable?         NO      N/A    single-voice HIGH
  3. Error messages actionable?        NO      N/A    single-voice HIGH
  4. Docs findable & complete?         NO      N/A    single-voice CRITICAL
  5. Upgrade path safe?                PARTIAL N/A    single-voice HIGH
  6. Dev environment friction-free?    NO      N/A    single-voice HIGH
═══════════════════════════════════════════════════════════════
Codex tidak tersedia. 5 temuan CRITICAL dari satu suara, 6 klaim penopang
diverifikasi ulang secara independen terhadap file nyata. Ditandai, bukan diabaikan.
```

## Amandemen ke Plan (diterapkan sekarang, hasil DX)

1. **Lokasi skrip diseragamkan** ke `sosmed_sentiment/tools/` di seluruh dokumen.
   Bagian Item 1-3 di atas yang menulis `scripts/` **dibatalkan oleh Section 5 dan
   amandemen ini.** Perintah kanonik:
   ```
   python -m sosmed_sentiment.tools.build_lexicon
   python -m sosmed_sentiment.tools.calibrate_thresholds
   python -m sosmed_sentiment.tools.sample_for_labeling
   python -m sosmed_sentiment.tools.score_calibration
   ```
2. **Keputusan komentar nol-token:** `tidak_terklasifikasi`, **tanpa panggilan LLM**.
   Eskalasi jadi opt-in `--escalate-empty`. Menutup either/or yang tidak diputuskan.
3. **Urutan tugas diperbaiki** (melingkar sebelumnya): T0 → T3 → T4 → T1 → T6 → T5 →
   sisanya.
4. **Output pelabelan pindah** dari `runs/` (gitignore) ke path yang di-track.
5. **`--escalation-budget` dinyatakan sebagai pecahan** (`0.2`), konsisten dengan
   threshold lain di skrip yang sama.

## DX Scorecard

| # | Dimensi | Sebelum | Sesudah checklist | Catatan |
|---|---|---|---|---|
| 1 | Getting Started | 2/10 | 8/10 | Fixture 20 komentar + bagian README |
| 2 | API/CLI Design | 4/10 | 8/10 | Nama flag diseragamkan, `--month`, escape hatch |
| 3 | Error Messages | 3/10 | 8/10 | Teks literal wajib per tugas, bukan kategori |
| 4 | Documentation | 1/10 | 8/10 | README adalah satu-satunya tempat analis melihat |
| 5 | Upgrade & Migration | 5/10 | 7/10 | `--no-negation` sebagai jalan mundur tanpa git |
| 6 | Dev Environment | 3/10 | 8/10 | `.env.example`, `config/thresholds.yaml` |
| 7 | Community & Ecosystem | N/A | N/A | Tool internal satu pengguna — dimensi tidak berlaku |
| 8 | DX Measurement | 4/10 | 8/10 | Metrik T7 sudah kuat; ditambah mode `--validate` |
| | **Keseluruhan** | **3,1/10** | **7,9/10** | |

## DX Implementation Checklist

- [ ] `docs/examples/comments.sample.json` — 20 komentar, bentuk nyata, di-commit (F2)
- [ ] Bagian `## Sentiment analysis` di `README.md` dengan urutan copy-paste (F1)
- [ ] `.env.example` dengan tiga variabel LLM (F3)
- [ ] `config/thresholds.yaml` dengan default sekarang + komentar ASUMSI (F22)
- [ ] Output pelabelan ke path yang di-track, bukan `runs/` (F13)
- [ ] CSV pelabelan: UTF-8 **dengan BOM**, kolom id dipaksa teks (F15)
- [ ] `score_calibration.py` menolak kolom id notasi ilmiah dengan pesan penyebab (F15)
- [ ] Codebook pelabelan + label keempat `tidak_yakin` (F14)
- [ ] Dedup sebelum sampling berstrata (F18)
- [ ] `--force` untuk menimpa sampel; merge parsial; mode `--validate` (F16, F17)
- [ ] `lexicon_version` diturunkan dari lexicon yang dimuat, bukan konstanta (F5)
- [ ] Default lexicon implisit yang hilang = gagal keras (F5)
- [ ] `--lexicon-config starter` sebagai sentinel escape hatch (F6)
- [ ] `--no-negation` + `negation_handling` di config (F6)
- [ ] `--output` opsional saat `--dry-run` (F7)
- [ ] `generate_report` mencetak `run_id` + timestamp sumbernya (F7)
- [ ] `--price-input` / `--price-output` + mata uang eksplisit; tolak satu-tanpa-lainnya (F8)
- [ ] `--escalation-budget` sebagai pecahan (F8)
- [ ] `--month` di `analyze`, konsisten dengan `batch.py` (F9)
- [ ] Perintah lengkap dicetak di blok ringkasan run (F9)
- [ ] Teks pesan error literal ditulis per tugas, bukan T10 gabungan (F10)
- [ ] Cache di-hash dengan input + stopwords + versi pipeline; log hit/miss (F11)
- [ ] Progress di `build_lexicon` + baris "sekitar 4 menit" di awal (F12)
- [ ] Bahasa output CLI dipilih satu dan ditulis di `Rules.md` §7 (F23)
- [ ] Konfirmasi lisensi InSet jadi prasyarat T4; `--ref <commit>` untuk fetch (F24)

**Phase 2.5 complete.** DX overall: 3,1/10 → 7,9/10 target.
TTHW: tidak terukur (tidak ada jalur hello world) → target < 5 menit.
Codex: unavailable. Claude subagent: 24 issues (5 critical, 10 high, 9 medium);
6 klaim penopang diverifikasi ulang, 6 dari 6 benar.
Consensus: 0/6 confirmed (single-voice), 5 single-voice CRITICAL flagged regardless.
5 amandemen diterapkan ke plan. Passing to Phase 3 (Eng Review).

---
---

# FASE 3 — ENG REVIEW (gate wajib, mereview plan yang sudah diamandemen)

Codex: tidak tersedia — `[subagent-only]`.

## Step 0 — Scope Challenge

Cakupan **tidak dikurangi** (aturan autoplan P2). Tapi eng voice menemukan bahwa
cakupan T1 **jauh lebih besar dari yang plan akui**, dan itu perubahan estimasi,
bukan perubahan cakupan. Lihat H-COMPLEXITY di bawah.

## Step 0.5 — Eng Dual Voices

### CLAUDE SUBAGENT (eng — independent review)

Subagent membaca plan 1.497 baris, seluruh kode `sosmed_sentiment/`, `Rules.md`,
`Architecture.md`, dan **menjalankan probe sendiri terhadap venv repo**. Ia menuduh
plan ini salah fakta di tiga tempat. **Kelima klaim penopang diverifikasi ulang.
Kelimanya benar.**

| Klaim | Verifikasi langsung | Status |
|---|---|---|
| `stem()` TIDAK punya `lru_cache` | `stemming.py` dibaca utuh: tidak ada cache; docstring-nya menyatakan cache per-token **dicoba dan ditolak** | **PLAN SALAH** |
| `tidak` ada di InSet | `tidak` → bobot **-5** (dinormalisasi **-1,0**). `bukan` -3, `jangan` -3 | **BENAR, lebih buruk dari dugaan** |
| `bukannya` hanya jadi negasi setelah stemming | `stem(['bukannya'])` → `['bukan']` | **BENAR** |
| `tak` tidak tertangani di mana pun | bukan `NEGATION_WORDS`, bukan stopword, bukan `SLANG_MAP`, bukan di InSet | **BENAR** |
| confidence selalu 1.0 untuk kecocokan InSet apa pun | bobot |1| InSet = 0,2 dinormalisasi; `0,2 / 0,15 = 1,33` → `min(...,1,0)` = **1,0** | **BENAR** |

**CRITICAL C2 — `tidak` bernilai -1,0 di InSet, dan plan tidak pernah memutuskan apakah
kata negasi diskor atau dikonsumsi. Ini temuan terpenting Fase 3.**

Ini mengubah bentuk masalah yang Fase 1 temukan. Dengan InSet terpasang:

```
  ['tidak','bagus'] tanpa penanganan negasi:
      tidak = -1,0   bagus = +0,8   rata-rata = -0,1  ->  netral
      (bukan "positif" seperti dengan starter lexicon - InSet secara TIDAK SENGAJA
       menutupi sebagian bug negasi, dengan cara yang salah dan tidak bisa diandalkan)

  ['tidak','bagus'] dengan pembalikan naif DAN tidak mengonsumsi 'tidak':
      tidak = -1,0   bagus dibalik = -0,8   rata-rata = -0,9  ->  negatif conf 1,0
      Label benar, alasannya salah, magnitudonya dobel-hitung.

  ['tidak','kecewa'] dengan pembalikan naif DAN tidak mengonsumsi 'tidak':
      tidak = -1,0   kecewa dibalik = +0,8   rata-rata = -0,1  ->  netral
      SALAH. "tidak kecewa" itu positif. Bobot negasi menelan pembalikannya.
```

Kata negasi **harus dikonsumsi sebagai operator** — dikeluarkan dari `matched` **dan**
dari penyebut OOV. Kalau tidak, penanganan negasi menghasilkan label yang benar untuk
alasan yang salah pada kasus mudah, dan salah pada kasus yang justru penting.
**DITERIMA, wajib, masuk ke definisi T1.**

**CRITICAL C1 — kontrak balikan `score_tokens()` tidak punya konsumen.** Section 5
menulis sambil lalu bahwa ia akan mengembalikan tiga nilai. `is_ambiguous()` tidak punya
parameter untuk menerimanya, dan T1 hanya mendaftar satu file. Tiga metrik T7 tidak bisa
dijangkau tanpa keputusan ini. **DITERIMA** — `score_tokens()` mengembalikan satu
dataclass (`score`, `oov_ratio`, `signal_ratio`, `negations_applied`,
`negations_dangling`, `matched_raw`, `matched_stemmed`); `is_ambiguous()` menerimanya;
T1 mendaftar `lexicon_classifier.py` **dan** `hybrid.py` **dan** `analyze.py`.

**CRITICAL C3 — deteksi negasi harus jalan di daftar stemmed, lookup lexicon di daftar
raw.** `bukannya` hanya jadi negasi setelah stemming. Kedua daftar harus sejajar
indeksnya. **DITERIMA, ditulis eksplisit.**

**CRITICAL C4 — "berhenti di batas klausa" tidak bisa diimplementasi di pipeline ini.**
Saat token sampai ke `score_tokens()`, tanda baca sudah hilang (`tokenizing.py`
`[a-z0-9']+`) dan filter stopword sudah mengubah jarak antar-token — `karena` ada di
`DEFAULT_STOPWORDS`, jadi penanda klausa dihapus sebelum scorer melihatnya. Lebih buruk:
filter **memendekkan** jarak, sehingga `tidak ada yang bagus` menjadi `['tidak','bagus']`
dan kata yang sebenarnya jauh tertarik masuk ke jendela.
**DITERIMA.** 0E salah menjanjikan sesuatu yang tidak bisa dikirim. **Amandemen:**
jendela ±2 murni atas token terfilter, dan **keterbatasannya ditulis jujur** di
`Rules.md` dan di Blok Metodologi laporan. Tidak menjanjikan (b) lalu mengirim (a).

**CRITICAL C5 — lookup dua-kunci diam-diam mengubah arti `oov_ratio`, dan
melemahkannya persis di tempat ia paling dibutuhkan.** `oov_ratio` adalah satu-satunya
sinyal "kami tidak paham teks ini". Raw-first + 8.395 entri meruntuhkan OOV di seluruh
papan, sehingga lengan `oov_ratio > 0.5` di `is_ambiguous()` mendekati kode mati dan
eskalasi menyusut jadi pita skor saja. Jaring pengaman yang plan andalkan untuk
menangkap keterbatasan negasinya sendiri adalah lengan yang sedang dinonaktifkan.
Ditambah: 1.142 kata yang net ≈0 **dihitung sebagai cocok** — mereka menekan `oov_ratio`
turun sekaligus menyeret rata-rata ke nol. Komentar penuh kata seperti itu tampak
sekaligus dipahami dan netral.
**DITERIMA.** Tambah `signal_ratio` (fraksi token dengan |bobot| ≥ 0,2) sebagai lengan
eskalasi kedua; hitung `oov_ratio` hanya atas token konten (negasi dikecualikan); buang
entri gabungan yang mendekati nol saat build. **Diputuskan sebelum T8**, karena sapuan
mengukur apa pun yang keputusan ini hasilkan.

**HIGH H2 — "confidence 1.0" yang plan kutip delapan kali adalah bug rumus, bukan bug
negasi.** `lexicon_classifier.py:106`. Bobot terkecil InSet = 0,2 dinormalisasi, dan
`0,2 / 0,15 = 1,33` → dipotong jadi **1,0**. **Setiap kecocokan satu kata melaporkan
keyakinan maksimum.** Perbaiki negasi dan kamu masih mengirim laporan yang hampir setiap
label non-netralnya mengklaim confidence penuh. **DITERIMA — tugas baru T1b.**
Rumus diskalakan ulang atas rentang yang bisa dipakai, plus faktor cakupan (jumlah token
cocok / total) supaya kecocokan 1-dari-1 tidak seyakin 5-dari-6.

**HIGH H4 — pembalikan tanda magnitudo penuh adalah default yang salah.** `tidak bagus`
tidak senegatif `jelek`. **DITERIMA** — balik lalu redam (`skor → -skor × k`, k≈0,5-0,7),
`k` jadi nilai config di `config/thresholds.yaml`, dan diuji dua-duanya:
`tidak bagus → negatif` DAN `|skor(tidak bagus)| < |skor(jelek)|`.

**HIGH H3 — `threshold_score` adalah dua kenop berbeda memakai satu nama.**
`analyze.py:125` meneruskannya sebagai `neutral_band` ke `classify()`; `hybrid.py:46`
meneruskan nilai yang sama ke `is_ambiguous()`. Sapuan T8 karenanya mengubah label
**dan** eskalasi bersamaan, dan tabel "% dieskalasi" hasilnya tidak bisa dibaca sebagai
pengukuran satu variabel. **DITERIMA** — dipisah jadi `neutral_band` dan
`escalation_band` sebelum T8.

**HIGH H6 — threshold dan lexicon tidak diversikan bersama.** Setiap `build_lexicon`
ulang diam-diam membatalkan `config/thresholds.yaml` tanpa satu pun error.
**DITERIMA** — `calibrated_against_lexicon_version` di `thresholds.yaml`, peringatan
keras saat tidak cocok di `threshold_config.py`.

**HIGH H5 — tidak ada yang melindungi run berbayar yang sedang jalan.**
`analyze.py:109` adalah satu loop sekuensial memanggil `classify_via_llm` per komentar,
dan `llm_failure_ratio_exceeds_threshold` baru dievaluasi **setelah seluruh loop**
(baris 133). Crash di komentar 11.999 kehilangan semuanya, termasuk uang yang sudah
dibelanjakan. Sisi scraper repo ini **sudah punya pola checkpoint**
(`tests/test_checkpoint.py`); pipeline sentimen tidak memakainya ulang.
**DITERIMA — pelanggaran DRY sekaligus risiko uang. Tugas baru T6b.**

**HIGH H1 — "jalur utama tidak lagi menggabungkan apa pun" (baris 637) SALAH.**
1.142 duplikat pos/neg adalah **kata mentah yang sama di dua file**. Penggabungan itu
terjadi di ruang kunci mentah dan tidak bisa dihindari di bawah B-prime. HIGH 7 Fase 1
karenanya cuma setengah terselesaikan, dan plan menyatakannya selesai.
**DITERIMA — dikoreksi.** Dan kriteria sukses T4 "pertahankan 9.074 entri" **tidak bisa
dicapai**: 740 entri multi-kata dibuang aturan B, jadi indeks mentah maksimum ~8.395.
**Kriteria diperbaiki jadi ~8.395.**

**HIGH H8 — "`stem()` sudah punya `lru_cache` per token unik" SALAH, dan sumbernya
adalah `Architecture.md`.** `stemming.py` tidak punya cache; docstring-nya menyatakan
cache per-token dicoba lalu ditolak karena kosakata komentar informal terlalu luas.
`Architecture.md` §2 mengklaim `lru_cache` dan **dokumen itu salah tentang kodenya
sendiri.** Plan ini mengulanginya dua kali karena mempercayai dokumen alih-alih membaca
file. **DITERIMA — `Architecture.md` §2 ikut diperbaiki di T11.** Ini contoh kedua dari
pola `design-doc-can-go-stale-mid-session` di sesi yang sama.

**MEDIUM M5 — "315 test tetap hijau" dipakai sebagai kriteria verifikasi T1, dan itu
tidak mungkin.** `test_lexicon_classifier.py` menegaskan balikan 2-tuple, dan
`test_empty_token_list_is_netral_with_zero_oov` menegaskan persis perilaku yang T5
hendak ubah. **DITERIMA** — kriteria diganti: "315 test hijau **kecuali** N test yang
sengaja diperbarui, tiap perubahan disertai alasan di pesan commit". Mengatakan "315
hijau" mengundang orang melemahkan T1 demi menjaga angka.

**MEDIUM M1 — `NEGATION_WORDS` tidak lengkap untuk bahasa TikTok nyata.** `tak` hilang
sepenuhnya dari keempat mekanisme (diverifikasi). Juga `enggak`/`engga`/`ngak`,
`gaada`, `tanpa`. **DITERIMA ke T1.**

**MEDIUM M2, M3, M4, M7, M8 — diterima seluruhnya.** Paling menonjol: fallback
length-mismatch di `stem()` tidak diuji dan tidak dicatat, padahal di bawah lookup
dua-kunci ia satu-satunya yang menjamin kesejajaran indeks raw/stemmed; dan dedup
diterapkan ke kalibrasi tapi tidak ke produksi, jadi Item 3 mengkalibrasi distribusi
yang run sungguhan tidak pernah lihat.

**HIGH H7 — lisensi InSet adalah gate hukum, bukan catatan kaki.** InSet terbit di
bawah lisensi Creative Commons yang dikutip luas memuat klausul NonCommercial.
Meng-commit artefak turunan ke repo alat bisnis bukan hal yang boleh ditemukan setelah
`config/lexicon_inset.csv` masuk histori git — dan plan sendiri mencatat commit itu
tidak bisa dibalik. **DITERIMA — prasyarat keras di atas T4, jawaban tertulis di
`SOURCE.md`.**

### ENG DUAL VOICES — CONSENSUS TABLE

```
ENG DUAL VOICES — CONSENSUS TABLE:
═══════════════════════════════════════════════════════════════
  Dimension                            Claude  Codex  Consensus
  ──────────────────────────────────── ─────── ────── ─────────
  1. Architecture sound?               PARTIAL N/A    single-voice HIGH
  2. Test coverage sufficient?         NO      N/A    single-voice HIGH
  3. Performance risks addressed?      NO      N/A    single-voice HIGH
  4. Security threats covered?         PARTIAL N/A    single-voice HIGH (lisensi)
  5. Error paths handled?              NO      N/A    single-voice CRITICAL
  6. Deployment risk manageable?       PARTIAL N/A    single-voice MEDIUM
═══════════════════════════════════════════════════════════════
Codex tidak tersedia. 5 CRITICAL + 8 HIGH dari satu suara; 5 klaim penopang
diverifikasi ulang terhadap kode nyata, 5 dari 5 benar, tiga di antaranya
membuktikan PLAN INI SALAH FAKTA. Ditandai, bukan diabaikan.
```

### CROSS-MODEL TENSION

```
CROSS-MODEL TENSION:
  Ukuran T1: Fase 1 memperkirakan negasi sebagai "CC ~25 menit, tambahkan loop
  jendela". Eng voice menghitungnya sebagai enam keputusan semantik yang belum
  satupun diambil plan: daftar token mana yang dideteksi, negasi dikonsumsi atau
  diskor, magnitudo pembalikan, penyebut OOV didefinisi ulang, kontrak balikan
  berubah, sinyal baru masuk ke is_ambiguous(). Eng voice menang telak, dan
  buktinya adalah bobot -5 milik `tidak` di InSet yang tidak ada satupun fase
  sebelumnya lihat. Perkiraan direvisi.

  Tidak ada tension yang tersisa terbuka: setiap temuan eng voice diterima atau
  diverifikasi. Ini bukan tanda kesepakatan yang nyaman - itu tanda review
  sebelumnya kurang teliti membaca kode dan terlalu percaya dokumen.
```

## Section 1 — Architecture

Diagram arsitektur Fase 1 tetap berlaku, dengan dua koreksi wajib:

```
  preprocessing.pipeline (BARU)
       |  mengembalikan tokens_filtered DAN tokens_stemmed, SEJAJAR INDEKS
       |  (kesejajaran dijamin hanya oleh fallback length-mismatch stem() --
       |   sekarang tidak diuji dan tidak dicatat: lihat M2)
       v
  score_tokens (DIUBAH BESAR - bukan tambahan kecil)
       |  1. deteksi negasi di tokens_stemmed
       |  2. negasi DIKONSUMSI: keluar dari matched DAN dari penyebut OOV
       |  3. lookup lexicon raw-first di tokens_filtered, fallback stemmed
       |  4. balik-lalu-redam token dalam jendela +-2 (bukan batas klausa)
       |  5. mengembalikan DATACLASS, bukan tuple
       v
  is_ambiguous (DIUBAH - kontrak baru)
       |  eskalasi kalau: |skor| <= escalation_band
       |              ATAU oov_ratio > threshold_oov
       |              ATAU signal_ratio < threshold_signal   <-- LENGAN BARU
       |  (tanpa lengan baru, lengan OOV mendekati kode mati setelah InSet)
       v
  loop klasifikasi di analyze.py:109
       |  RISIKO: sekuensial, tanpa checkpoint, rasio gagal dicek setelah
       |  seluruh loop. Repo punya pola checkpoint di sisi scraper yang
       |  tidak dipakai ulang.  -> T6b
```

**Coupling:** `score_tokens()` sekarang menjadi titik yang dipakai bersama tiga jalur
(lexicon-only, hybrid, dry-run) dengan kontrak baru. Itu coupling yang naik, dan
**dibenarkan** — alternatifnya menduplikasi semantik negasi ke tiga tempat.

**Temuan Section 1: 4** (kontrak balikan, lengan eskalasi baru, kesejajaran indeks tak
terjamin, loop tanpa checkpoint).

## Section 2 — Code Quality

- **DRY, temuan baru:** repo punya pola checkpoint yang teruji di sisi scraper
  (`tests/test_checkpoint.py`) dan pipeline sentimen menulis loop panjangnya sendiri
  tanpa memakainya. Itu pelanggaran DRY yang berbiaya uang, bukan gaya.
- **Poin positif yang layak dicatat:** T3 (mengeluarkan `_preprocess()` dari
  `cli/analyze.py`) juga memperbaiki pelanggaran `Rules.md` §3 yang sudah ada —
  "`cli/*.py` tidak boleh memuat logika transformasi teks". Argumennya lebih kuat dari
  yang plan sadari.
- **Kompleksitas:** `score_tokens()` setelah T1 punya 5 tanggung jawab (deteksi negasi,
  konsumsi, lookup dua-kunci, balik-redam, hitung tiga rasio). Itu di atas ambang.
  **Pecah jadi dua fungsi**: `_resolve_tokens()` (lookup dua-kunci + negasi) dan
  `score_tokens()` (agregasi + rasio).
- **`Rules.md` §3 tidak punya baris `tools/`** — §11 menyuruh memperbarui dokumen alih-alih
  menyimpang diam-diam. Masuk T11.

**Temuan Section 2: 4.**

## Section 3 — Test Review

Klaim Fase 1 "Section 6: 0 gaps" **dibatalkan.** Itu tidak bisa dipertahankan.

```
  CODEPATH BARU (revisi setelah temuan eng):
    - resolusi token: raw hit / stemmed hit / dua-duanya meleset
    - negasi: dalam jendela / di luar jendela / menggantung / ganda
    - negasi sebagai entri lexicon (tidak=-1,0)          <-- BARU, C2
    - kesejajaran indeks saat fallback stem() menyala    <-- BARU, M2
    - signal_ratio sebagai lengan eskalasi ketiga        <-- BARU, C5
    - rumus confidence yang diskalakan ulang             <-- BARU, H2
    - saklar --no-negation                               <-- BARU, F6
    - checkpoint/resume di loop LLM                      <-- BARU, H5
    - dry-run: hitung, pecah alasan, estimasi, nol panggilan API
    - build lexicon: 5 aturan + verifikasi sha256
    - kalibrasi: sapuan, sampling, skoring, validasi CSV Excel
```

| Test | Kenapa ia ada |
|---|---|
| `tidak bagus` → **negatif** terhadap lexicon InSet asli | Membuktikan temuan inti Fase 1 benar-benar tertutup |
| `tidak kecewa` → **positif** terhadap InSet asli | **Test terpenting seluruh rencana.** Ini satu-satunya yang gagal kalau negasi tidak dikonsumsi sebagai operator (C2) — kasus yang label-nya salah justru saat implementasi terlihat benar |
| `|skor(tidak bagus)| < |skor(jelek)|` | Mengunci redaman (H4) |
| Fixture dengan `tidak` di lexicon | Tidak bisa disentuh `STARTER_LEXICON`; butuh fixture sendiri (C2) |
| `--no-negation` menghasilkan output identik byte dengan hari ini | Satu-satunya bukti escape hatch berfungsi (F6) |
| `bukannya` terdeteksi sebagai negasi | Membuktikan deteksi jalan di daftar stemmed (C3) |
| `tidak ada yang bagus` — teks mentah DAN daftar token pasca-filter | Membuat distorsi jendela terlihat, bukan disembunyikan (C4) |
| Kata negasi lolos `stem()` tanpa berubah | Upgrade Sastrawi bisa mematikan seluruh penanganan negasi diam-diam |
| `oov_ratio` selalu di [0,1]; token cocok berskor 0,0 dihitung dikenal | Membuat keputusan C5 bisa ditegaskan |
| Kesejajaran indeks saat fallback `stem()` menyala | M2 |
| Karakterisasi di fixture 20 komentar: rasio eskalasi + distribusi label sebelum/sesudah swap | Membuat efek nyata swap jadi diff, bukan perasaan |
| `--dry-run` dengan `LLM_API_KEY` terisi → nol permintaan HTTP | Test QA bermusuhan |
| CSV kalibrasi rusak Excel → ditolak dengan pesan penyebab | F15 |
| Loop LLM crash di tengah → checkpoint bisa dilanjut | H5 |

**Yang rusak jam 2 pagi Jumat** (revisi): bukan `tidak bagus` — itu ada test-nya.
Melainkan (a) analis membangun ulang lexicon dan mendapat rasio eskalasi serta label
yang berbeda materiil **tanpa satu pun output error** (H6), dan (b) run hybrid mati di
komentar 5.000 dari 12.000 dengan uang sudah terpakai dan tanpa resume (H5).

**Temuan Section 3: 14 test wajib**, 8 di antaranya tidak ada di rencana Fase 1.

## Section 4 — Performance

- Lookup dua-kunci: benar bahwa biaya CPU-nya nol. **Section 7 Fase 1 memberi harga
  yang benar untuk hal yang salah** — risikonya semantik (C5), bukan performa.
- Klaim "233 detik build" berdiri di atas asumsi `lru_cache` yang **tidak ada** (H8).
  Angkanya tetap valid karena diukur langsung, tapi alasannya di plan salah.
- **Risiko performa nyata yang Fase 1 lewatkan:** loop LLM sekuensial pada 10x beban.
  60 ribu komentar × 20% eskalasi = 12.000 panggilan HTTP berurutan dengan retry dan
  sleep. Itu, bukan stemming, yang jadi tebing sesungguhnya begitu LLM menyala.

**Temuan Section 4: 2.**

## Failure Modes Registry (revisi Fase 3)

```
  CODEPATH        | FAILURE MODE                    | RESCUED?| TEST?| USER SEES?    | LOGGED?
  ----------------|---------------------------------|---------|------|---------------|--------
  score_tokens    | negasi tidak dikonsumsi ->      | N       | N    | "tidak kecewa"| N  <-- CRITICAL
                  | bobot InSet menelan pembalikan  |         |      | = netral      |
  score_tokens    | confidence 1.0 untuk tiap       | N       | N    | Semua label    | N  <-- CRITICAL
                  | kecocokan 1 kata (bug rumus)    |         |      | tampak pasti  |
  is_ambiguous    | lengan OOV jadi kode mati       | N       | N    | Eskalasi diam- | N  <-- CRITICAL
                  | setelah InSet                   |         |      | diam menyusut |
  score_tokens    | 0 token -> netral conf 1.0      | N       | N    | Diam-diam salah| N <-- CRITICAL
  loop LLM        | crash mid-run, uang terpakai    | N       | N    | Semua hilang  | N  <-- CRITICAL
  threshold_config| lexicon dibangun ulang,         | N       | N    | Angka beda,   | N  <-- CRITICAL
                  | threshold jadi basi             |         |      | tanpa error   |
  stem()          | fallback length-mismatch        | N       | N    | Lambat 100x   | N  <-- GAP
  analyze         | lexicon_version distempel salah | N       | N    | Provenance    | N  <-- CRITICAL
                  | saat fallback                   |         |      | palsu         |
  build_lexicon   | TSV berubah, sha256 tak dicek   | N       | N    | Lexicon beda  | N  <-- GAP
  score_calib     | CSV rusak Excel                 | N       | N    | Akurasi palsu | N  <-- CRITICAL
  ----------------|---------------------------------|---------|------|---------------|--------
```

**8 CRITICAL GAP** (naik dari 2 di Fase 1). Setiap satunya menghasilkan angka salah
tanpa jejak. Ini yang paling penting dari seluruh `/autoplan`: pipeline ini tidak
kekurangan fitur, ia kekurangan cara untuk memberi tahu ketika ia salah.

## Tugas Baru dari Fase 3

- [ ] **T1b (P1)** — sentiment — Perbaiki rumus confidence (skala ulang + faktor cakupan)
  - Surfaced by: eng H2 — `0,2 / 0,15` → confidence 1,0 untuk tiap kecocokan satu kata
  - Verify: kecocokan 1-dari-1 punya confidence lebih rendah dari 5-dari-6
- [ ] **T1c (P1)** — sentiment — `signal_ratio` sebagai lengan eskalasi ketiga; `oov_ratio` hanya atas token konten
  - Surfaced by: eng C5 — lengan OOV mendekati kode mati setelah InSet
  - Verify: lengan eskalasi diukur terpisah di laporan dry-run
- [ ] **T1d (P1)** — sentiment — Pisah `neutral_band` dari `escalation_band`
  - Surfaced by: eng H3 — sapuan T8 tidak bisa dibaca sebagai pengukuran satu variabel
- [ ] **T4b (P1)** — lexicon — `calibrated_against_lexicon_version` + peringatan tidak cocok
  - Surfaced by: eng H6 — build ulang membatalkan threshold diam-diam
- [ ] **T6b (P1)** — cli — Checkpoint/resume di loop LLM + abort dini saat rasio gagal tinggi
  - Surfaced by: eng H5 — crash mid-run kehilangan uang yang sudah dibelanjakan; repo sudah punya pola checkpoint yang tidak dipakai ulang
- [ ] **T4c (P1, prasyarat keras)** — legal — Konfirmasi lisensi InSet SEBELUM commit CSV
  - Surfaced by: eng H7 — klausa NonCommercial, commit tidak bisa dibalik dari histori

## Completion Summary — Fase 3 (Eng)

```
  +====================================================================+
  |              ENG PLAN REVIEW — COMPLETION SUMMARY                  |
  +====================================================================+
  | Scope                | HELD (tidak dikurangi); T1 diperbesar       |
  | Step 0               | 3 kesalahan fakta di plan ditemukan+dikoreksi|
  | Section 1  (Arch)    | 4 issues found                              |
  | Section 2  (Quality) | 4 issues found                              |
  | Section 3  (Tests)   | 14 test wajib, 8 tidak ada di Fase 1        |
  | Section 4  (Perf)    | 2 issues found                              |
  +--------------------------------------------------------------------+
  | Failure modes        | 10 total, 8 CRITICAL GAPS                   |
  | Test plan artifact   | ditulis ke ~/.gstack/projects/...           |
  | Outside voice        | ran (claude subagent; codex unavailable)    |
  | Tugas baru           | 6 (T1b, T1c, T1d, T4b, T4c, T6b)           |
  | Unresolved decisions | 4 (dinaikkan ke Final Gate)                 |
  +====================================================================+
```

**Phase 3 complete.** Codex: unavailable. Claude subagent: 19 issues (5 critical,
8 high, 6 medium); 5 klaim penopang diverifikasi ulang, 5 dari 5 benar, 3 di antaranya
membuktikan plan ini salah fakta. Consensus: 0/6 confirmed (single-voice), 5
single-voice CRITICAL flagged regardless. Passing to Phase 4 (Final Gate).

---
---

# FASE 4 — IMPLEMENTATION TASKS (agregat lintas fase)

Diagregasi dari 3 fase (CEO, DX, Eng). 40 tugas: 26 P1, 13 P2, 1 P3.
jq tidak terpasang di mesin ini; agregasi dijalankan dengan serializer json Python
(aturan yang sama: tidak pernah merangkai JSONL dengan tangan).

- [ ] **T0 (P1, human: ~2 mnt / CC: ~2 mnt) — repo** — Commit seluruh kerja yang belum di-track
  - Surfaced by: ceo-review — Audit Sistem + CEO voice CRITICAL 4 - 315 test dan 5 dokumen di working tree, nol di git
  - Files: .
- [ ] **T1 (P1, human: ~4j / CC: ~25mnt) — sentiment** — Tangani negasi di score_tokens()
  - Surfaced by: ceo-review — 0A Premise Challenge - ['tidak','bagus'] menghasilkan positif confidence 1.0
  - Files: sosmed_sentiment/sentiment/lexicon_classifier.py
- [ ] **T2 (P1, human: ~30mnt / CC: ~10mnt) — llm** — Satu panggilan router nyata dengan 20 komentar
  - Surfaced by: ceo-review — CEO voice HIGH 6 - classify_via_llm belum pernah mengembalikan respons nyata
  - Files: (none)
- [ ] **T3 (P1, human: ~1j / CC: ~10mnt) — preprocessing** — Ekstrak _preprocess() ke preprocessing/pipeline.py, kembalikan token filtered dan stemmed
  - Surfaced by: ceo-review — 0D cherry-pick 1 + CEO voice HIGH 5
  - Files: sosmed_sentiment/preprocessing/pipeline.py, sosmed_sentiment/cli/analyze.py
- [ ] **T4 (P1, human: ~4j / CC: ~30mnt) — lexicon** — Build InSet dengan lookup dua-kunci
  - Surfaced by: ceo-review — Item 1 + CEO voice HIGH 5 - pertahankan 9.074 entri, jangan turunkan ke 5.960
  - Files: sosmed_sentiment/tools/build_lexicon.py, config/lexicon_inset.csv
- [ ] **T5 (P1, human: ~2j / CC: ~15mnt) — sentiment** — Token kosong menghasilkan ambigu, bukan netral confidence 1.0
  - Surfaced by: ceo-review — Section 2 CRITICAL GAP - mengenai 21,7% korpus
  - Files: sosmed_sentiment/sentiment/lexicon_classifier.py
- [ ] **E1 (P1, human: ~3j / CC: ~20mnt) — sentiment** — Negasi DIKONSUMSI sebagai operator: keluar dari matched DAN penyebut OOV
  - Surfaced by: eng-review — eng C2 - tidak bernilai -1,0 di InSet; tanpa ini 'tidak kecewa' jadi netral
  - Files: sosmed_sentiment/sentiment/lexicon_classifier.py
- [ ] **E10 (P1, human: ~30mnt / CC: ~30mnt) — legal** — Konfirmasi lisensi InSet SEBELUM commit CSV (prasyarat keras)
  - Surfaced by: eng-review — eng H7 - klausa NonCommercial; commit tidak bisa dibalik dari histori git
  - Files: config/lexicon_inset.SOURCE.md
- [ ] **E11 (P1, human: ~3j / CC: ~25mnt) — cli** — Checkpoint/resume di loop LLM + abort dini saat rasio gagal tinggi
  - Surfaced by: eng-review — eng H5 - crash mid-run kehilangan uang; repo punya pola checkpoint yang tak dipakai ulang
  - Files: sosmed_sentiment/cli/analyze.py
- [ ] **E12 (P1, human: ~30mnt / CC: ~5mnt) — sentiment** — NEGATION_WORDS diperluas: tak, enggak, engga, ngak, gaada, tanpa
  - Surfaced by: eng-review — eng M1 - 'tak' tidak tertangani di keempat mekanisme (diverifikasi)
  - Files: sosmed_sentiment/preprocessing/filtering.py, sosmed_sentiment/preprocessing/normalizing.py
- [ ] **E2 (P1, human: ~2j / CC: ~15mnt) — sentiment** — score_tokens mengembalikan dataclass; is_ambiguous menerima kontrak baru
  - Surfaced by: eng-review — eng C1 - kontrak 3-tuple tidak punya konsumen; 3 metrik T7 tak terjangkau tanpa ini
  - Files: sosmed_sentiment/sentiment/lexicon_classifier.py, sosmed_sentiment/sentiment/hybrid.py
- [ ] **E3 (P1, human: ~1j / CC: ~10mnt) — sentiment** — Deteksi negasi di tokens_stemmed, lookup lexicon raw-first; indeks sejajar
  - Surfaced by: eng-review — eng C3 - bukannya hanya jadi negasi setelah stemming
  - Files: sosmed_sentiment/sentiment/lexicon_classifier.py
- [ ] **E4 (P1, human: ~1j / CC: ~10mnt) — sentiment** — Jendela +-2 murni; klaim 'batas klausa' dicabut dan keterbatasan ditulis jujur
  - Surfaced by: eng-review — eng C4 - tanda baca sudah hilang, filter stopword mengubah jarak antar-token
  - Files: sosmed_sentiment/sentiment/lexicon_classifier.py, docs/Rules.md
- [ ] **E5 (P1, human: ~2j / CC: ~15mnt) — sentiment** — signal_ratio sebagai lengan eskalasi ketiga; oov_ratio hanya atas token konten
  - Surfaced by: eng-review — eng C5 - lengan OOV mendekati kode mati setelah InSet; jaring pengaman dinonaktifkan
  - Files: sosmed_sentiment/sentiment/hybrid.py
- [ ] **E6 (P1, human: ~1j / CC: ~10mnt) — sentiment** — Perbaiki rumus confidence: skala ulang + faktor cakupan
  - Surfaced by: eng-review — eng H2 - 0,2/0,15 -> 1,0; tiap kecocokan satu kata melapor keyakinan maksimum
  - Files: sosmed_sentiment/sentiment/lexicon_classifier.py
- [ ] **E7 (P1, human: ~1j / CC: ~10mnt) — sentiment** — Balik-lalu-redam (k konfigurabel), bukan pembalikan magnitudo penuh
  - Surfaced by: eng-review — eng H4 - 'tidak bagus' tidak senegatif 'jelek'
  - Files: sosmed_sentiment/sentiment/lexicon_classifier.py, config/thresholds.yaml
- [ ] **E8 (P1, human: ~1j / CC: ~10mnt) — sentiment** — Pisah neutral_band dari escalation_band
  - Surfaced by: eng-review — eng H3 - sapuan T8 mengubah label dan eskalasi bersamaan, tak terbaca
  - Files: sosmed_sentiment/sentiment/hybrid.py
- [ ] **E9 (P1, human: ~1j / CC: ~10mnt) — lexicon** — calibrated_against_lexicon_version + peringatan keras saat tidak cocok
  - Surfaced by: eng-review — eng H6 - build ulang membatalkan thresholds.yaml diam-diam
  - Files: sosmed_sentiment/sentiment/threshold_config.py
- [ ] **D1 (P1, human: ~2j / CC: ~15mnt) — docs** — Bagian '## Sentiment analysis' di README.md dengan urutan copy-paste
  - Surfaced by: devex-review — DX F1 - README tidak pernah menyebut sosmed_sentiment
  - Files: README.md
- [ ] **D2 (P1, human: ~30mnt / CC: ~10mnt) — fixtures** — Commit docs/examples/comments.sample.json (20 komentar, bentuk nyata)
  - Surfaced by: devex-review — DX F2 - tidak ada input kecil; satu-satunya input valid 15 menit dan di-gitignore
  - Files: docs/examples/comments.sample.json
- [ ] **D3 (P1, human: ~20mnt / CC: ~5mnt) — config** — .env.example + config/thresholds.yaml
  - Surfaced by: devex-review — DX F3/F22 - Rules.md menyuruh melihat file yang tidak pernah dikirim
  - Files: .env.example, config/thresholds.yaml
- [ ] **D4 (P1, human: ~15mnt / CC: ~5mnt) — kalibrasi** — Output pelabelan ke path yang di-track, bukan runs/ (gitignore)
  - Surfaced by: devex-review — DX F13 - artefak manusia paling mahal ditulis ke tempat git tidak lihat
  - Files: sosmed_sentiment/tools/sample_for_labeling.py
- [ ] **D5 (P1, human: ~2j / CC: ~15mnt) — kalibrasi** — CSV UTF-8 dengan BOM, kolom id dipaksa teks, tolak file rusak Excel
  - Surfaced by: devex-review — DX F15 - comment_id 19 digit jadi 7.67905E+18, kerusakan SEBAGIAN
  - Files: sosmed_sentiment/tools/sample_for_labeling.py, sosmed_sentiment/tools/score_calibration.py
- [ ] **D6 (P1, human: ~1j / CC: ~10mnt) — kalibrasi** — Codebook pelabelan + label keempat tidak_yakin
  - Surfaced by: devex-review — DX F14 - 3 label untuk pipeline 4-keluaran, nol definisi
  - Files: docs/calibration/codebook.md
- [ ] **D7 (P1, human: ~1j / CC: ~10mnt) — sentiment** — lexicon_version diturunkan dari lexicon yang dimuat; default implisit hilang = gagal keras
  - Surfaced by: devex-review — DX F5 - run 28 kata melaporkan diri sebagai run InSet, NFR-03 rusak diam-diam
  - Files: sosmed_sentiment/cli/analyze.py
- [ ] **D8 (P1, human: ~1j / CC: ~10mnt) — cli** — --no-negation + --lexicon-config starter sebagai escape hatch
  - Surfaced by: devex-review — DX F6 - perubahan berisiko tertinggi rilis tanpa saklar mati
  - Files: sosmed_sentiment/cli/analyze.py
- [ ] **T10 (P2, human: ~1j / CC: ~10mnt) — errors** — Tutup 8 GAP non-kritis dari Failure Modes Registry
  - Surfaced by: ceo-review — Section 2, Section 4
  - Files: sosmed_sentiment/
- [ ] **T6 (P2, human: ~3j / CC: ~20mnt) — cli** — FR-09 --dry-run
  - Surfaced by: ceo-review — Item 2
  - Files: sosmed_sentiment/cli/analyze.py
- [ ] **T7 (P2, human: ~2j / CC: ~15mnt) — observability** — 3 metrik baru: raw vs stemmed hit, komentar terbalik negasi, komentar 0 token
  - Surfaced by: ceo-review — Section 8
  - Files: sosmed_sentiment/cli/analyze.py, sosmed_sentiment/output/serializer.py
- [ ] **T8 (P2, human: ~4j / CC: ~30mnt) — kalibrasi** — Sapuan threshold dipisah komentar pendek vs panjang, plus dedup
  - Surfaced by: ceo-review — Item 3 + CEO voice HIGH 9 - oov_ratio bimodal di komentar pendek
  - Files: sosmed_sentiment/tools/calibrate_thresholds.py
- [ ] **T9 (P2, human: ~2j / CC: ~15mnt) — kalibrasi** — Sampling berstrata + skoring label, satu angka akurasi keseluruhan
  - Surfaced by: ceo-review — Item 3 Tahap B + CEO voice HIGH 8 - klaim per-band dicoret
  - Files: sosmed_sentiment/tools/sample_for_labeling.py, sosmed_sentiment/tools/score_calibration.py
- [ ] **E13 (P2, human: ~30mnt / CC: ~5mnt) — preprocessing** — Log WARNING + hitung saat fallback length-mismatch stem() menyala
  - Surfaced by: eng-review — eng M2 - satu-satunya penjamin kesejajaran indeks, tak diuji tak dicatat
  - Files: sosmed_sentiment/preprocessing/stemming.py
- [ ] **E14 (P2, human: ~1j / CC: ~10mnt) — lexicon** — Verifikasi sha256 kedua TSV di build_lexicon; --ref untuk pin fetch
  - Surfaced by: eng-review — eng - SOURCE.md mencatat hash yang tidak ada yang verifikasi
  - Files: sosmed_sentiment/tools/build_lexicon.py
- [ ] **E15 (P2, human: ~30mnt / CC: ~5mnt) — docs** — Perbaiki Architecture.md §2: stem() TIDAK punya lru_cache; tambah baris tools/ ke Rules.md §3
  - Surfaced by: eng-review — eng H8/M4 - dokumen salah tentang kodenya sendiri; plan mempercayainya dua kali
  - Files: docs/Architecture.md, docs/Rules.md
- [ ] **E16 (P2, human: ~1j / CC: ~10mnt) — sentiment** — Dedup juga di jalur produksi, bukan cuma kalibrasi
  - Surfaced by: eng-review — eng M7 - Item 3 mengkalibrasi distribusi yang run sungguhan tak pernah lihat
  - Files: sosmed_sentiment/cli/analyze.py
- [ ] **D10 (P2, human: ~1j / CC: ~10mnt) — cli** — --price-input/--price-output + mata uang eksplisit; --escalation-budget sebagai pecahan
  - Surfaced by: devex-review — DX F8 - 1m ambigu, mata uang tak pernah disebut, satuan bentrok di skrip yang sama
  - Files: sosmed_sentiment/cli/analyze.py
- [ ] **D11 (P2, human: ~2j / CC: ~15mnt) — kalibrasi** — --force, merge parsial, mode --validate
  - Surfaced by: devex-review — DX F16/F17 - re-run menghancurkan label parsial; nol umpan balik sampai akhir
  - Files: sosmed_sentiment/tools/sample_for_labeling.py, sosmed_sentiment/tools/score_calibration.py
- [ ] **D12 (P2, human: ~20mnt / CC: ~5mnt) — tools** — Progress di build_lexicon + baris 'sekitar 4 menit' di awal
  - Surfaced by: devex-review — DX F12 - diam 4 menit mengundang Ctrl-C
  - Files: sosmed_sentiment/tools/build_lexicon.py
- [ ] **D9 (P2, human: ~2j / CC: ~15mnt) — cli** — --month, --output opsional saat dry-run, perintah lengkap dicetak di ringkasan
  - Surfaced by: devex-review — DX F7/F9 - 8 flag diketik dari ingatan sekali sebulan
  - Files: sosmed_sentiment/cli/analyze.py
- [ ] **T11 (P3, human: ~10mnt / CC: ~3mnt) — docs** — Buat TODOS.md, perbaiki sentiment-pipeline-design.md:99
  - Surfaced by: ceo-review — 0D cherry-pick 4 dan 5 + prior learning design-doc-can-go-stale-mid-session
  - Files: TODOS.md, docs/designs/sentiment-pipeline-design.md
## STATUS: MENUNGGU KEPUTUSAN USER (2026-08-30)

Gate `/autoplan` sudah dipresentasikan. User minta waktu untuk memikirkannya.
**Tidak ada implementasi yang dijalankan. Tidak ada kode yang diubah.**

Empat keputusan masih terbuka, menunggu jawaban:

| # | Keputusan | Inti persoalannya |
|---|---|---|
| UC1 | Buka ulang ADR-02 (hybrid) atau tetap? | LLM-only terukur ~$0,13-$2,90 per run bulanan. Premis "LLM murni mahal" tidak pernah dihitung dan kemungkinan salah di skala ini. Mungkin ada alasan non-biaya (kedaulatan data / offline / kebijakan) yang belum tertulis. |
| UC2 | Evaluasi model Indonesia terlatih? | `w11wo/indonesian-roberta-base-sentiment-classifier` diverifikasi ada. Menghapus Item 1 dan 3. Harga: `torch` ~2,5 GB di repo yang sengaja dipilih ringan. |
| UC3 | Tetapkan target akurasi? | Nol target akurasi di kelima dokumen. Tanpa itu, tidak ada definisi selesai, dan Item 3 menyetel threshold ke anggaran biaya, bukan ke kebenaran. |
| T-CACHE | Cache preprocessing? | Hemat 15 menit per siklus dry-run. Di luar tulisan FR-09. Taste call, tidak mengubah arah. |

**Empat pilihan yang ditawarkan di gate** (tetap berlaku saat user kembali):
A. Ukur dulu baru putuskan — commit, satu panggilan router nyata, label 200 komentar,
   adu tiga kandidat terhadap label itu, baru putuskan Item 1/2/3 hidup atau mati.
B. Tetap rencana awal — pegang ADR-02, jalankan 40 tugas berurutan.
C. Amankan yang sudah pasti — commit + perbaiki negasi + perbaiki rumus confidence, lalu berhenti.
D. Tanya dulu.

**Berlaku terlepas dari keputusan apa pun (tidak ada perdebatan soal ini):**
- Seluruh kerja dua sesi (315 test, `sosmed_sentiment/`, 5 dokumen) masih **nol commit**
  di working tree. Satu `git checkout` yang salah menghapus semuanya.
- Bug negasi nyata dan terbukti: `['tidak','bagus']` -> positif confidence 1,0.
- Rumus confidence: tiap kecocokan satu kata InSet melapor keyakinan 1,0
  (`0,2 / 0,15` dipotong jadi 1,0).

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | issues_open | 5 proposals, 3 accepted, 1 deferred; 2 critical gaps |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | codex CLI not installed |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | issues_open | 19 issues, 8 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | skipped | no UI scope detected |
| DX Review | `/plan-devex-review` | Developer experience gaps | 1 | issues_open | score 3/10 to 8/10, TTHW unmeasurable to 5 min |

- **CROSS-MODEL:** Codex unavailable on this machine (binary not installed), so every phase ran `[subagent-only]`. Three independent Claude subagents (CEO, DX, Eng) each ran against the plan with no prior-phase context. Sixteen of their load-bearing claims were re-verified directly against the repo, the real 6,158-comment corpus, and the network. Sixteen of sixteen held. Three of them proved this plan factually wrong.
- **VERDICT:** NOT CLEARED — eng review has 8 critical gaps and 4 unresolved decisions requiring the user. The plan is materially better than it was and is not yet safe to implement as written.

**UNRESOLVED DECISIONS:**
- UC1 — ADR-02 rests on an unpriced premise: LLM-only costs about $0.13 to $2.90 per monthly run. Reopen or confirm.
- UC2 — A pretrained Indonesian sentiment model (verified to exist) was never considered and would delete items 1 and 3; it costs a 2.5 GB torch dependency.
- UC3 — No accuracy target exists in any of the five documents, so nothing here has a definition of done.
- T-CACHE — Preprocessing cache for dry-run: saves 15 minutes per cycle, sits outside FR-09 as written.
