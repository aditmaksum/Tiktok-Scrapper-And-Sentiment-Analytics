<!-- /autoplan restore point: /c/Users/asets/.gstack/projects/romysaputrasihananda-tiktok-comment-scrapper/master-autoplan-restore-20260829-002510.md -->
# Design: Sampling Video dari Mirror Orderan

Status: REVIEWED (/autoplan 2026-08-29, mode SELECTIVE EXPANSION)
Branch: master
Menambah, bukan mengganti: Fase 1 (`batch.py`) tetap apa adanya.
Berdampingan dengan: `phase-2-and-3-discovery.md` (pemeringkatan lewat SQL tetap berlaku).

## Masalah

`mirror_orderan_aff_tiktok.csv` adalah export SQL dari database order perusahaan.
Isinya ribuan baris dengan dua kolom: `id_konten` dan `account_type`. Satu baris
adalah satu order, bukan satu video, jadi satu video populer bisa muncul ratusan
kali.

Menjalankan `batch.py` atas seluruh file itu tidak mungkin: pada kecepatan terukur
~123 detik per video, 1000 video butuh ~34 jam berjalan tanpa putus. Yang
dibutuhkan bukan semua video, melainkan potret bulanan yang mewakili.

Komposisi datanya timpang: mayoritas baris adalah affiliate. Sampling acak polos
akan menghasilkan sampel yang hampir seluruhnya affiliate, sementara akun KOL dan
official justru yang paling ingin dipantau sentimennya.

## Yang dibangun

CLI baru `sample.py` plus modul `tiktokcomment/sampler.py`. Outputnya CSV yang
langsung diterima `batch.py` apa adanya. Tidak ada perubahan perilaku pada scraper.

```sh
python sample.py --input=mirror_orderan_aff_tiktok.csv --size=150 --dry-run
python sample.py --input=mirror_orderan_aff_tiktok.csv --size=150 --output=runs/samples/2026-09.csv
python batch.py --input=runs/samples/2026-09.csv
```

### Alur

1. **Baca** CSV mirror lewat `runner.read_rows()` yang sudah ada. Fungsi itu sudah
   menerima `id_konten` maupun `url_or_id`, menangani BOM, sel kosong, baris rusak,
   dan sudah membuang duplikat lewat set `seen`.
2. **Normalisasi id secara offline.** `parse_aweme_id` melakukan HTTP HEAD untuk
   short link; dipakai atas ribuan baris itu berarti ribuan request sebelum
   scraping dimulai. Tambahkan parameter `resolve_short_links: bool = True` dan
   panggil sampler dengan `False`. Default tidak berubah, jadi `batch.py` tetap
   berperilaku sama.
3. **Dedup per video** sudah gratis dari `read_rows`. Tanpa itu sampling jadi
   berbobot jumlah order, bukan acak per video.
4. **Klasifikasi tier** dari `account_type`, cocok substring dan `casefold()`,
   karena nilainya teks bebas (`kol account`, `affiliate account`):
   - Tier 1: mengandung `kol`
   - Tier 2: mengandung `official`
   - Tier 3: mengandung `affiliate`
   - Tier 4: sisanya, termasuk sel kosong (label `unknown` dari `read_rows`)

   Video yang cocok lebih dari satu kata kunci masuk tier prioritas tertinggi
   yang cocok, jadi `kol official` jatuh ke Tier 1.
5. **Kuota per tier, bukan prioritas berjenjang polos.** Default `50,30,20`
   (KOL, official, affiliate), bisa diubah lewat `--quota`. Keputusan user
   2026-08-29: affiliate harus selalu kebagian. Prioritas berjenjang polos
   memberi affiliate nol slot kapan pun KOL+official melebihi kuota, dan bulan
   berikutnya angka affiliate jadi tidak bisa dibandingkan karena tidak ada
   datanya.

   - **Pembulatan sisa terbesar.** `floor(size * persen)` dulu, lalu slot sisa
     diberikan ke pecahan terbesar; seri dimenangkan tier prioritas lebih tinggi.
     Total selalu persis `--size`. Contoh: 151 -> 75,5/45,3/30,2 -> 76/45/30.
   - **Tumpahan mengalir turun** menurut urutan prioritas KOL, official,
     affiliate, unknown. Kalau kuota KOL 75 tapi hanya ada 20 kandidat, 55 slot
     sisa tidak dibuang - mengalir ke official, lalu affiliate. Affiliate boleh
     melampaui 20% karena sampel penuh lebih berharga daripada proporsi murni.
     Tumpahan dicatat di log dan manifest.
   - **Tier `unknown` tidak dapat jatah.** Hanya menerima tumpahan, paling
     akhir. Pembagian 50-30-20 tetap utuh, dan barisnya tidak dibuang diam-diam.
6. **Seed.** `--seed` membuat hasil bisa diulang. Kalau tidak diberi, seed acak
   dibuat sendiri dan dicatat di manifest.
7. **Urutan output diacak.** Baris hasil dikocok sebelum ditulis, tidak
   dikelompokkan per tier. Alasannya operasional: batch berjalan berjam-jam dan
   bisa mati di tengah. Kalau output berurut KOL dulu, batch yang mati di 40%
   menghasilkan nol video affiliate. Dikocok, sampel parsial tetap mewakili
   semua tier.
8. **Output** CSV `url_or_id,account_type` dengan `account_type` asli
   dipertahankan apa adanya, plus manifest JSON di sebelahnya (seed, jumlah per
   tier, jumlah duplikat yang dibuang, waktu, nama file input, perkiraan durasi
   batch).
9. **`--exclude`** membuang video yang sudah discrape bulan sebelumnya, dibaca
   dari `runs/*/comments.json`, supaya sampel bulan ini tidak mengulang bulan lalu.
10. **`--dry-run`** mencetak komposisi tier dan perkiraan durasi tanpa menulis file.

## Step 0 — Hasil tantangan scope

### 0A. Premise Challenge

| # | Premis | Status |
|---|---|---|
| P1 | Scrape seluruh mirror tidak mungkin | TERBUKTI - 123 detik/video terukur pada run 2026-08 |
| P2 | Satu baris = satu order, ada video duplikat | DIASUMSIKAN - dedup tetap aman kalau ternyata sudah unik |
| P3 | Mayoritas affiliate | DINYATAKAN USER - diterima |
| P4 | KOL + official diprioritaskan | DINYATAKAN USER - diterima |
| P5 | Sampling acak metode yang benar | DIPUTUSKAN USER 2026-08-29: acak berjenjang dibangun, jalur SQL berperingkat TETAP berlaku. Keduanya menghasilkan CSV berbentuk sama, jadi tidak saling meniadakan. |

### 0B. What already exists

| Sub-masalah | Kode yang sudah ada | Dipakai ulang? |
|---|---|---|
| Baca CSV `id_konten`/`url_or_id` + `account_type` | `runner.read_rows()` (`tiktokcomment/runner.py:44`) | YA - termasuk BOM, sel kosong, laporan baris dilewat |
| Buang video duplikat | set `seen` di dalam `read_rows` | YA - gratis |
| Ubah URL jadi aweme_id | `parse_aweme_id()` (`tiktokcomment/tiktokcomment.py:24`) | SEBAGIAN - butuh mode offline |
| Tulis CSV yang dibaca Excel | pola `_assemble()`, `utf-8-sig` + `csv.DictWriter` | Pola saja |
| Validasi flag CLI | pola `batch.py` (`_parse_range`, `_check_month`) | Pola saja |
| Konsumsi output | `batch.py --input` | YA - tanpa perubahan |

Tidak ada yang dibangun ulang. Yang baru hanya logika tier dan pemilihan acak.

### 0C. Dream state

```
  CURRENT STATE                     THIS PLAN                      12-MONTH IDEAL
  operator menyusun CSV     --->    satu perintah mengubah   --->  SQL -> sample -> batch
  video manual tiap bulan;          mirror order jadi sampel        jalan sebagai satu rantai;
  batch 11 video pertama            bulanan yang bisa                sentimen per account_type
  dirakit tangan; tidak ada         direproduksi (seed, tier,        terlacak antar bulan;
  catatan kenapa video itu          manifest)                        sampel antar bulan tidak
  yang dipilih                                                       tumpang tindih tanpa sengaja
```

Delta: rencana ini mencapai sekitar 80% dari ideal. Sisanya adalah pelacakan
sentimen antar bulan, yang bukan urusan scraper.

### 0C-bis. Alternatif implementasi

```
APPROACH A: Sampler CLI terpisah, minimal
  Summary: sample.py + sampler.py, kuota total, prioritas berjenjang, tulis CSV.
  Effort:  S (human ~3 jam / CC ~20 menit)
  Risk:    Low
  Pros:    Diff kecil; batch.py tidak tersentuh; CSV perantara bisa diperiksa mata.
  Cons:    Tanpa manifest, sampel bulan lalu tidak bisa direproduksi atau dibuktikan.
  Reuses:  read_rows, pola CLI batch.py
  Completeness: 7/10

APPROACH B: Flag --sample di dalam batch.py
  Summary: batch.py membaca mirror langsung dan menyampel sendiri sebelum scraping.
  Effort:  S (human ~2 jam / CC ~15 menit)
  Risk:    Med
  Pros:    Satu perintah saja; tidak ada file perantara.
  Cons:    Tidak ada CSV yang bisa diperiksa sebelum membakar 5 jam scraping;
           sampel tidak bisa diulang; batch.py jadi punya dua tanggung jawab.
  Completeness: 5/10

APPROACH C: Sampler lengkap (DIPILIH)
  Summary: A ditambah manifest JSON, --dry-run, --exclude lintas bulan, --seed,
           urutan output dikocok, perkiraan durasi batch.
  Effort:  M (human ~1 hari / CC ~40 menit)
  Risk:    Low
  Pros:    Sampel bisa dibuktikan dan diulang; --dry-run mencegah salah kuota
           sebelum jam-jaman terbuang; --exclude membuat kadensi bulanan nyata.
  Cons:    Empat flag lebih banyak untuk dipelajari; satu file lebih banyak diuji.
  Reuses:  read_rows, pola CLI batch.py, runs/ layout
  Completeness: 10/10
```

**KEPUTUSAN OTOMATIS: APPROACH C** (Prinsip 1 completeness + Prinsip 2 boil lakes).
Selisih C dari A adalah beberapa flag dan satu file manifest; dengan CC selisih itu
menit, sementara nilainya adalah sampel yang bisa dipertanggungjawabkan bulan depan.

### 0D. Cherry-pick (SELECTIVE EXPANSION, diputus otomatis)

| # | Peluang | Effort | Keputusan | Alasan |
|---|---|---|---|---|
| 1 | `--dry-run` komposisi tier | S | DITERIMA | Mencegah salah kuota sebelum 5 jam scraping terbuang |
| 2 | Manifest JSON | S | DITERIMA | Satu-satunya cara membuktikan sampel bulan lalu |
| 3 | `--exclude` lintas bulan | S | DITERIMA | Inti kadensi bulanan; tanpa ini sampel bisa mengulang |
| 4 | Kuota per tier eksplisit | S | **DITERIMA** (user 2026-08-29) | Default `--quota 50,30,20`; affiliate dijamin kebagian |
| 5 | `--seed` + seed tercatat | S | DITERIMA | Reproduksi; juga membuat test deterministik |
| 6 | Perkiraan durasi batch dicetak | S | DITERIMA | 123 detik/video sudah terukur; operator tahu ongkosnya di muka |
| 7 | Mode proporsional bertingkat | M | DIBATALKAN | #4 diterima, jadi ini redundan |

### 0E. Temporal interrogation

```
  HOUR 1 (fondasi)    : Nama kolom dan kata kunci tier. Sudah diputus:
                        id_konten/url_or_id; kol|official|affiliate, casefold, substring.
  HOUR 2-3 (inti)     : Kalau Tier 1 lebih besar dari kuota? Sampel acak di dalam Tier 1.
                        Kalau account_type kosong? Tier 3, tetap ikut, tidak dibuang.
  HOUR 4-5 (integrasi): Kejutan - read_rows memanggil parse_aweme_id yang melakukan
                        HTTP HEAD untuk short link. Ribuan baris = ribuan request.
                        Wajib ada mode offline sebelum sampler menyentuh file besar.
  HOUR 6+ (poles)     : Yang akan disesali kalau tidak direncanakan sekarang -
                        urutan output. Dikocok, bukan dikelompokkan per tier.
```

## Review Sections

### Section 1 - Architecture

```
  SEBELUM                              SESUDAH
  ┌──────────┐                         ┌──────────┐   ┌────────────┐
  │ batch.py │                         │ batch.py │   │ sample.py  │
  └────┬─────┘                         └────┬─────┘   └─────┬──────┘
       │                                    │               │
       ▼                                    ▼               ▼
  ┌──────────┐                         ┌──────────┐   ┌────────────┐
  │ runner   │                         │ runner   │◀──│ sampler    │
  │ read_rows│                         │ read_rows│   │ tier+acak  │
  │ run_batch│                         │ run_batch│   └─────┬──────┘
  └────┬─────┘                         └────┬─────┘         │
       ▼                                    ▼               ▼
  ┌──────────────┐                     ┌──────────────┐  ┌────────┐
  │ TiktokComment│                     │ TiktokComment│  │ CSV +  │
  │ (jaringan)   │                     │ (jaringan)   │  │manifest│
  └──────────────┘                     └──────────────┘  └────────┘
```

Sampler bergantung pada `read_rows`, bukan sebaliknya. Tidak ada siklus. Sampler
tidak pernah menyentuh jaringan.

Empat jalur data:

```
  INPUT CSV ──▶ read_rows ──▶ klasifikasi tier ──▶ sampel acak ──▶ tulis CSV+manifest
      │              │               │                  │                │
      ▼              ▼               ▼                  ▼                ▼
  [file hilang]  [tanpa kolom]  [account_type    [kuota > tersedia]  [dir tak bisa
   click exit 2   ScrapeError    kosong -> Tier 3] ambil semua,       ditulis] GAP
                                                    peringatan
  [header saja]  [id tak       [semua satu tier] [kuota < 1]        [path adalah
   0 baris ->     terbaca]      isi dari tier     ditolak sebelum     direktori] GAP
   exit 1         dilewat +     itu saja,         apa pun jalan
                  dilaporkan    peringatan
```

Skala: 10x (10 ribu baris) dan 100x (100 ribu baris) sama saja - `read_rows` O(n)
dengan satu set, seluruhnya di memori, sekitar 10 MB pada 100 ribu baris. Tidak ada
titik gagal tunggal: proses lokal, tanpa jaringan, tanpa DB.

Rollback: hanya file baru plus satu parameter berdefault pada `parse_aweme_id`.
`git revert` cukup. Tidak ada state yang perlu dimigrasikan. Reversibility 5/5.

**TEMUAN A1 (Medium).** CSV hasil sampling berisi `id_konten` internal perusahaan.
`.gitignore` sudah menutup `*_orderan_*.csv` dan `runs/`, tapi tidak menutup file
seperti `videos-2026-09.csv` di root. Perbaikan: default output ke
`runs/samples/<label>.csv` (sudah tercakup `runs/`) dan tambahkan pola
`videos-*.csv` serta `*-sample.csv` ke `.gitignore`. Pola `videos.example.csv`
yang dilacak git tidak ikut tertutup.

### Section 2 - Error & Rescue Map

```
  CODEPATH                | WHAT CAN GO WRONG            | EXCEPTION CLASS
  ------------------------|------------------------------|-------------------------
  sample.py main          | file input tidak ada         | click UsageError (exit 2)
                          | --size < 1                   | (validasi sendiri)
                          | --output menunjuk direktori  | IsADirectoryError
                          | direktori output tak bisa    | PermissionError / OSError
                          |   ditulis                    |
  sampler.read_candidates | tidak ada kolom video        | ScrapeError
                          | file bukan UTF-8             | UnicodeDecodeError
                          | nol baris terpakai           | ScrapeError
  sampler.load_exclusions | comments.json rusak          | ValueError
                          | file exclude tidak ada       | (dilewat, peringatan)
  sampler.sample          | kuota > kandidat             | (bukan error, peringatan)
                          | satu tier kosong             | (bukan error, peringatan)

  EXCEPTION CLASS       | RESCUED? | RESCUE ACTION                  | USER SEES
  ----------------------|----------|--------------------------------|---------------------
  click UsageError      | Y        | click sendiri                  | pesan click, exit 2
  ScrapeError           | Y        | log pesan, exit 2              | satu baris tanpa traceback
  UnicodeDecodeError    | N <- GAP | -                              | traceback <- BURUK
  PermissionError/OSError| N <- GAP| -                              | traceback <- BURUK
  IsADirectoryError     | N <- GAP | -                              | traceback <- BURUK
  ValueError (exclude)  | N <- GAP | -                              | traceback <- BURUK
```

Empat GAP. Semuanya diperbaiki dengan pola yang sudah dipakai repo ini: tangkap
di batas CLI, ubah jadi `ScrapeError` dengan pesan yang menyebut file dan flag
yang salah, keluar dengan kode 2, tanpa traceback. Operator meneruskan satu baris
itu ke pemelihara; traceback tidak memberi tahu apa pun kepada mereka.

Tidak ada `except Exception` di rencana ini.

### Section 3 - Security & Threat Model

| Ancaman | Likelihood | Impact | Dimitigasi? |
|---|---|---|---|
| CSV formula injection lewat `account_type` (`=cmd\|...` dibuka di Excel) | Med | High | **BELUM - TEMUAN A2** |
| Path traversal lewat `--output` | Low | Med | Belum; validasi seperti `_check_month` |
| Data order internal ikut ter-commit | Med | Med | Lihat TEMUAN A1 |
| Dependency baru | - | - | Tidak ada; `random`, `csv`, `json` stdlib |
| PII | Low | Low | Tahap sampling hanya menyentuh id video, bukan komentar |

**TEMUAN A2 (High, dua tempat).** `account_type` adalah teks bebas dari database
dan ditulis apa adanya ke CSV yang dibuka analis di Excel. Sel yang diawali
`=`, `+`, `-`, atau `@` dieksekusi Excel sebagai formula. Paparan yang sama sudah
ada sekarang di `_assemble()` untuk kolom `comment`, `nickname`, dan `caption` -
teks yang datang dari internet dan sepenuhnya dikendalikan orang asing. Itu jalur
yang lebih berbahaya daripada sampler.

Perbaikan: satu helper bersama yang memberi prefix `'` pada sel yang diawali
karakter itu. **Diangkat sebagai TASTE DECISION**: pasang di sampler saja, atau
sekalian di `_assemble` (yang mengubah bentuk `comments.csv` yang sudah ada).

### Section 4 - Data flow & edge cases

```
  INTERAKSI            | EDGE CASE                    | HANDLED? | HOW
  ---------------------|------------------------------|----------|---------------------------
  sample.py dijalankan | --size 0 atau negatif        | RENCANA  | tolak sebelum baca file
                       | --size > jumlah kandidat     | RENCANA  | ambil semua + peringatan
                       | file hanya header            | RENCANA  | exit 1, "nothing to sample"
                       | seluruh baris satu tier      | RENCANA  | isi dari tier itu + peringatan
                       | account_type unicode/casing  | RENCANA  | casefold + substring
                       | dijalankan dua kali, seed sama| RENCANA  | hasil identik (itu gunanya)
                       | dijalankan dua kali, tanpa seed| RENCANA | hasil beda, seed tercatat
  --exclude            | comments.json belum ada      | RENCANA  | dilewat + peringatan
                       | exclude menghabiskan kandidat| RENCANA  | exit 1 dengan pesan jelas
  batch.py membaca hasil| baris terkocok antar tier   | RENCANA  | sengaja - lihat Alur poin 7
                       | batch mati di 40%            | RENCANA  | sampel parsial tetap wakili tier
```

`--size 0` adalah pengulangan persis ISSUE-001 dari laporan QA 2026-08-28: cap nol
menghasilkan sukses palsu. **Prior learning applied**: validasi kuota sebelum
apa pun menyentuh file, sama seperti `--max-comments` di `batch.py:79`.

### Section 5 - Code quality

DRY: seluruh pembacaan CSV lewat `read_rows`. Menulis ulang parser CSV di sampler
akan menduplikasi penanganan BOM, sel kosong, dan pelaporan baris rusak yang sudah
diuji 15 test. Ditolak (Prinsip 4).

Penamaan: `sampler.py` dengan `classify_tier()`, `sample_rows()`, `write_sample()`.
Nama menyebut apa yang dilakukan, bukan bagaimana.

Kompleksitas: pengisian kuota berjenjang adalah satu loop atas tiga tier, tiga
cabang. Di bawah ambang lima.

Over-engineering check: tidak ada abstraksi tier yang bisa dikonfigurasi lewat
file; kata kunci ditulis sebagai konstanta modul. Eksplisit di atas pintar
(Prinsip 5).

### Section 6 - Test Review

```
  NEW CODEPATHS:
    classify_tier: kol / official / affiliate / kosong / campur / casing aneh
    sample_rows:   kuota < tier1 / kuota = total / kuota > total / satu tier saja
    seed:          seed sama -> hasil sama; seed beda -> hasil beda
    exclude:       exclude sebagian / exclude semua / file tidak ada / JSON rusak
    urutan output: hasil tidak terurut per tier
    parse offline: short link tidak memicu jaringan

  NEW ERROR PATHS (silang Section 2):
    --size < 1, file tanpa kolom video, nol baris terpakai, dir tak bisa ditulis,
    output adalah direktori, file bukan UTF-8, comments.json rusak

  NEW INTEGRATIONS: tidak ada panggilan jaringan baru sama sekali
```

Test yang membuat berani rilis jam 2 pagi Jumat: seed tetap menghasilkan daftar
video yang identik, dan sampler tidak pernah membuka soket. Yang kedua diuji
dengan monkeypatch `Session.head` menjadi peledak - kalau terpanggil, test gagal.

Test yang ditulis QA bermusuhan: file 100 ribu baris yang seluruhnya satu video
yang sama, dengan `--size=150`. Harus keluar 1 baris, bukan 150, dan berkata jelas
kenapa.

Risiko flaky: keacakan. Seluruh test menyuntik seed tetap. Tidak ada test yang
bergantung waktu, jaringan, atau urutan.

Piramida: seluruhnya unit. Tidak ada E2E karena tidak ada jaringan yang terlibat.

### Section 7 - Performance

Tidak ada query, tidak ada N+1, tidak ada koneksi. 100 ribu baris masuk memori
sekitar 10 MB. Jalur paling lambat adalah membaca file: p99 di bawah satu detik
untuk file ukuran mirror sekarang.

Yang mahal bukan sampler melainkan konsekuensinya: setiap 10 video yang dipilih
berarti sekitar 20 menit scraping. Karena itu perkiraan durasi dicetak sebelum
operator menjalankan `batch.py`.

### Section 8 - Observability

Baris log (pola loguru yang sudah dipakai): jumlah baris dibaca, jumlah duplikat
dibuang, jumlah per tier sebelum sampling, jumlah per tier sesudah, seed terpakai,
jumlah yang dikeluarkan `--exclude`, perkiraan durasi batch, path file ditulis.

Manifest JSON adalah jejak audit permanen. Tiga minggu setelah rilis, pertanyaan
"kenapa video ini yang masuk sampel September" dijawab dengan membaca manifest dan
menjalankan ulang dengan seed yang sama.

Tidak perlu dashboard atau alert: ini perkakas yang dijalankan tangan sebulan sekali.

### Section 9 - Deployment

Tidak ada migrasi, tidak ada flag fitur, tidak ada state bersama. Rilis berarti
menambah dua file dan satu parameter berdefault. Verifikasi pasca-rilis: jalankan
`--dry-run` atas mirror sungguhan dan periksa komposisi tier masuk akal, lalu
jalankan `batch.py` atas hasilnya dengan `--size` kecil.

Rollback: hapus dua file baru. `batch.py` dan scraper tidak pernah berubah.

### Section 10 - Long-term trajectory

Reversibility: 5/5. Utang teknis: nihil yang berarti. Ketergantungan jalur: satu
parameter baru berdefault pada `parse_aweme_id`; default menjaga perilaku lama,
jadi pemanggil lain tidak terpengaruh.

Pertanyaan satu tahun: seorang engineer baru membaca `sample.py` dan langsung
paham - baca CSV, golongkan, acak, tulis. Bagian yang butuh komentar hanyalah
kenapa urutan output dikocok, dan itu ditulis sebagai komentar di kode.

Setelah ini: sentimen per `account_type` antar bulan. Itu pekerjaan SQL atas
`comments.csv`, bukan pekerjaan scraper.

## Registry

### Failure Modes

```
  CODEPATH            | FAILURE MODE          | RESCUED? | TEST? | USER SEES        | LOGGED?
  --------------------|-----------------------|----------|-------|------------------|--------
  sample.py main      | --size < 1            | Y (plan) | Y     | pesan + exit 1   | Y
  sample.py main      | dir tak bisa ditulis  | Y (plan) | Y     | pesan + exit 2   | Y
  sample.py main      | output = direktori    | Y (plan) | Y     | pesan + exit 2   | Y
  read_candidates     | tanpa kolom video     | Y (ada)  | Y     | pesan + exit 2   | Y
  read_candidates     | file bukan UTF-8      | Y (plan) | Y     | pesan + exit 2   | Y
  read_candidates     | nol baris terpakai    | Y (plan) | Y     | pesan + exit 1   | Y
  load_exclusions     | comments.json rusak   | Y (plan) | Y     | peringatan, lanjut| Y
  sample_rows         | kuota > kandidat      | Y (plan) | Y     | peringatan       | Y
  sample_rows         | satu tier kosong      | Y (plan) | Y     | peringatan       | Y
  write_sample        | CSV formula injection | TASTE    | Y     | (lihat A2)       | -
```

Nol CRITICAL GAP setelah perbaikan yang direncanakan: tidak ada baris dengan
RESCUED=N dan USER SEES=Silent.

## NOT in scope

- `batch.py` dan scraper tidak diubah perilakunya.
- Tidak ada pembacaan metrik view/engagement. Pemeringkatan tetap urusan SQL.
- Tidak ada resolusi short link lewat jaringan di tahap sampling.
- Mode proporsional bertingkat: ditunda ke TODOS.
- Pelacakan sentimen antar bulan: pekerjaan SQL atas hasil, bukan scraper.

## Implementation Tasks

- [ ] **T1 (P1, human: ~1j / CC: ~10m)** — tiktokcomment.py — tambah `resolve_short_links: bool = True` pada `parse_aweme_id`, teruskan dari `read_rows`
  - Surfaced by: 0E Temporal — ribuan HTTP HEAD sebelum scraping dimulai
  - Files: `tiktokcomment/tiktokcomment.py`, `tiktokcomment/runner.py`
  - Verify: test monkeypatch `Session.head` jadi peledak, sampler tetap lulus
- [ ] **T2 (P1, human: ~3j / CC: ~20m)** — sampler.py — `classify_tier`, `sample_rows`, `write_sample`, manifest
  - Surfaced by: 0C-bis Approach C
  - Files: `tiktokcomment/sampler.py`
  - Verify: `pytest tests/test_sampler.py`
- [ ] **T3 (P1, human: ~2j / CC: ~15m)** — sample.py — CLI, validasi kuota, `--dry-run`, `--seed`, `--exclude`
  - Surfaced by: Section 4 — `--size 0` mengulang ISSUE-001
  - Files: `sample.py`
  - Verify: `python sample.py --input=videos.example.csv --size=0` keluar 1 dengan pesan
- [ ] **T4 (P1, human: ~30m / CC: ~5m)** — Section 2 — ubah empat GAP jadi `ScrapeError` di batas CLI
  - Surfaced by: Section 2 — UnicodeDecodeError, PermissionError, IsADirectoryError, ValueError
  - Files: `sample.py`, `tiktokcomment/sampler.py`
  - Verify: test per jalur, tanpa traceback di output
- [ ] **T5 (P2, human: ~15m / CC: ~3m)** — .gitignore — tutup `videos-*.csv` dan `*-sample.csv`, default output ke `runs/samples/`
  - Surfaced by: TEMUAN A1 — id konten internal bisa ter-commit
  - Files: `.gitignore`, `sample.py`
  - Verify: `git check-ignore -v runs/samples/2026-09.csv`
- [ ] **T6 (P2, human: ~30m / CC: ~5m)** — CSV formula injection guard (lingkup menunggu keputusan gate)
  - Surfaced by: TEMUAN A2
  - Files: `tiktokcomment/sampler.py` (+ `tiktokcomment/runner.py` kalau lingkup penuh dipilih)
  - Verify: sel `=cmd` keluar sebagai `'=cmd`
- [ ] **T7 (P2, human: ~2j / CC: ~15m)** — tests — cakupan penuh Section 6
  - Surfaced by: Section 6
  - Files: `tests/test_sampler.py`
  - Verify: `pytest`
- [ ] **T8 (P3, human: ~20m / CC: ~5m)** — README — bagian sampling bulanan
  - Surfaced by: Section 10 — pertanyaan satu tahun
  - Files: `README.md`
  - Verify: baca ulang

## Dual Voices — degradasi

```
CEO DUAL VOICES — CONSENSUS TABLE:
═══════════════════════════════════════════════════════════════
  Dimension                            Claude  Codex  Consensus
  ──────────────────────────────────── ─────── ────── ─────────
  1. Premises valid?                   OK      N/A    N/A
  2. Right problem to solve?           OK      N/A    N/A
  3. Scope calibration correct?        OK      N/A    N/A
  4. Alternatives sufficiently explored? OK    N/A    N/A
  5. Competitive/market risks covered? N/A     N/A    N/A
  6. 6-month trajectory sound?         OK      N/A    N/A
═══════════════════════════════════════════════════════════════
```

Codex: `[codex-unavailable: binary not found]`. Subagen Claude: tidak dijalankan -
kebijakan sesi ini melarang spawn subagen tanpa permintaan eksplisit user. Mode:
**single-reviewer**. Konsekuensi jujur: tidak ada suara model kedua yang menantang
temuan di atas. Kalau itu penting, jalankan `npm install -g @openai/codex` lalu
ulangi, atau minta subagen secara eksplisit.

---

## Fase 3 — Eng Review

Kode yang benar-benar dibaca untuk fase ini: `tiktokcomment/runner.py:44-109`
(`read_rows`), `tiktokcomment/tiktokcomment.py:24-57` (`parse_aweme_id`),
`batch.py:76-135` (validasi flag), `tiktokcomment/runner.py:330-360` (`_assemble`).

### E1 — `read_rows` menyimpan `account_type` kemunculan pertama

`read_rows` membuang duplikat dengan set `seen` dan menyimpan baris pertama.
Di mirror orderan, video yang sama bisa muncul ratusan kali, dan tidak ada
jaminan `account_type`-nya konsisten di seluruh baris itu. Yang menang adalah
yang kebetulan paling atas. Karena tier ditentukan dari kolom itu, ketidak-
konsistenan data langsung menggeser video antar tier.

Keputusan otomatis (Prinsip 5, eksplisit): tetap pertahankan first-wins, tapi
catat peringatan ketika baris duplikat membawa `account_type` yang **berbeda**.
Murah, dan memunculkan masalah kualitas data di mirror alih-alih menyembunyikannya.
Menambah satu dict kecil di `read_rows`.

### E2 — RNG harus instance, bukan global

`TiktokComment.__sleep` memakai `random.uniform` global. Sampler tidak berjalan
di proses yang sama, jadi tidak bentrok hari ini, tapi `random.seed()` global
membuat determinisme sampler bergantung pada apa pun yang menyentuh modul
`random` lebih dulu. Pakai `random.Random(seed)` sebagai instance milik sampler.
Determinisme jadi tertutup rapat dan bisa diuji: test boleh menyetel
`random.seed(0)` global dan output sampler tetap sama.

### E3 — Koreksi estimasi memori

Fase 1 menulis "sekitar 10 MB pada 100 ribu baris". Terlalu optimistis: 100 ribu
objek `Row` plus string plus set `seen` lebih dekat ke 25-30 MB. Tetap tidak
masalah, tapi angkanya dibetulkan supaya tidak dikutip salah nanti.

### E4 — `--exclude` membaca file yang membesar

`runs/<bulan>/comments.json` untuk 11 video sudah 1 MB. Untuk 150 video sekitar
14 MB, dan `--exclude` yang membaca beberapa bulan berarti `json.load` beberapa
puluh MB hanya untuk mengambil daftar `aweme_id`. Masih wajar sekarang.
Keputusan otomatis (Prinsip 3, pragmatis): pakai `json.load` yang sederhana,
tapi catat batasnya di komentar. Kalau suatu saat lambat, `.partial.jsonl`
bisa dibaca baris per baris tanpa parse penuh.

Kenapa `comments.json` dan bukan manifest sampel bulan lalu: yang ingin dihindari
adalah video yang **sudah punya data**, bukan video yang sempat terpilih lalu
gagal discrape. Yang kedua justru layak dicoba lagi.

### E5 — `random.sample`, bukan shuffle-lalu-potong

Untuk mengisi kuota dari satu tier, `Random.sample(population, k)` adalah
O(k) dan langsung menyatakan maksudnya. `shuffle` atas 100 ribu kandidat untuk
mengambil 40 adalah pemborosan yang juga lebih sulit dibaca.

### Test diagram + artefak

15 codepath baru dipetakan ke tipe test, jalur bahagia, jalur gagal, dan edge
case. Artefak lengkap ditulis ke
`~/.gstack/projects/romysaputrasihananda-tiktok-comment-scrapper/asets-master-test-plan-20260829-050328.md`.

```
ENG DUAL VOICES — CONSENSUS TABLE:
═══════════════════════════════════════════════════════════════
  Dimension                            Claude  Codex  Consensus
  ──────────────────────────────────── ─────── ────── ─────────
  1. Architecture sound?               OK      N/A    N/A
  2. Test coverage sufficient?         OK      N/A    N/A
  3. Performance risks addressed?      OK      N/A    N/A
  4. Security threats covered?         GAP A2  N/A    N/A
  5. Error paths handled?              4 GAP   N/A    N/A
  6. Deployment risk manageable?       OK      N/A    N/A
═══════════════════════════════════════════════════════════════
```

## Fase 3.5 — DX Review

Tipe produk: CLI internal. Persona: operator yang menjalankan batch bulanan -
paham terminal, tidak membaca kode scraper, dan membayar setiap kesalahan dengan
jam-jaman scraping.

### Peta perjalanan developer

| Tahap | Sekarang | Sesudah rencana |
|---|---|---|
| 1. Dapat file mirror | Export SQL | sama |
| 2. Tahu video mana discrape | Pilih tangan, tanpa catatan | `sample.py` |
| 3. Coba tanpa risiko | Tidak ada | `--dry-run` |
| 4. Tahu ongkosnya | Tidak tahu sampai batch jalan | perkiraan durasi dicetak |
| 5. Jalankan batch | `batch.py --input=...` | sama, tanpa perubahan |
| 6. Batch mati di tengah | checkpoint | sama, plus sampel terkocok tetap mewakili |
| 7. Ulangi bulan depan | Mulai dari nol | `--exclude` |
| 8. Buktikan pilihan bulan lalu | Tidak bisa | manifest + seed |
| 9. Ganti kuota | - | `--size`, dan lihat #4 di gate |

### Narasi empati

Saya operator. Saya punya file 4000 baris dan waktu semalam. Yang saya takutkan
bukan kodenya salah, tapi saya menekan enter dengan kuota keliru lalu tahu lima
jam kemudian bahwa isinya affiliate semua. `--dry-run` yang mencetak komposisi
tier dan "perkiraan 5,1 jam" menghapus ketakutan itu dalam dua detik.

### DX Scorecard

| # | Dimensi | Skor | Catatan |
|---|---|---|---|
| 1 | Time to hello world | 9/10 | Satu perintah `--dry-run`, di bawah 1 menit |
| 2 | Penamaan CLI konsisten | 8/10 | `--input`/`--output` ikut `batch.py`; `--size` ikut `main.py`. Catatan: `main.py` memakai `--aweme_id` bergaris bawah, satu-satunya di repo - jangan ditiru |
| 3 | Pesan error | 9/10 | Wajib pola repo: masalah + nilai yang diterima + cara benar |
| 4 | Dokumentasi | 7/10 | Butuh bagian README (T8); tanpa itu `--exclude` dan `--seed` tak akan ditemukan |
| 5 | Default & escape hatch | 8/10 | `account_type` tak dikenal jatuh ke Tier 3 dan tetap ikut, tidak dibuang diam-diam |
| 6 | Umpan balik saat jalan | 9/10 | Sampler instan; nilai sebenarnya ada di perkiraan durasi |
| 7 | Jalur upgrade | 10/10 | Alat baru; `parse_aweme_id` dapat parameter berdefault, pemanggil lama tidak terpengaruh |
| 8 | Friksi lingkungan | 10/10 | Nol dependensi baru; `random`, `csv`, `json` stdlib |

**Overall: 9/10. TTHW: < 1 menit (target < 5 menit).**

```
DX DUAL VOICES — CONSENSUS TABLE:
═══════════════════════════════════════════════════════════════
  Dimension                            Claude  Codex  Consensus
  ──────────────────────────────────── ─────── ────── ─────────
  1. Getting started < 5 min?          OK      N/A    N/A
  2. API/CLI naming guessable?         OK      N/A    N/A
  3. Error messages actionable?        OK      N/A    N/A
  4. Docs findable & complete?         GAP T8  N/A    N/A
  5. Upgrade path safe?                OK      N/A    N/A
  6. Dev environment friction-free?    OK      N/A    N/A
═══════════════════════════════════════════════════════════════
```

### DX Implementation Checklist

- [ ] Setiap pesan error menyebut masalah, nilai yang diterima, dan cara benar
- [ ] `--dry-run` adalah contoh pertama di README, bukan yang terakhir
- [ ] Perkiraan durasi memakai angka terukur 123 detik/video, bukan tebakan
- [ ] Seed selalu dicetak, termasuk saat dibuat otomatis
- [ ] Flag mengikuti `batch.py`, bukan `--aweme_id` gaya `main.py`

---

## Adendum 2026-08-29 — kuota tier diputuskan user

`--quota` default `50,30,20` untuk KOL, official, affiliate. Empat tier, bukan
tiga: KOL dan official dipisah, bukan digabung seperti draft pertama.

Perubahan yang mengikuti pada task list:

- **T2** bertambah: `allocate_quota()` dengan pembulatan sisa terbesar dan
  tumpahan berurut. Effort naik dari ~20 menit CC ke ~30 menit.
- **T3** bertambah flag `--quota`, divalidasi seperti `_parse_range` di
  `batch.py:113`: harus tiga angka, tidak boleh negatif, jumlahnya harus 100.
- **T7** bertambah delapan test: pembagian tepat (150 -> 75/45/30), pembagian
  dengan sisa (151 -> 76/45/30), tumpahan satu tingkat, tumpahan berantai dua
  tingkat, satu tier kosong sama sekali, semua kandidat satu tier, `--quota`
  tidak berjumlah 100 ditolak, `--quota` negatif ditolak.

Test yang paling penting dari kelompok itu: **affiliate tidak pernah nol selama
ada kandidat affiliate**. Itu isi permintaan user, dan satu-satunya cara tahu
kodenya masih memenuhinya enam bulan lagi.
