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

## Monthly batch (the main workflow)

Put the month's videos in a CSV, then run one command.

```csv
url_or_id,account_type
7418294751977327878,affiliate
https://www.tiktok.com/@kol/video/7451234567890123456,kol
7461234567890123456,
```

Only `url_or_id` is required. It accepts a bare id, a full video URL, or a
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
| `--month`         | current | Run label / output folder, `YYYY-MM`                     |
| `--max-comments`  |  `200`  | Cap per video, replies included                          |
| `--max-replies`   |   `10`  | Cap on replies fetched per comment                       |
| `--video-delay`   |  `7,10` | Random seconds between videos, `MIN,MAX`                 |
| `--request-delay` |   `1,3` | Random seconds between requests inside one video         |
| `--fresh`         |  off    | Ignore the checkpoint and scrape every row again         |

### Resuming a broken run

Each video's result is appended to `runs/YYYY-MM/.partial.jsonl` the moment it
finishes. Rerun the exact same command and the batch picks up where it stopped
instead of starting over. This matters: at the default delays a 1000-video
batch runs for hours, so it will sometimes be interrupted.

Use `--fresh` to discard the checkpoint and rescrape everything.

### Smoke test

Before the batch starts, one small request runs against the first video in the
CSV. If TikTok has stopped answering, or the response no longer carries the
fields the parser expects, the run stops immediately with a one-line message
instead of failing silently hours in. Exit code is `2` for that case.

Put a video you know has comments on the first line of the CSV.

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
| `--max-replies`|       |   `10`  | Cap on replies per comment          |
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

## License

This project is licensed under the [MIT License](LICENSE).
