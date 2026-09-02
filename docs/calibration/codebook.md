# Codebook Pelabelan Sentimen — Tahap B

Dipakai buat melabeli sampel komentar TikTok secara manual (`sosmed_sentiment`
pipeline, kalibrasi threshold eskalasi & pengukuran akurasi gate G-08). Tujuan
dokumen ini: kalau kalibrasi ulang dikerjakan orang lain atau di sesi lain,
labelnya tetap konsisten dengan yang sudah ada di
`config/calibration/tahap-b-labels.csv`.

## Definisi Label

### `positif`
Komentar menunjukkan kepuasan, pujian, testimoni baik, atau niat beli/lanjut
pakai. Termasuk testimoni singkat berupa emoji jelas (`🥰`, `🔥`, `😍`).

Contoh dari sampel: *"Testimoni anak jadi banyak kosa kata, pakai emoji
hati"*, *"fix si mau beli deh kak"*.

### `negatif`
Komentar menunjukkan keluhan, kekecewaan, tuduhan (mis. produk palsu), atau
efek samping negatif yang jelas dikeluhkan (bukan cuma disebutkan netral).

Contoh: keluhan rasa/bau, laporan produk tidak sesuai janji, kekecewaan
eksplisit.

### `netral`
**Default kalau ragu antara netral dan salah satu kutub, KECUALI ada sinyal
jelas** — bukan keranjang sampah buat "gak yakin". Termasuk di sini:
- Pertanyaan murni tanpa opini terlampir (*"berapa sendok bun ngasinya"*,
  *"15 tahun apa masih bisa"*, *"anak usia 2thn brp kali minumnya"*).
- Informasi faktual tanpa opini (*"info dosis dari dokter, gak ada opini"*).
- Komentar yang cuma menyebut angka/fakta tanpa nada jelas.
- Ambigu tapi condong ke arah "tidak jelas suka atau komplain" (dicatat di
  `notes`, bukan ditebak).

### `tidak_yakin` (opsi ke-4, ditambahkan setelah kalibrasi model pertama)
Dipakai HANYA kalau setelah membaca komentar, kamu benar-benar tidak bisa
memutuskan salah satu dari 3 label di atas — bukan pintasan buat komentar yang
sebenarnya `netral` (banyak pertanyaan murni SALAH kalau dilabel
`tidak_yakin`, itu `netral`). Contoh valid: sarkasme yang bisa dibaca dua arah,
komentar terpotong/tidak lengkap, campuran bahasa yang bikin makna kabur.

**Kenapa dipisah dari `netral`:** kalau `tidak_yakin` dicampur ke `netral`,
akurasi model yang diukur terhadap `netral` jadi bias — model yang salah nebak
komentar yang MEMANG ambigu (bukan salah model) dihukum sama kayak yang jelas
netral. Memisahkan keduanya bikin evaluasi akurasi lebih jujur ke performa
model yang sebenarnya.

## Menangani Disagreement Antar-Annotator

Kalau kalibrasi ulang dikerjakan lebih dari satu orang (label sampel yang sama
dua kali, atau bagi sampel jadi beberapa annotator):

1. **Overlap minimal 20 komentar** dilabel oleh kedua annotator secara
   independen (tanpa lihat label satu sama lain dulu) — buat ukur kesepakatan.
2. **Kalau beda label:** diskusikan berdua, bukan salah satu otomatis menang.
   Kalau tetap gak sepakat setelah diskusi, pakai `tidak_yakin` untuk baris
   itu — itu sinyal valid bahwa komentarnya memang ambigu, bukan kegagalan
   proses.
3. **Catat di `notes`** kenapa keputusan akhir diambil, terutama buat kasus
   yang sempat berbeda pendapat — supaya annotator berikutnya (atau diri
   sendiri 6 bulan lagi) paham alasannya, bukan cuma hasil akhirnya.
4. Kesepakatan yang rendah secara sistematis pada satu kategori (mis. selalu
   beda pendapat soal `netral` vs `tidak_yakin`) adalah sinyal kalau
   definisi di codebook ini masih belum cukup tajam — revisi bagian itu,
   dicatat di bawah.

## Riwayat Revisi

| Tanggal | Perubahan |
|---|---|
| 2026-08-30 | Draf awal, ditulis setelah 200 komentar pertama sudah dilabel dengan 3 kategori (positif/negatif/netral) — opsi `tidak_yakin` ditambahkan belakangan, jadi sampel yang sudah ada belum memakainya secara retroaktif. |
