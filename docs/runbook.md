# Runbook — Command Manual Sosmed Sentiment Pipeline

Kumpulan command buat jalanin pipeline sentimen sendiri, tanpa CC. Semua
command dijalankan dari root repo (`tiktok-comment-scrapper/`), venv sudah aktif.

## 0. Sekali di awal (setup)

```sh
# aktifin venv (Windows)
venv\Scripts\activate

# install semua dependency (termasuk torch/transformers, ~600MB)
pip install -r requirements.txt

# copy template env, isi LLM_API_KEY/LLM_BASE_URL/LLM_MODEL kalau mau LLM eskalasi
copy .env.example .env
notepad .env
```

**Isi `.env` yang bener:**
```
LLM_API_KEY=isi-key-kamu
LLM_BASE_URL=http://localhost:PORT/v1
LLM_MODEL=nama-model
```
`LLM_BASE_URL` cuma sampai `/v1` — JANGAN tambahin `/chat/completions` di
belakang, itu ditambahin sendiri sama SDK-nya (kalau ditambahin manual, path-nya
dobel dan gagal connect).

Tanpa `.env` diisi, pipeline tetap jalan pakai model lokal doang (gak ada
eskalasi LLM) — bukan error, cuma warning di log.

## 1. Scraping (kalau belum ada `comments.json` bulan ini)

```sh
python batch.py --input=mirror_orderan_aff_tiktok.csv --sample=150
```

Lihat `README.md` bagian "Monthly batch" buat detail flag.

## 2. Analisis sentimen

```sh
# cara singkat (pakai runs/<bulan>/comments.json otomatis)
python -m sosmed_sentiment.cli.analyze --month 2026-08 --threshold-config config/thresholds.yaml

# cara eksplisit (kalau path-nya beda dari konvensi runs/<bulan>/)
python -m sosmed_sentiment.cli.analyze --input runs/2026-08/comments.json --output runs/2026-08/analysis_result.json --threshold-config config/thresholds.yaml
```

`--threshold-config config/thresholds.yaml` **wajib** kalau `.env` LLM diisi
(dipakai buat mutusin komentar mana yang confidence-nya kerendahan dan perlu
dieskalasi ke LLM). Kalau `.env` LLM kosong, flag ini boleh dihilangkan.

**Kalau run keputus di tengah jalan** (komputer mati, terminal ketutup, dst):
jalanin command yang SAMA lagi, otomatis lanjut dari komentar terakhir yang
kelar (checkpoint `.analyze-partial.jsonl`), gak mulai dari nol. Pakai
`--fresh` kalau justru mau paksa ulang semua dari awal:

```sh
python -m sosmed_sentiment.cli.analyze --month 2026-08 --threshold-config config/thresholds.yaml --fresh
```

**Estimasi waktu** (6.000-an komentar): mode model-only ~25 menit
(preprocessing/stemming ~15 menit + model ~9 menit). Mode hybrid (LLM
nyala) bisa lebih lama tergantung berapa banyak yang dieskalasi (~48% di
kalibrasi terakhir) dan kecepatan router LLM-nya.

## 3. Bikin laporan HTML

```sh
python -m sosmed_sentiment.cli.generate_report --input runs/2026-08/analysis_result.json --output runs/2026-08/report.html
```

Buka `runs/2026-08/report.html` langsung di browser (dobel klik, gak perlu server).

### 3a. Narasi LLM + spot-check manusia (`--narrative-review`)

Kalau `.env` LLM diisi (`LLM_API_KEY`/`LLM_MODEL`/`LLM_BASE_URL`, sama kayak
punya `analyze`), `generate_report` juga minta LLM nulis narasi headline/
risk/actions laporan - divalidasi guardrail sitasi (tiap angka yang disebut
LLM harus cocok ke angka yang bener-bener ada di metrics laporan itu
sendiri) sebelum boleh masuk laporan. Kalau ditolak guardrail 2x, atau LLM
gak dikonfigurasi, laporan otomatis balik ke narasi deterministik (yang
lama, non-LLM) - bagian narasi TIDAK PERNAH kosong.

**Cara spot-check:**

```sh
python -m sosmed_sentiment.cli.generate_report \
  --input runs/2026-08/analysis_result.json \
  --output runs/2026-08/report.html \
  --narrative-review
```

Ini nyetak semua kalimat narasi (headline/risk/actions) ke terminal SETELAH
`report.html` ditulis, plus angka metrics pembanding di sebelahnya - cocokin
tiap angka yang disebut ke tabel yang sudah ada di laporan yang sama. Baris
pertama outputnya selalu banner sumber narasi: `llm-accepted` (LLM lolos
guardrail), `llm-retried-then-fallback` (LLM ditolak 2x, dipakai narasi
deterministik), `no-llm-configured` (`.env` LLM kosong), atau
`narrative-disabled` (dipanggil bareng `--no-narrative`).

**Kapan pakai `--narrative-review`:** pakai di **SETIAP run selama 2 minggu
pertama** sistem narasi LLM ini jalan (masa membangun kepercayaan) - setelah
itu boleh dikurangi jadi **sampling ~1 dari 5 run**, asal belum ada tanda
guardrail sering nolak/salah. Bukan gate blocking - laporan tetap
ter-generate dan tersimpan walau operator gak sempat spot-check, ini cuma
sinyal kualitas tambahan.

**Flag lain terkait narasi:**

| Flag | Fungsi |
|---|---|
| `--no-narrative` | Skip panggilan LLM narasi sama sekali (laporan pakai narasi deterministik), independen dari eskalasi LLM sentimen di `analyze` - dua keputusan on/off yang beda, walau sama-sama pakai `.env` LLM |
| `--fresh-narrative` | Buang cache `narrative.json`, paksa generate ulang dari LLM (sama pola penamaan dengan `--fresh` di `analyze`) |

Dua file sidecar ikut tersimpan di sebelah `report.html`: `narrative.json`
(cache narasi LLM terakhir yang lolos guardrail, dipakai lagi otomatis kalau
metrics-nya sama) dan `narrative_review.json` (jejak audit: kapan generate,
sumbernya LLM apa fallback, dan kapan/siapa yang terakhir spot-check lewat
`--narrative-review`).

## 4. Kalibrasi ulang threshold (jarang, cuma kalau mau)

Cuma perlu kalau ganti model, atau mau kalibrasi ulang pakai data lebih baru.

```sh
# 1. generate 200 sampel komentar acak buat dilabel manual
python scripts/generate_labeling_sample.py
# -> nulis ke local/labeling_sample.xlsx, buka di Excel, isi kolom sentiment_label

# 2. simpan hasil isian sebagai local/labeling_sample_labeled.xlsx (nama file
#    HARUS persis ini), lalu:
python scripts/calibrate_threshold.py
# -> ngukur akurasi model terhadap label kamu, nulis config/thresholds.yaml
#    dan config/calibration/tahap-b-labels.csv (yang kedua ini boleh di-commit,
#    yang pertama JANGAN pernah di-commit local/ - isinya teks pelanggan asli)
```

## 5. Coba cepat tanpa data asli

```sh
python -m sosmed_sentiment.cli.analyze --input docs/examples/comments.sample.json --output /tmp/test-result.json
python -m sosmed_sentiment.cli.generate_report --input /tmp/test-result.json --output /tmp/test-report.html
```

## Ringkasan flag `analyze`

| Flag | Wajib? | Fungsi |
|---|---|---|
| `--month YYYY-MM` | Salah satu dari ini atau `--input`+`--output` | Shorthand `runs/<bulan>/comments.json` → `runs/<bulan>/analysis_result.json` |
| `--input` | (lihat atas) | Path `comments.json` |
| `--output` | (lihat atas) | Path tujuan `analysis_result.json` |
| `--threshold-config` | Wajib kalau `.env` LLM diisi | Path `config/thresholds.yaml` |
| `--fresh` | Opsional | Buang checkpoint, ulang semua dari awal |
| `--exclude-config` | Opsional | Path `config/exclude_accounts.yaml` |
| `--stopwords-config` | Opsional | Path stopword custom |

## Exit code

| Kode | Arti |
|---|---|
| `0` | Sukses penuh |
| `2` | Gagal sebelum proses mulai (input gak valid, model gagal dimuat, threshold config gak ada/rusak) — aman di-rerun |
| `3` | Selesai TAPI >10% eskalasi LLM gagal — file JSON tetap tersimpan, tapi cek koneksi LLM/router |
