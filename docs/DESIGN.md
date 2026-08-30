# DESIGN — Sosmed Sentiment Pipeline

| | |
|---|---|
| **Versi** | 0.1 |
| **Tanggal** | 2026-08-30 |
| **Status** | Draf |
| **Sumber** | `PRD.md` v0.1, `Architecture.md` v0.1 |

Proyek ini tidak punya antarmuka aplikasi (CLI saja untuk kedua modul) — tapi **punya** satu artefak visual yang benar-benar dibaca manusia: laporan HTML dari Modul 2. Dokumen ini dipecah dua: format keluaran CLI (mengikuti pola dokumen untuk proyek tanpa UI), dan desain visual laporan HTML (karena itu tetap sebuah "layar" yang dilihat orang, meski dihasilkan statis).

> **ASUMSI PENTING:** Tidak ada acuan gaya visual brand yang dikonfirmasi untuk laporan ini (laporan HTML lain yang ada di lingkungan kerja sengaja **tidak** dijadikan acuan sesuai arahan eksplisit). Palet dan tipografi di bawah adalah default netral yang aman dipakai untuk laporan internal apa pun — ganti kapan saja tanpa mengubah struktur data atau logika Modul 2, karena style ada di template Jinja2 terpisah (`report.html.j2`).

## Bagian A — CLI (Modul 1 & Modul 2)

**Format keluaran terminal:**
- Progres tahap dicetak ke stderr dengan prefix level: `[INFO]`, `[WARNING]`, `[ERROR]`.
- Contoh: `[INFO] Ingest: 6158 komentar dibaca dari 200 video`
- Contoh: `[WARNING] 3 komentar dilewati karena field 'comment' tidak ada`
- Ringkasan akhir dicetak sebagai blok terpisah dengan garis pembatas, contoh:
  ```
  ==== Ringkasan Run ====
  Total komentar mentah   : 6158
  Dikecualikan (internal) : 1334
  Dianalisis              : 4824
  Sentimen: positif 1204 | negatif 892 | netral 2728
  Eskalasi ke LLM         : 612 (12.7%)
  Output tersimpan        : ./output/analysis_result.json
  ========================
  ```

**Struktur pesan error:** `[ERROR] <apa yang salah>: <detail>. <saran tindakan>`
Contoh: `[ERROR] Skema input tidak valid: field 'comments' hilang pada video aweme_id=7562480653489556757. Periksa kembali file sumber.`

**Kode keluar:** sesuai `Architecture.md` §6 (0 sukses, 1 error umum, 2 input tidak valid, 3 kegagalan LLM sistemik).

**Pemakaian warna terminal:** opsional, hanya kalau terminal mendukung ANSI color — merah untuk `[ERROR]`, kuning untuk `[WARNING]`, tanpa warna untuk `[INFO]`. Tidak wajib, tidak boleh jadi satu-satunya penanda level (prefix teks tetap ada sebagai fallback, sesuai prinsip aksesibilitas — jangan menyampaikan informasi hanya lewat warna).

## Bagian B — Desain Visual Laporan HTML

### 1. Arah Desain
Laporan ini dibaca oleh analis atau stakeholder non-teknis untuk memahami sentimen dan isu utama dari komentar sosmed dalam satu duduk baca — bukan dashboard yang dieksplorasi berulang. Kesan yang dibangun: rapi, mudah dipindai (scannable), netral secara warna brand (karena template ini dipakai lintas proyek). **Hindari**: warna-warna brand spesifik yang mengasumsikan satu klien tertentu, animasi/interaktivitas berlebihan (laporan ini statis dan sering dibuka lewat file lokal, bukan browser modern dengan JS penuh), dan kepadatan grafik yang butuh interaksi (hover, klik) untuk dibaca — karena akan dibuka offline dan mungkin di-screenshot/dicetak.

### 2. Token Desain

#### Warna
| Token | Nilai | Dipakai untuk |
|---|---|---|
| `--color-bg` | `#F7F8FA` | latar halaman |
| `--color-surface` | `#FFFFFF` | kartu ringkasan, tabel |
| `--color-text` | `#1A1D24` | teks utama |
| `--color-text-muted` | `#5B6270` | keterangan, metadata |
| `--color-border` | `#E2E5EA` | garis pemisah antar section |
| `--color-positif` | `#1E7E4F` | angka & bar sentimen positif |
| `--color-negatif` | `#B0362C` | angka & bar sentimen negatif |
| `--color-netral` | `#7A8290` | angka & bar sentimen netral |
| `--color-accent` | `#2454A6` | judul section, elemen navigasi |

Kontras teks utama (`#1A1D24`) di atas latar (`#F7F8FA` / `#FFFFFF`) berada jauh di atas rasio 4.5:1 (kombinasi gelap-di-atas-terang standar), aman untuk teks isi ukuran normal.

#### Tipografi
| Peran | Font | Ukuran | Tebal | Tinggi baris |
|---|---|---|---|---|
| Judul laporan | Inter (fallback: system-ui, sans-serif) | 28px | 700 | 1.3 |
| Judul section | Inter | 18px | 600 | 1.4 |
| Teks isi | Inter | 14px | 400 | 1.6 |
| Angka besar (metrik) | Inter | 32px | 700 | 1.2 |
| Keterangan kecil / metadata | Inter | 12px | 400 | 1.5 |

Satu keluarga font (Inter) via Google Fonts dengan fallback `system-ui, -apple-system, sans-serif` supaya tetap terbaca kalau dibuka offline tanpa akses ke Google Fonts (memenuhi NFR-04 di `PRD.md`).

#### Jarak & Sudut
- Skala jarak: 4 / 8 / 16 / 24 / 32 / 48px.
- Radius sudut kartu/kotak: 8px.
- Bayangan: satu level saja, tipis (`0 1px 3px rgba(0,0,0,0.08)`) untuk kartu ringkasan — hindari bayangan berlapis yang terlihat berat saat dicetak.

### 3. Tata Letak
- Lebar maksimum konten: 960px, ditengahkan (`margin: 0 auto`), padding samping 24px di layar sempit.
- Single-column — laporan ini dibaca berurutan dari atas ke bawah, bukan grid multi-panel seperti dashboard.
- Tidak perlu breakpoint kompleks karena tidak ada interaksi kompleks; cukup satu penyesuaian di lebar <600px (padding diperkecil, angka metrik besar diperkecil sedikit) supaya tetap terbaca kalau dibuka di HP.

### 4. Komponen Laporan
| Komponen | Deskripsi | Catatan |
|---|---|---|
| Kartu Metrik | Kotak putih, angka besar + label kecil di bawahnya | Dipakai untuk total komentar, jumlah per sentimen |
| Bar Distribusi Sentimen | Bar horizontal proporsional (CSS width%, bukan JS chart library) dengan warna sesuai token sentimen | Tanpa JS memastikan tetap tampil kalau dibuka dari file lokal dengan pembatasan skrip |
| Tabel Top Keyword | Tabel dua kolom: kata/frasa, jumlah kemunculan — dipisah per tab/section untuk overall vs per label sentimen | Section terpisah, bukan tab interaktif (supaya tetap terbaca kalau dicetak ke PDF) |
| Kartu Contoh Komentar | Kutipan komentar representatif per label sentimen, dengan username disamarkan sebagian (mis. `us***ti`) | Lihat catatan privasi di bawah |
| Blok Metodologi & Limitasi | Teks penjelasan singkat: metode hybrid dipakai, rasio eskalasi LLM, limitasi (reply pertanyaan ikut dihitung sentimen apa adanya) | Wajib ada — ini yang membedakan laporan jujur dari laporan yang terlihat rapi tapi menyesatkan |

> **ASUMSI:** Username di kartu contoh komentar disamarkan sebagian secara default untuk kehati-hatian privasi, meski datanya publik. Ini bisa dimatikan lewat opsi kalau ternyata analis butuh username utuh untuk tindak lanjut (mis. membalas komentar). Konfirmasi preferensinya.

### 5. Susunan Laporan (Layout dari Atas ke Bawah)

**SCR-01 — Laporan Sentimen & Messaging**
- **Tujuan:** Analis/stakeholder memahami distribusi sentimen dan isu utama dari satu batch komentar dalam satu kali baca.
- **Melayani:** FR-07
- **Data yang ditampilkan:** seluruh field di `analysis_result.json` §4 Schema.md — `meta`, `sentiment_summary`, `top_keywords_overall`, `top_keywords_by_sentiment`, `per_video` (ringkas, tabel), sample dari `comments[]` per label, `excluded_accounts_detected` (FR-10).
- **Aksi yang tersedia:** tidak ada aksi interaktif (statis) — hanya scroll & (opsional) navigasi anchor link ke tiap section lewat sticky nav sederhana.
- **Kondisi khusus:**
  - **Data kosong** (0 komentar dianalisis setelah exclude): tampilkan pesan eksplisit "Tidak ada komentar untuk dianalisis setelah exclude-list diterapkan — periksa apakah exclude-list terlalu luas" — bukan tabel/chart kosong tanpa penjelasan.
  - **Semua eskalasi LLM gagal:** blok metodologi menyorot peringatan bahwa sebagian signifikan data berstatus `tidak_terklasifikasi`, dengan jumlah pastinya.
- **Susunan (atas ke bawah):**
  1. Header: judul laporan, tanggal generate, nama file sumber, rentang tanggal komentar (`meta`).
  2. Baris kartu metrik: total komentar dianalisis, jumlah dikecualikan, rasio eskalasi LLM.
  3. Section Distribusi Sentimen: bar chart + angka & persentase per label.
  4. Section Messaging — Top Keyword Keseluruhan: tabel top-20.
  5. Section Messaging per Sentimen: tiga sub-tabel (positif/negatif/netral), top-10 masing-masing.
  6. Section Contoh Komentar Representatif: 3–5 kutipan per label.
  7. Section Ringkasan per Video (opsional/lipat jika video >20): tabel `per_video`.
  8. Section Transparansi Data: daftar `excluded_accounts_detected`, untuk pengecekan manual exclude-list (FR-10).
  9. Blok Metodologi & Limitasi (lihat komponen di atas) — selalu di bagian akhir sebagai catatan kaki laporan.

### 6. Aksesibilitas
- Kontras teks minimal 4.5:1 (dipenuhi lewat token warna di §2).
- Semua informasi status (sentimen positif/negatif/netral) memakai warna **dan** label teks eksplisit ("positif", bukan cuma warna hijau) — supaya tidak bergantung pada persepsi warna saja.
- Struktur heading HTML semantik (`<h1>` judul laporan, `<h2>` per section) supaya tetap bisa dinavigasi dengan pembaca layar meski laporan statis.

### 7. Gerak & Transisi
Tidak ada animasi — laporan statis, dibuka offline, kadang dicetak/screenshot. Transisi hover pada nav anchor (kalau ada) cukup instan/sangat singkat (~100ms), bukan elemen penting dari pengalaman membaca laporan.

### 8. Bahasa Laporan
- Bahasa Indonesia, register semi-formal (laporan internal, bukan dokumen legal).
- Label section pakai kata benda langsung ("Distribusi Sentimen", bukan "Lihat Distribusi Sentimen").
- Angka: pemisah ribuan pakai titik (`6.158`), desimal pakai koma (`12,7%`), mengikuti konvensi Bahasa Indonesia.
- Tanggal: format `DD Bulan YYYY` (mis. `30 Agustus 2026`) untuk keterbacaan manusia, bukan format ISO di tampilan (ISO tetap dipakai di data JSON mentahnya).

## Riwayat Perubahan
| Tanggal | Versi | Perubahan |
|---|---|---|
| 2026-08-30 | 0.1 | Draf awal — format CLI + desain visual laporan HTML dengan palet netral default (belum ada acuan brand) |
