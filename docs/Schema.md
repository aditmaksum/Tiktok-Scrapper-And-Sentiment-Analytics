# Schema — Sosmed Sentiment Pipeline

| | |
|---|---|
| **Versi** | 0.5 |
| **Tanggal** | 2026-08-30 |
| **Status** | Draf |
| **Sumber** | `PRD.md` v0.1, `Architecture.md` v0.1, contoh nyata `comments.json` |

Proyek ini tidak memakai database — semua data hidup di dua file JSON per run (input mentah dan hasil analisis). Dokumen ini mendefinisikan struktur keduanya secara eksplisit karena keduanya adalah **kontrak** antar komponen (khususnya antara Modul 1 dan Modul 2), meski tidak disimpan permanen di database.

## 1. Konvensi
- Semua field bertipe angka desimal (skor, confidence) memakai `float` standar JSON, presisi tidak perlu lebih dari 4 digit di belakang koma.
- Semua timestamp memakai format ISO 8601 (`YYYY-MM-DDTHH:MM:SS`), sesuai format yang sudah dipakai di `comments.json` sumber (zona waktu mengikuti data asal — tidak dikonversi, karena data sumber TikTok tidak eksplisit menyebut zona waktu).
- Penamaan field JSON memakai `snake_case`.
- `null` dipakai eksplisit untuk field yang secara valid tidak ada (mis. `parent_comment_id` untuk komentar top-level), bukan dihilangkan dari objek.

## 2. Skema Input — `comments.json` (kontrak eksternal, tidak dimiliki proyek ini)
Ini format yang **diterima**, bukan dirancang oleh proyek — didokumentasikan supaya adapter (`ingest.tiktok_adapter`) punya acuan pasti dan validasi input (FR-01) tahu persis apa yang harus dicek.

```
[
  {
    "aweme_id": string,              // ID video TikTok
    "caption": string,               // boleh kosong ("")
    "video_url": string,
    "video_author_username": string,  // BARU v0.3, OPSIONAL: username akun pengunggah video. Sumbernya kolom CSV input scraper (`nama_pengguna_kreator`, diisi analis dari data mereka sendiri), BUKAN dari panggilan API TikTok. String KOSONG ("") = baris CSV lama tanpa kolom ini, atau kolom dikosongkan (lihat PRD.md FR-11) — konsisten dgn konvensi field opsional lain di scraper ini (caption/video_url juga default "" bukan null), bukan error skema
    "total_collected": integer,      // CATATAN: ini total comments + replies, BUKAN cuma top-level
    "comments": [
      {
        "comment_id": string,
        "username": string,
        "nickname": string,
        "comment": string,           // teks komentar mentah
        "create_time": string,       // ISO 8601
        "avatar": string,            // URL, tidak dipakai analisis
        "digg_count": integer,       // jumlah like komentar
        "total_reply": integer,
        "replies": [
          {
            "comment_id": string,
            "username": string,
            "nickname": string,
            "comment": string,
            "create_time": string,
            "avatar": string,
            "digg_count": integer,
            ... (struktur sama dengan comment induk, tanpa "replies" bertingkat lagi)
          }
        ]
      }
    ]
  }
]
```

**Aturan validasi input (dijalankan FR-01 sebelum lanjut ke tahap berikutnya):**
- Root harus berupa array.
- Setiap elemen wajib punya `aweme_id` dan `comments` (boleh array kosong `[]`, tidak boleh hilang).
- Setiap `comment` di dalam `comments[]` wajib punya `comment_id`, `username`, `comment` (string, boleh kosong tapi field harus ada), `create_time`.
- `replies[]` boleh tidak ada atau kosong; kalau ada, tiap elemen wajib punya field yang sama seperti `comment`.
- Kalau salah satu aturan di atas gagal, ingest berhenti dan menyebutkan `aweme_id` / `comment_id` mana yang bermasalah (lihat Architecture §6, exit code 2).

## 3. Skema Data Internal — Komentar Setelah Flatten (dipakai antar-tahap Modul 1, tidak diekspos langsung)
```
{
  "comment_id": string,
  "video_id": string,              // dari aweme_id
  "video_caption": string,
  "is_reply": boolean,
  "parent_comment_id": string | null,   // null kalau is_reply = false
  "username": string,
  "text_raw": string,              // teks asli, belum diproses
  "create_time": string,           // ISO 8601
  "digg_count": integer,
  "excluded": boolean,             // true kalau username ada di exclude-list (FR-02) ATAU sama dgn video_author_username (FR-11)
  "exclude_reason": string | null  // "internal_account" (exclude-list manual) | "video_uploader" (FR-11, auto) | null kalau excluded = false
}
```

Field `text_clean`, `tokens_stemmed`, `emoji_found`, `sentiment_*` ditambahkan secara progresif oleh tahap-tahap berikutnya (preprocessing, sentiment) — bentuk akhirnya sama dengan objek `comments[]` di §4 di bawah.

## 4. Skema Output — `analysis_result.json` (kontrak resmi Modul 1 → Modul 2, INI YANG PALING PENTING DIJAGA STABIL)

```
{
  "meta": {
    "run_id": string,                        // mis. "run-20260830-143210"
    "generated_at": string,                  // ISO 8601, waktu run dieksekusi
    "source_file": string,                   // nama file input
    "date_range": { "from": string, "to": string },  // rentang create_time komentar yang dianalisis
    "total_videos": integer,
    "total_comments_raw": integer,           // termasuk reply, sebelum exclude
    "total_comments_excluded_internal": integer,
    "total_comments_analyzed": integer,      // raw - excluded - gagal ingest (kalau ada)
    "sentiment_method_breakdown": { "model": integer, "model_failed": integer, "llm": integer, "llm_failed": integer, "lexicon": integer },
    "config_used": {
      "model_version": string,               // REVISI 0.5, gantiin lexicon_version - "nama_model@revisi_pendek"
      "llm_base_url": string,                // endpoint router yg dipakai (NFR-03: telusuri run pakai config apa), bukan API key
      "llm_model": string,
      "ambiguous_confidence_threshold": float | null, // REVISI 0.5, gantiin ambiguous_threshold_score + ambiguous_threshold_oov_ratio (model cuma punya satu sinyal confidence, bukan skor+OOV). null kalau LLM_MODEL/LLM_API_KEY gak diisi (mode model-only) - gak ada threshold eskalasi yang dipakai karena gak ada eskalasi
      "exclude_config_file": string
    }
  },
  "sentiment_summary": {
    "positif": integer, "negatif": integer, "netral": integer, "tidak_terklasifikasi": integer,
    "positif_pct": float, "negatif_pct": float, "netral_pct": float
  },
  "top_keywords_overall": [
    { "keyword": string, "score": float, "count": integer }
  ],
  "top_keywords_by_sentiment": {
    "positif": [ { "keyword": string, "score": float, "count": integer } ],
    "negatif": [ { "keyword": string, "score": float, "count": integer } ],
    "netral": [ { "keyword": string, "score": float, "count": integer } ]
  },
  "per_video": [
    {
      "video_id": string,
      "caption": string,
      "total_comments_analyzed": integer,
      "sentiment_summary": { "positif": integer, "negatif": integer, "netral": integer },
      "top_keywords": [ { "keyword": string, "count": integer } ]
    }
  ],
  "comments": [
    {
      "comment_id": string,
      "video_id": string,
      "is_reply": boolean,
      "parent_comment_id": string | null,
      "username": string,
      "text_raw": string,
      "text_clean": string,
      "tokens_stemmed": [string],
      "emoji_found": [string],
      "sentiment_label": "positif" | "negatif" | "netral" | "tidak_terklasifikasi",
      "sentiment_confidence": float,
      "sentiment_method": "model" | "model_failed" | "llm" | "llm_failed",
      "create_time": string,
      "digg_count": integer
    }
  ],
  "excluded_accounts_detected": [
    { "username": string, "total_muncul": integer, "alasan": string }
  ]
}
```

**Catatan desain field penting:**
- `comments[]` menyimpan **seluruh** komentar yang dianalisis (bukan sample), supaya Modul 2 bisa menampilkan "contoh komentar representatif" per label tanpa perlu akses balik ke Modul 1 atau file input asli. Untuk data besar (>10.000 komentar), ini perlu dipantau ukurannya (lihat §8 Performa).
- `excluded_accounts_detected` **bukan** daftar exclude-list yang dipakai (itu ada di `meta.config_used`), tapi daftar akun-akun teratas berdasarkan frekuensi kemunculan di data mentah — dipakai FR-10 untuk membantu analis mengecek exclude-list-nya sudah cukup lengkap atau belum.

## 5. Enum & Nilai Tetap
| Enum | Nilai | Dipakai di |
|---|---|---|
| sentiment_label | `positif`, `negatif`, `netral`, `tidak_terklasifikasi` | `comments[].sentiment_label`, `sentiment_summary` |
| sentiment_method | `model`, `model_failed`, `llm`, `llm_failed` (`lexicon` masih ada di enum untuk kompatibilitas run lama, tidak diproduksi lagi sejak revisi 0.5) | `comments[].sentiment_method`, `meta.sentiment_method_breakdown` |
| exclude_reason | `internal_account` (manual, FR-02), `video_uploader` (auto, FR-11) | field internal komentar setelah flatten (§3), `excluded_accounts_detected[].alasan`. **Presedensi kalau match keduanya:** cek `video_uploader` (FR-11) dulu — sinyalnya lebih pasti (identitas video, bukan daftar manual) |

Tidak ada transisi status (data ini hasil klasifikasi satu kali per run, bukan entitas yang berubah status seiring waktu).

## 6. Data Awal (Seed)
Tidak ada seed data aplikasi. Yang perlu disiapkan sebelum run pertama:
- File lexicon sentimen Indonesia (lihat `Architecture.md` §2).
- `config/exclude_accounts.yaml` — minimal berisi kandidat awal `dokterrizkimrd`, `yayleindonesia`, `yaylesupport` (lihat catatan di `PRD.md` §9), untuk dikonfirmasi/diperluas oleh analis.
- `config/stopwords_custom.txt` — daftar stopword Bahasa Indonesia, sengaja **tidak** memasukkan kata negasi (`tidak`, `bukan`, `belum`, `jangan`) karena kata-kata ini krusial untuk akurasi sentimen.

## 7. Strategi "Migrasi"
Tidak relevan dalam arti migrasi database, tapi berlaku prinsip yang sama untuk **perubahan skema JSON**: kalau `analysis_result.json` (§4) berubah strukturnya di versi mendatang, field baru ditambahkan sebagai opsional dulu (Modul 2 harus tetap bisa baca file versi lama tanpa field baru itu), field lama tidak dihapus langsung — ditandai deprecated di Riwayat Perubahan dokumen ini sebelum benar-benar dibuang di versi berikutnya.

## 8. Retensi & Privasi
- Data yang diproses berisi data pribadi terbatas: `username`, `nickname`, teks komentar publik, dan URL avatar publik dari TikTok — semuanya sudah publik di platform asal, bukan data pribadi yang dikumpulkan sistem ini secara tersendiri.
- File `analysis_result.json` dan `comments.json` disimpan di filesystem lokal analis, tidak diunggah ke layanan pihak ketiga mana pun kecuali teks komentar yang dieskalasi ke LLM API (via router pihak ketiga, lihat Premise 3 di design doc) untuk klasifikasi (lihat `Architecture.md` §9). **Catatan privasi (revisi 0.2):** karena providernya sekarang router pihak ketiga yang belum ditentukan (bukan Anthropic langsung), kebijakan retensi/logging data komentar di sisi router itu TIDAK diketahui/diverifikasi di dokumen ini — analis perlu cek kebijakan privasi router yang dipilih sebelum run pertama, terutama kalau ada komentar yang mengandung info sensitif pelanggan (mis. nama anak, usia, kondisi kesehatan disebutkan dalam komentar).
- Tidak ada mekanisme penghapusan otomatis — retensi file mengikuti kebijakan penyimpanan lokal analis sendiri (di luar cakupan sistem ini).
- > **ASUMSI:** Tidak ada kewajiban regulasi khusus (mis. GDPR-like) yang berlaku untuk data ini. Konfirmasi kalau brand/perusahaan terkait punya kebijakan privasi data pelanggan yang lebih ketat dari asumsi ini.

## 9. Catatan Performa
- `comments[]` di `analysis_result.json` adalah bagian yang tumbuh linear dengan jumlah komentar — untuk data 6.158 entri, perkiraan ukuran file dalam kisaran puluhan MB (tergantung panjang `tokens_stemmed` dan teks). Untuk skala ±10.000 komentar (NFR-01) ini masih wajar dibuka/diproses di memori laptop biasa; kalau ke depan volumenya naik signifikan (>100.000), pertimbangkan memecah `comments[]` jadi file terpisah dari agregat (`meta`, `sentiment_summary`, `top_keywords_*`) — ditandai sebagai keputusan yang perlu ditinjau ulang, bukan dikerjakan sekarang.
- Tidak ada indeks (bukan database) — `per_video[]` dan `comments[]` cukup diakses linear karena ukurannya sudah dibatasi ke satu run.

## Riwayat Perubahan
| Tanggal | Versi | Perubahan |
|---|---|---|
| 2026-08-30 | 0.5 | Lapis pertama klasifikasi hybrid ganti dari lexicon jadi model lokal (Approach C, `docs/designs/sentiment-model-cascade.md`) — `sentiment_method` enum `lexicon`→`model`/`model_failed` (breaking, tidak backward-compatible penuh: field lama tidak dihapus dari enum tapi tidak diproduksi lagi), `meta.config_used.lexicon_version`→`model_version`, `ambiguous_threshold_score`+`ambiguous_threshold_oov_ratio`→`ambiguous_confidence_threshold` tunggal. Sengaja melanggar §7 "field lama tidak dihapus langsung" untuk `config_used` karena bentuk sinyalnya (skor+OOV vs confidence tunggal) tidak punya pemetaan 1:1 yang jujur |
| 2026-08-30 | 0.4 | Klarifikasi sumber `video_author_username`: kolom CSV input scraper (`nama_pengguna_kreator`), bukan panggilan API TikTok baru — mengikuti Architecture.md 0.4. Struktur field tidak berubah dari 0.3 |
| 2026-08-30 | 0.3 | Tambah `video_author_username` (opsional, nullable) ke skema input `comments.json`, dan `exclude_reason` enum value `video_uploader` — mengikuti Architecture.md 0.3 (ADR-03 revisi, FR-11). Field opsional & nullable karena scraper belum mengisi field ini per tanggal revisi — field lama tidak dihapus, sesuai §7 Strategi "Migrasi" |
| 2026-08-30 | 0.2 | Tambah `meta.config_used.llm_base_url` (opsional, field baru) mengikuti perubahan Architecture.md 0.2 (LLM provider-agnostic via router) — field lama tidak dihapus, sesuai §7 Strategi "Migrasi" |
| 2026-08-30 | 0.1 | Draf awal — skema input (eksternal) dan skema output `analysis_result.json` (kontrak internal) |
