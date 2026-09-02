# PRD — Sosmed Sentiment Pipeline

| | |
|---|---|
| **Versi** | 0.6 |
| **Tanggal** | 2026-08-30 |
| **Status** | Draf |
| **Sumber** | Diskusi 30 Agustus 2026 + file `comments.json` (200 video TikTok, 6.158 komentar+balasan) |

## 1. Ringkasan
Sosmed Sentiment Pipeline adalah dua alat command-line yang berjalan berurutan tapi independen: **Modul Analisis** mengubah data mentah komentar sosial media (saat ini format hasil scraping TikTok) menjadi klasifikasi sentimen (positif/negatif/netral) dan daftar top keyword/messaging yang muncul; **Modul Laporan** membaca hasil analisis itu dan menyusunnya jadi satu berkas HTML statis yang bisa dibaca offline. Penggunanya adalah analis internal yang perlu laporan sentimen per batch data komentar, tanpa harus mengulang seluruh proses NLP setiap kali cuma ingin mengubah tampilan laporan.

## 2. Masalah & Latar Belakang
Saat ini analisis sentimen komentar sosmed dilakukan manual (baca satu-satu atau spreadsheet), yang tidak mungkin diskalakan untuk ribuan komentar per batch (contoh data yang ada: 6.158 komentar dari 200 video). Kebutuhannya bukan sekadar hitung persentase positif/negatif, tapi juga menangkap *messaging* — topik/kata yang paling sering muncul di komentar, karena itu yang menunjukkan apa yang sebenarnya jadi perhatian audiens.

Dua kebutuhan ini (hitung sentimen, susun laporan) sengaja dipisah jadi dua alat agar masing-masing bisa dioptimalkan atau diganti sendiri-sendiri — misalnya kalau metode klasifikasi sentimen diganti nanti, modul laporan tidak perlu disentuh sama sekali selama kontrak data di antara keduanya tidak berubah.

## 3. Tujuan & Ukuran Keberhasilan
| ID | Tujuan | Ukuran keberhasilan | Target |
|---|---|---|---|
| G-01 | Klasifikasi sentimen otomatis menggantikan baca manual | Seluruh komentar (non-internal) di satu file input terklasifikasi tanpa intervensi manual per komentar | 100% coverage per run |
| G-02 | Messaging/top keyword merepresentasikan isu nyata, bukan noise | Top-20 keyword bisa ditelusuri balik ke komentar asli yang relevan (spot check manual) | Lolos spot check oleh analis |
| G-03 | Laporan bisa dibaca tanpa alat tambahan | Berkas HTML dibuka langsung dari file system, tanpa server, tanpa koneksi internet wajib | Terverifikasi dibuka offline |
| G-04 | Biaya panggilan LLM terkendali | Jumlah komentar yang dieskalasi ke LLM tercatat & tidak menyasar seluruh data | Rasio eskalasi dilog per run, dievaluasi setelah run pertama |

## 4. Pengguna & Peran
| Peran | Deskripsi | Kebutuhan utama | Hak akses inti |
|---|---|---|---|
| Analis (operator CLI) | Menjalankan kedua modul dari terminal, mengelola file konfigurasi (exclude-list akun, threshold) | Jalankan pipeline, baca log, buka laporan | Akses penuh ke filesystem lokal & config |

> **ASUMSI:** Sistem ini single-user, dijalankan lokal oleh satu analis per waktu. Tidak ada konsep login/otorisasi karena tidak ada komponen server. Konfirmasi kalau ternyata perlu dipakai bergantian oleh beberapa orang dengan hak berbeda.

## 5. Cakupan

### Termasuk (rilis ini)
- Ingest data komentar dari file JSON berformat hasil scraping TikTok (struktur `video → comments[] → replies[]`, sesuai `comments.json`).
- Filter akun internal/brand dari data sebelum dianalisis (exclude-list dikonfigurasi manual).
- Preprocessing teks Bahasa Indonesia lengkap (cleaning, normalizing, case folding, tokenizing, filtering, stemming) mengikuti urutan yang sudah disepakati di diskusi sebelumnya.
- Klasifikasi sentimen **hybrid**: model klasifikasi lokal (revisi 0.6, gantiin rencana lexicon awal — lihat `Architecture.md` ADR-02) sebagai pass pertama, eskalasi ke LLM untuk komentar yang confidence-nya rendah.
- Ekstraksi top keyword/messaging berbasis TF-IDF, dipecah per label sentimen (top keyword khusus komentar negatif vs positif vs netral).
- Output analisis dalam format JSON terstruktur sebagai kontrak resmi ke Modul Laporan.
- Generator laporan HTML statis single-file dari output JSON tersebut.
- Kedua modul berupa CLI terpisah, dijalankan manual.

### Tidak termasuk (sengaja ditunda)
- **Platform selain TikTok** (Instagram, X, YouTube) — skema inputnya berbeda. Arsitektur disiapkan agar bisa ditambah lewat pola adapter, tapi adapter lain tidak dibangun di rilis ini. *Alasan: belum ada data/contoh nyata untuk platform lain.*
- **Web UI / upload lewat browser** — CLI saja dulu. *Alasan: sesuai keputusan bentuk sistem di brief ini.*
- **Penyimpanan histori / database** — setiap run berdiri sendiri, tidak ada perbandingan antar periode otomatis. *Alasan: keputusan eksplisit user (one-off per file).*
- **Pipeline terjadwal/otomatis** — trigger manual saja. *Alasan: sesuai keputusan bentuk sistem.*
- **Deteksi otomatis akun internal/brand berbasis heuristik pola perilaku** (mis. "akun yang cuma pernah reply, tidak pernah comment top-level") — tetap ditunda, exclude-list untuk kasus ini tetap manual. *Alasan: heuristik pola perilaku berisiko salah mengecualikan pelanggan yang kebetulan pola komentarnya begitu.* **Dikecualikan dari penundaan ini:** akun pengunggah video itu sendiri — lihat FR-11, kasus ini beda karena akun pengunggah video secara definisi bukan komentator/pelanggan, jadi auto-exclude untuk kasus spesifik ini tidak punya risiko false-positive yang sama.
- **Deteksi kalimat tanya vs pernyataan sentimen** — komentar berupa pertanyaan ("dok ini bisa gak buat anak usia 2 tahun") akan tetap diklasifikasi sentimen apa adanya (biasanya netral), bukan dikategorikan terpisah sebagai "pertanyaan". *Alasan: di luar cakupan awal, dicatat sebagai limitasi.*

## 6. Kebutuhan Fungsional
| ID | Fitur | Deskripsi | Peran | Prioritas |
|---|---|---|---|---|
| FR-01 | Ingest & Flatten | Baca `comments.json`, ratakan struktur nested (video→comment→reply) jadi satu daftar komentar datar dengan metadata asal (video_id, is_reply, parent_comment_id) | Analis | Wajib |
| FR-02 | Exclude Akun Internal | Buang komentar dari akun yang ada di exclude-list config sebelum tahap analisis lain berjalan | Analis | Wajib |
| FR-03 | Preprocessing Teks | Jalankan pipeline: ekstraksi emoji → case folding → cleaning → normalizing → tokenizing → filtering stopword → stemming | Analis | Wajib |
| FR-04 | Klasifikasi Sentimen Hybrid | Pass 1 model sentimen lokal (`mdhugol/indonesia-bert-sentiment-classification`); komentar dengan confidence rendah dieskalasi ke LLM. Hasil: label + confidence + metode yang dipakai | Analis | Wajib |
| FR-05 | Ekstraksi Top Keyword/Messaging | TF-IDF unigram+bigram dari token hasil stemming, top-N keseluruhan dan top-N per label sentimen | Analis | Wajib |
| FR-06 | Serialisasi Hasil Analisis | Simpan seluruh hasil (per-komentar, agregat, top keyword, metadata run) ke satu file JSON sesuai `Schema.md` | Analis | Wajib |
| FR-07 | Generate Laporan HTML | Baca file JSON hasil analisis, susun laporan HTML statis satu file (ringkasan, distribusi sentimen, top keyword, contoh komentar representatif) | Analis | Wajib |
| FR-08 | CLI Interface | Kedua modul menerima argumen input/output path via command line, punya `--help`, exit code jelas | Analis | Wajib |
| FR-09 | Dry-run Estimasi Biaya LLM | Mode opsional yang menghitung berapa komentar akan dieskalasi ke LLM tanpa benar-benar memanggil API, supaya biaya bisa diperkirakan dulu | Analis | Sebaiknya |
| FR-10 | Laporan Transparansi Exclude-list | Laporan HTML menampilkan daftar akun paling sering muncul di data (top pengirim komentar/reply) supaya analis bisa cek manual apakah ada akun brand yang lolos belum di-exclude | Analis | Sebaiknya |
| FR-11 | Auto-exclude Akun Pengunggah Video | Kalau field `video_author_username` tersedia di `comments.json` (lihat catatan ketergantungan di bawah), buang komentar dari akun tsb otomatis, tanpa perlu masuk exclude-list manual — akun pengunggah video secara definisi bukan komentator | Analis | Sebaiknya |

### Kriteria Penerimaan

**FR-01 — Ingest & Flatten**
- Diberikan `comments.json` valid dengan struktur video→comments→replies, ketika dijalankan, maka menghasilkan daftar datar berisi seluruh 6.158 entri (komentar + balasan) dengan field asal yang bisa ditelusuri balik ke video aslinya.
- Kasus gagal: ketika file JSON tidak sesuai skema yang diharapkan (mis. field `comments` hilang), maka program berhenti dengan pesan error yang menyebutkan field mana yang bermasalah, exit code ≠ 0.

**FR-02 — Exclude Akun Internal**
- Diberikan exclude-list berisi `["dokterrizkimrd", "yayleindonesia", "yaylesupport"]`, ketika dijalankan pada data contoh, maka ketiga akun tersebut dan seluruh komentarnya tidak muncul di hasil analisis maupun hitungan sentimen/keyword.
- Kasus gagal: ketika exclude-list kosong atau tidak ada, maka program tetap jalan (bukan error), tapi log memperingatkan bahwa tidak ada akun yang dikecualikan.
- **Keputusan matching (sesi /plan-eng-review):** exact match, case-sensitive — TIDAK ada normalisasi/casefold. Keputusan sadar: username TikTok di data nyata konsisten lowercase, analis menilai resiko mismatch karena kapital kecil. Sama berlaku untuk matching `video_author_username` di FR-11.

**FR-11 — Auto-exclude Akun Pengunggah Video**
- **Sumber data (revisi 2026-08-30, sesi /plan-eng-review):** BUKAN dari panggilan API TikTok baru — TikTok `comment/list/` endpoint yang dipakai scraper tidak pernah mengembalikan info uploader, dan menambah endpoint video-detail terpisah akan dobelin request volume per video (resiko block). Sumber sebenarnya: analis sudah punya data ini di CSV input mereka sendiri (kolom baru `nama_pengguna_kreator`, ditambahkan ke `id_konten,account_type` yang sudah ada). Scraper (`tiktok-comment-scrapper/tiktokcomment/runner.py`) membaca kolom ini bareng `account_type` dan menempelkannya ke tiap video's entry sebagai `video_author_username` di `comments.json` — zero request tambahan ke TikTok.
- Diberikan `comments.json` yang punya field `video_author_username` terisi untuk suatu video, ketika ingest dijalankan, maka seluruh komentar dari akun tsb di video itu dibuang otomatis dari hasil analisis, dicatat di `exclude_reason` = `"video_uploader"` (beda dari `"internal_account"` untuk exclude-list manual).
- Kasus gagal/degradasi: kalau `video_author_username` tidak ada di video tertentu (baris CSV lama tanpa kolom ini, atau kolom dikosongkan), FR-11 di-skip untuk video itu tanpa error — exclude-list manual (FR-02) tetap jalan sebagai jaring pengaman.
- **Deteksi typo (sesi /plan-eng-review, critical gap):** kalau `video_author_username` diisi TAPI tidak ada satupun comment/reply di video itu yang usernamenya match, log `WARNING` (bukan error, run tetap lanjut) — sinyal kemungkinan typo di kolom CSV atau format salah (uploader yang memang tidak pernah berkomentar sendiri juga valid, warning ini cuma sinyal untuk dicek manual, bukan berarti pasti salah).

**FR-04 — Klasifikasi Sentimen Hybrid**
- Diberikan komentar dengan confidence model di atas `ambiguous_confidence_threshold` (config, wajib dikalibrasi - lihat `Architecture.md` ADR-02), ketika diklasifikasi, maka label diambil dari model tanpa memanggil LLM, dan field `sentiment_method` = `"model"`.
- Diberikan komentar dengan confidence model di bawah threshold itu, ketika diklasifikasi, maka komentar dikirim ke LLM dan `sentiment_method` = `"llm"`.
- Kasus gagal: ketika panggilan API LLM gagal (timeout/error), maka komentar tersebut ditandai `sentiment_label` = `"tidak_terklasifikasi"` (bukan membuat seluruh run gagal), dan dicatat di log beserta jumlah kegagalan di akhir run.

**FR-07 — Generate Laporan HTML**
- Diberikan `analysis_result.json` valid, ketika modul laporan dijalankan, maka menghasilkan satu berkas `.html` yang bisa dibuka di browser tanpa server, menampilkan minimal: ringkasan jumlah komentar dianalisis, distribusi sentimen (angka & persentase), top-20 keyword keseluruhan, top-10 keyword per label sentimen, dan metadata run (tanggal generate, sumber file, rentang tanggal komentar).
- Kasus gagal: ketika `analysis_result.json` tidak sesuai skema (field wajib hilang), maka program berhenti dengan pesan error yang jelas, bukan menghasilkan HTML kosong/rusak.

## 7. Alur Pengguna Utama

**Alur A — Analisis batch baru**
1. Analis menaruh file komentar mentah (format sesuai FR-01) di folder input.
2. Analis menjalankan Modul Analisis via CLI dengan path input & output yang diinginkan.
3. Sistem menjalankan ingest → exclude filter → preprocessing → klasifikasi hybrid → ekstraksi keyword → simpan `analysis_result.json`.
4. Analis mengecek log run (jumlah komentar masuk, dikecualikan, dianalisis, rasio eskalasi LLM).
5. **Gagal di mana:** kalau file input tidak valid, proses berhenti di langkah 3 dengan pesan error spesifik sebelum panggilan LLM apa pun terjadi (menghindari biaya sia-sia).

**Alur B — Hasilkan laporan dari hasil analisis yang sudah ada**
1. Analis menjalankan Modul Laporan dengan path `analysis_result.json` sebagai input.
2. Sistem membaca JSON, menyusun HTML, menyimpan ke path output.
3. Analis membuka file HTML di browser untuk direview.
4. **Gagal di mana:** kalau JSON tidak sesuai skema, laporan tidak dibuat sama sekali (tidak ada laporan setengah jadi) — pesan error menyebutkan bagian skema yang tidak cocok.

**Alur C — Cek kualitas exclude-list sebelum analisis final (opsional, FR-10)**
1. Analis menjalankan dry-run atau melihat laporan sebelumnya untuk daftar top pengirim komentar/reply.
2. Analis membandingkan dengan exclude-list yang sudah ada, menambah akun yang terlewat.
3. Analis menjalankan ulang Alur A dengan exclude-list yang sudah diperbarui.

## 8. Kebutuhan Non-Fungsional
| ID | Kategori | Kebutuhan | Cara verifikasi |
|---|---|---|---|
| NFR-01 | Skala data | Sanggup memproses ±10.000 komentar dalam satu run di laptop biasa (tanpa server khusus). Waktu proses ~15-16 menit (didominasi stemming Sastrawi) diterima sebagai batas wajar — tool dipakai ±1x/bulan, jadi tradeoff kompleksitas multiprocessing tidak sepadan. **Keputusan final, tidak akan dioptimasi lebih lanjut di v1.** | Uji dengan data 6.158 entri yang ada, catat waktu & memori |
| NFR-02 | Biaya | Panggilan LLM hanya untuk komentar yang lolos kriteria ambigu, jumlah panggilan dicatat di log setiap run | Cek log setelah run, bandingkan dengan total komentar |
| NFR-03 | Reproducibility | Bagian lexicon dari hasil harus identik antar run dengan input & config sama; bagian LLM boleh bervariasi sedikit (dicatat sebagai limitasi) | Jalankan 2x dengan input sama, bandingkan bagian lexicon |
| NFR-04 | Portabilitas laporan | File HTML bisa dibuka langsung dari filesystem tanpa server lokal, tetap terbaca meski tanpa koneksi internet (font boleh fallback ke system font) | Buka file secara offline |
| NFR-05 | Observability | Setiap tahap pipeline mencatat jumlah data masuk/keluar (mis. "6158 masuk → 4824 setelah exclude → 4824 setelah preprocessing") | Baca log setelah run |
| NFR-06 | Bahasa | Pipeline preprocessing & lexicon menargetkan Bahasa Indonesia (termasuk slang/informal khas TikTok), bukan multibahasa | Spot check komentar campuran bahasa daerah/asing di hasil |

## 9. Ketergantungan & Asumsi
- Ketergantungan: akses API LLM (lihat `Architecture.md` untuk provider) — butuh API key & koneksi internet saat run Modul Analisis (khusus untuk komentar yang dieskalasi).
- Ketergantungan: lexicon sentimen Bahasa Indonesia dan library stemming (lihat `Architecture.md`).
- > **ASUMSI:** Definisi "ambigu" untuk eskalasi ke LLM (threshold skor lexicon, atau rasio token out-of-vocabulary) belum dikalibrasi dengan data nyata. Nilai awal akan ditulis di `Architecture.md` sebagai default yang bisa diubah lewat config, tapi hasil klasifikasi awal perlu direview manual oleh analis sebelum dipercaya penuh.
- > **ASUMSI:** Reply yang berbentuk pertanyaan ke brand (bukan pernyataan sentimen) tetap ikut diklasifikasi seperti komentar biasa di v1 — kemungkinan besar jatuh ke "netral". Ini bukan bug, tapi keterbatasan cakupan v1.
- > **ASUMSI:** Exclude-list awal untuk data contoh berisi minimal `dokterrizkimrd`, `yayleindonesia`, `yaylesupport` berdasarkan temuan analisis data — perlu dikonfirmasi apakah tiga akun ini memang seluruhnya akun internal, dan apakah ada akun lain yang juga harus masuk daftar.

## 10. Risiko
| Risiko | Dampak | Kemungkinan | Mitigasi |
|---|---|---|---|
| Threshold eskalasi LLM terlalu longgar → biaya API membengkak | Biaya tak terduga | Sedang | FR-09 dry-run mode + logging jumlah eskalasi per run |
| Exclude-list tidak lengkap → data brand/admin mencemari hasil | Hasil sentimen & keyword bias | Sedang-Tinggi | FR-10 transparansi top pengirim komentar di laporan |
| Lexicon coverage rendah untuk slang TikTok baru | Banyak komentar salah dieskalasi/salah label | Sedang | Bagian dari alasan memilih hybrid; pantau rasio eskalasi sebagai sinyal |
| Reply berupa pertanyaan ikut dihitung sebagai sentimen | Distribusi sentimen sedikit menyimpang dari makna sebenarnya | Rendah-Sedang | Dicatat sebagai limitasi eksplisit di laporan (bagian metodologi) |

## 11. Rencana Rilis
- **Fase 1 — Modul Analisis inti:** FR-01 s.d. FR-06 (ingest, exclude, preprocessing, klasifikasi hybrid, ekstraksi keyword, serialisasi JSON).
- **Fase 2 — Modul Laporan:** FR-07, FR-08 (khusus generator laporan) — bisa dikerjakan paralel dengan Fase 1 selama kontrak skema JSON (`Schema.md`) sudah disepakati lebih dulu.
- **Fase 3 — Penyempurnaan:** FR-09 (dry-run biaya), FR-10 (transparansi exclude-list) — ditambahkan setelah Fase 1–2 berjalan dan hasil awal sudah divalidasi manual.

## Riwayat Perubahan
| Tanggal | Versi | Perubahan |
|---|---|---|
| 2026-08-30 | 0.4 | Tambah keputusan matching exact/case-sensitive di FR-02 (bukan casefold) dan deteksi typo (warning) di FR-11 kalau `video_author_username` tidak match komentar manapun — temuan sesi /plan-eng-review (Code Quality Issue 4, Failure Mode Issue 6) |
| 2026-08-30 | 0.3 | FR-11 direvisi (sesi /plan-eng-review): sumber `video_author_username` diubah dari rencana API call baru (dobel request, resiko block) jadi kolom CSV input baru (`nama_pengguna_kreator`) yang analis sudah punya di data mereka sendiri — zero request tambahan ke TikTok |
| 2026-08-30 | 0.2 | Tambah FR-11 (auto-exclude akun pengunggah video) berdasarkan diskusi sesi /office-hours — mempersempit non-goal "deteksi otomatis akun internal" jadi khusus heuristik pola perilaku, bukan kasus video-uploader yang zero-risk. Butuh field baru `video_author_username` dari scraper (dependency terpisah, lihat kriteria penerimaan FR-11) |
| 2026-08-30 | 0.1 | Draf awal berdasarkan diskusi alur preprocessing, keputusan hybrid sentiment, CLI, one-off report |
