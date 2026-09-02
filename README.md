[![Twitter: romy](https://img.shields.io/twitter/follow/RomySihananda)](https://twitter.com/RomySihananda)

# tiktok-comment-scrapper

![](https://raw.githubusercontent.com/RomySaputraSihananda/RomySaputraSihananda/main/images/GA-U-u2bsAApmn9.jpeg)
Get all comments from tiktok video url or id.

This fork adds a monthly batch runner on top of the original single-video CLI:
feed it a CSV of videos, get one dataset for the month, resume where it stopped
if the run breaks. Design notes live in
[docs/designs/monthly-tiktok-comment-scraper.md](docs/designs/monthly-tiktok-comment-scraper.md).

## Requirements

- **Python >= 3.11.4**
- **Requests >= 2.31.0**

## Installation

```sh
# Cloning Repository
git clone https://github.com/romysaputrasihananda/tiktok-comment-scrapper

# Change Directory
cd tiktok-comment-scrapper

# Create Virtual Environment (Optional)
python -m venv venv
source venv/bin/activate  # On Windows use `venv\Scripts\activate`

# Install Requirement
pip install -r requirements.txt
```

## Picking the month's videos

The order mirror holds one row per order, not per video, so the same video
repeats hundreds of times and affiliate accounts dominate. `sample.py` turns
that file into a month's worth of videos worth scraping.

```sh
# see the split and what it will cost, write nothing
python sample.py --input=mirror_orderan_aff_tiktok.csv --size=150 --dry-run

# write it, then scrape it
python sample.py --input=mirror_orderan_aff_tiktok.csv --size=150
python batch.py --input=runs/2026-08/sample.csv
```

Videos are grouped into four tiers by the `account_type` column, matched as a
casefolded substring so `kol account` and `KOL` both land in the same place:
`kol`, `official`, `affiliate`, and `unknown` for anything else, including
blank cells.

`--quota` splits the sample between the first three, `50,30,20` by default.
Affiliate holds a floor rather than taking whatever is left over. Without it, a
month where KOL and official fill the quota gives affiliate zero rows, and next
month's affiliate number has nothing to compare against.

A tier that cannot fill its share passes the spare slots down the list, so
affiliate can end up above 20% when there are not enough KOL videos to go
round. The manifest records what actually happened.

### Flags

| Flag        | Default | Description                                              |
| :---------- | :-----: | :------------------------------------------------------- |
| `--input`   |    —    | Order mirror CSV (required)                              |
| `--output`  | `runs/YYYY-MM/sample.csv` | Where to write the sample            |
| `--size`    |  `150`  | How many videos to sample                                |
| `--quota`   | `50,30,20` | Percent split KOL,OFFICIAL,AFFILIATE, must total 100   |
| `--seed`    | random  | Reuse a seed to reproduce an earlier sample              |
| `--exclude` |   none  | Glob of earlier results to skip, e.g. `runs/*/comments.json` |
| `--dry-run` |   off   | Print the split and the duration estimate, write nothing |

### The manifest

Every run writes `<output>.manifest.json` next to the CSV: the seed, how many
videos each tier had, how many it contributed, how many duplicate rows were
dropped, and the estimated batch duration. Three months later, "why was this
video in September's sample" is answered by reading that file and rerunning
with the same `--seed`.

### Not sampling the same videos twice

```sh
python sample.py --input=mirror.csv --size=150 --exclude='runs/*/comments.json'
```

The exclusion is by what was actually **scraped**, not by what was sampled. A
video picked last month whose scrape failed has no data yet and deserves
another turn.

### Where the sample stops being random

If a tier holds fewer videos than its share, the sampler takes all of them, and
that tier is a census rather than a sample. `--dry-run` shows this: when
`sampled` equals `available` for a tier, every video in it is going into the
batch. Lower `--size` if you want the split to hold exactly, or use `--exclude`
so the next month reaches different videos.

## Monthly batch (the main workflow)

Put the month's videos in a CSV, then run one command.

```csv
url_or_id,account_type
7418294751977327878,affiliate
https://www.tiktok.com/@kol/video/7451234567890123456,kol
7461234567890123456,
```

The order-mirror export works as-is, no renaming needed:

```csv
id_konten,account_type
7532149368489594117,affiliate account
7512845318480776455,kol account
```

The video column may be called `url_or_id` or `id_konten`, whichever your export
produces; one of them is required. It accepts a bare id, a full video URL, or a
`vt.tiktok.com` short link. A row with an empty or unreadable `url_or_id` is
skipped and reported at the end of the run; it never aborts the batch.
Duplicate video ids are skipped.

`account_type` labels what kind of account posted the video - `affiliate`,
`kol`, or whatever else you use. It is free text and optional: leave it blank
and the row still gets scraped, labelled `unknown`. Losing a video to a missed
cell would cost more than an untidy label.

```sh
python batch.py --input=videos.csv
```

### Feeding it the order mirror directly

The batch takes the mirror itself, and picks the videos with the same tier
quota `sample.py` uses:

```sh
python batch.py --input=mirror_orderan_aff_tiktok.csv --sample=100
```

The chosen videos and their manifest are written to `runs/YYYY-MM/sample.csv`
and `sample.manifest.json` before a single request goes out, so a run can be
inspected while it is still going and reproduced later from its seed.

Without `--sample`, an input holding more than 500 videos is refused:

```
mirror_orderan_aff_tiktok.csv holds 5049 videos, which is about 172h 30m of
scraping. Pass --sample N to scrape a quota-balanced sample of them, or --all
if you really mean to scrape every one.
```

That guard exists because pointing the batch at the whole mirror starts a
three-day run and nothing on the command line says so. `--all` is the way to
say you meant it.

`sample.py` is still there for the times you want to see the split, or write a
list to hand around, before committing the hours: it has `--dry-run` and
`--exclude`, which the batch flags do not.

Output lands in `runs/YYYY-MM/` as one pair of files for the whole month:

```
runs/2026-08/comments.json   # nested, comments with their replies
runs/2026-08/comments.csv    # flat, one row per comment and per reply
runs/2026-08/.partial.jsonl  # checkpoint, see below
```

`account_type` is a column in both, so filtering or grouping stays your call.

Rerunning the same month overwrites its files rather than appending, so a
re-run never doubles the data.

### Flags

| Flag              | Default | Description                                             |
| :---------------- | :-----: | :------------------------------------------------------ |
| `--input`         |    —    | Input CSV (required)                                     |
| `--output`        | `runs`  | Root directory for run output                            |
| `--month`         | current | Run label / output folder, `YYYY-MM` (a plain name, not a path or drive) |
| `--max-comments`  |  `200`  | Cap per video, replies included                          |
| `--max-replies`   |    `5`  | Cap on replies fetched per comment                       |
| `--keep-empty`    |  off    | Keep comments whose text is blank (dropped by default)   |
| `--video-delay`   |  `7,10` | Random seconds between videos, `MIN,MAX`                 |
| `--request-delay` |   `1,3` | Random seconds between requests inside one video         |
| `--sample`        |   off   | Scrape a quota-balanced sample of N videos instead of all |
| `--quota`         | `50,30,20` | Percent split KOL,OFFICIAL,AFFILIATE for `--sample`    |
| `--seed`          | random  | Reuse a seed to reproduce an earlier `--sample`          |
| `--all`           |  off    | Scrape every video even when the input is large          |
| `--fresh`         |  off    | Ignore the checkpoint and scrape every row again         |

### Resuming a broken run

Each video's result is appended to `runs/YYYY-MM/.partial.jsonl` the moment it
finishes. Rerun the exact same command and the batch picks up where it stopped
instead of starting over. This matters: at the default delays a 1000-video
batch runs for hours, so it will sometimes be interrupted.

Use `--fresh` to discard the checkpoint and rescrape everything.

### What gets collected

Each video contributes at most `--max-comments` rows, replies included, with at
most `--max-replies` replies per comment. The cap can overshoot by a few rows: a
comment is never separated from its replies to hit the number exactly.

Comments whose text is blank are dropped and do not spend a slot of the cap.
These are not sticker or photo comments - probed against the live API, they come
back with an empty text, no `image_list`, status 1 and not hidden. There is
nothing in them to read or to score. Pass `--keep-empty` to collect them anyway.

Emoji-only comments are kept: an emoji is text and carries sentiment.

Paging stops after 40 pages per video, and after 5 pages of replies per
comment, whatever the caps say. Blank comments do not spend a slot of
`--max-comments`, so on a video whose pages are mostly blank the cap alone
would never stop the paging; these limits bound what one video can spend.

`create_time` is written in the local time of the machine that ran the scrape,
not UTC. Run the monthly batch from the same machine, or the same timezone,
or the timestamps of two runs cannot be compared directly.

Replies are worth watching. On a busy video they can crowd out the top-level
comments, which is usually where opinions about the product live. In one real
run a video with 1549 comments yielded only 37 top-level ones under a reply cap
of 10. Lower `--max-replies` to shift the balance back.

### Smoke test

Before the batch starts, small requests run against up to the first 5 videos in
the CSV, stopping at the first one that has comments. A video with comments
turned off is normal, so one quiet video does not block a run; only every probe
coming back empty does. If TikTok has stopped answering, the run stops
immediately with a one-line message instead of failing silently hours in. Exit
code is `2` for that case.

The smoke test deliberately does not check the caption. TikTok returns the
`share_info` block inconsistently - measured at 10 of 16 identical requests -
so a missing caption says nothing about whether the endpoint still works.

### Exit codes

| Code | Meaning                                                        |
| :--: | :------------------------------------------------------------- |
|  `0` | All videos scraped                                              |
|  `1` | Finished, but some rows were skipped or some videos failed      |
|  `2` | Stopped early: smoke test failed, or TikTok blocked the run     |

On code `2` the checkpoint is kept, so rerunning the same command continues.

## Single video

The original CLI still works, with the caps and URL support added.

```sh
python main.py --aweme_id=7170139292767882522 --size=200 --output=data
```

### Flags

| Flag           | Alias | Default |            Description             |
| :------------- | :---: | :-----: | :--------------------------------- |
| `--aweme_id`   |       |    —    | Video id or URL (required)          |
| `--size`       |  `-s` |  `200`  | Cap on comments, replies included   |
| `--max-replies`|       |    `5`  | Cap on replies per comment          |
| `--keep-empty` |       |  off    | Keep blank-text comments            |
| `--output`     |  `-o` |  `data` | Output directory                    |

## Sample Output

```json
{
  "aweme_id": "7170139292767882522",
  "caption": "makk aku jadi animee",
  "account_type": "affiliate",
  "video_url": "https://t.tiktok.com/i18n/share/video/7170139292767882522/",
  "total_collected": 4,
  "comments": [
    {
      "comment_id": "7310977412674093829",
      "username": "user760722966",
      "nickname": "rehan",
      "comment": "bagus",
      "create_time": "2023-12-10T18:55:47",
      "avatar": "https://p16-sign-useast2a.tiktokcdn.com/...",
      "digg_count": 12,
      "total_reply": 3,
      "replies": [
        {
          "comment_id": "7310977412674093830",
          "username": "ryo.syntax",
          "nickname": "Bukan Rio",
          "comment": "good game",
          "create_time": "2023-12-10T18:56:19",
          "avatar": "https://p16-sign-useast2a.tiktokcdn.com/...",
          "digg_count": 0,
          "total_reply": 0,
          "replies": []
        }
      ]
    }
  ],
  "has_more": 0
}
```

`caption` may come back empty; see the smoke test note above. `video_url`
always has a value, falling back to one built from the id.

The CSV carries the same data flattened, with `is_reply` and
`parent_comment_id` so replies can be joined back to their comment:

```csv
account_type,aweme_id,caption,video_url,comment_id,parent_comment_id,is_reply,username,nickname,comment,create_time,digg_count,total_reply
```

## Notes on rate limiting

The scraper waits a random 7-10 seconds between videos and 1-3 seconds between
requests inside a video. The gaps are randomised rather than fixed so the
request train does not form a uniform interval.

There is no proxy support and none is planned: the point of this tool is to
cost nothing to run. If TikTok rate-limits the machine, the run stops with exit
code `2` and the checkpoint intact. Wait a few hours and rerun the same command.

## Sentiment analysis (`sosmed_sentiment/`)

Two more CLIs on top of the same scraped data: `analyze` classifies each
comment's sentiment and pulls top keywords, `generate_report` turns that into
one offline HTML file.

### Install

Same `requirements.txt`, same venv - `pip install -r requirements.txt` also
installs `torch` and `transformers` for this part. That adds **~600MB** to the
venv (torch ~120MB CPU-only + the sentiment model's ~500MB weights, downloaded
once on first run - see below), a deliberate departure from this repo's
"stay light" convention. See `docs/Architecture.md` ADR-02 for why.

### First run downloads the model

The first `analyze` run on a machine logs a line like:

```
memuat model sentimen lokal (mdhugol/indonesia-bert-sentiment-classification)...
unduhan pertama kali ~500MB, sekali per mesin, butuh internet - proses
berikutnya pakai cache lokal.
```

That download takes a few minutes depending on your connection and needs
internet access (blocked by some office proxies/firewalls - `huggingface.co`
needs to be reachable). Every run after the first loads from the local
HuggingFace cache in a couple of seconds. If the load fails, `analyze` exits
with code `2` and an actionable message - no comment is processed yet at that
point, so rerunning once the connection issue is fixed picks up cleanly.

### Running it

```sh
# .env: copy .env.example, fill in LLM_API_KEY/LLM_BASE_URL/LLM_MODEL if you
# want ambiguous comments escalated to an LLM (optional - without it, the
# local model's own label is used as-is for everything)

# --month is shorthand for --input runs/<month>/comments.json and
# --output runs/<month>/analysis_result.json
python -m sosmed_sentiment.cli.analyze \
  --month 2026-08 \
  --threshold-config config/thresholds.yaml   # required only with LLM env vars set

python -m sosmed_sentiment.cli.generate_report \
  --input runs/2026-08/analysis_result.json \
  --output runs/2026-08/report.html
```

A quick fixture to try the CLI against without real scraped data:
`docs/examples/comments.sample.json` (9 synthetic comments, matches the real
input schema).

### Resuming an interrupted run

`analyze` writes `.analyze-partial.jsonl` next to `--output` as it goes -
preprocessing + classification on ~6,000 comments takes ~20-25 minutes
(stemming + model inference), long enough that a killed process or a
background job hitting a shell timeout shouldn't mean starting over. Rerun
the exact same command and already-processed comments are skipped. Pass
`--fresh` to ignore the checkpoint and reclassify everything.

### Calibrating the escalation threshold

`config/thresholds.yaml` is checked in with a value already calibrated against
this repo's own 200-comment labeled sample - see the comments in that file for
the full sweep and reasoning. To recalibrate against a new labeled sample (a
different product line, a different model), label 200 comments the same way:

```sh
python scripts/generate_labeling_sample.py   # writes local/labeling_sample.xlsx
# ... fill in the sentiment_label column, save as
# local/labeling_sample_labeled.xlsx (see docs/calibration/codebook.md for
# label definitions) ...
python scripts/calibrate_threshold.py
```

`local/` is gitignored on purpose - it holds real customer comment text and
is never committed (see the note in `.gitignore`). `calibrate_threshold.py`
mirrors just `comment_id`+`sentiment_label`+`notes` (no comment text or
username) to `config/calibration/tahap-b-labels.csv`, which IS committed -
that's the reproducible, privacy-safe half of the labeling work.

There is deliberately no threshold baked into the code itself - two earlier
assumptions in this project (a stemming cache that didn't exist, an "LLM is
expensive" estimate that was never priced) turned out wrong once measured, so
this one is never guessed.

## License

This project is licensed under the [MIT License](LICENSE).
