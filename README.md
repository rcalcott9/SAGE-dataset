# SAGE dataset — per-rater moral verdict histories from r/AmItheAsshole

Builds a dataset of individual raters' AITA verdict histories for a research
project replicating Sorensen et al. (2025), *Value Profiles for Encoding Human
Variation* (arXiv:2503.15484), in the moral-judgment domain.

## Pipeline

1. **`download_aita.py`** — pulls AmItheAsshole comments from the
   [Arctic Shift](https://arctic-shift.photon-reddit.com) API into NDJSON.
   Paginates `[after, before)` ascending by `created_utc` in pages of 100
   (the API max), ~1 request/second, checkpointing to `<out>.checkpoint` after
   every page so it is resumable (`--resume`, or `--after` to override). Keeps
   only `id, author, link_id, parent_id, created_utc, score, body`.

   API notes (verified 2026-07-15): a real `User-Agent` header is **required**
   (default urllib UA → HTTP 403); `limit` is capped at 100 (500 → HTTP 400);
   `after`/`before` accept epoch seconds or ISO dates; `sort=asc` returns
   ascending.

2. **`build_rater_histories.py`** — parses verdicts from **top-level** comments
   (`parent_id` starts with `t3_`) and writes per-rater histories.
   - Verdict match is **case-sensitive** on a word boundary (so casual
     "nah"/"info" don't false-positive); first acronym wins; `YWBTA`/`YWNBTA`
     fold to `YTA`/`NTA`. Categories: YTA, NTA, ESH, NAH, INFO.
   - Bots/deleted excluded everywhere: `AutoModerator`, `Judgement_Bot_AITA`,
     `AmItheAsshole-ModTeam`, `[deleted]`, null.
   - `comment_rank` = position of the rater's comment among the post's non-bot
     top-level comments ordered by `created_utc` (rank 1 = earliest) — a proxy
     for social-information exposure.
   - Outputs (restricted to raters with ≥ `--min-verdicts`): `verdicts.csv`,
     `rater_summary.csv`, `post_coverage.csv`, plus `stats.json` (overall,
     unfiltered) and a printed summary.

3. **`analysis/`** — downstream reports/plots (duckdb/pandas/matplotlib OK here;
   the pipeline itself is stdlib-only).

## Usage

```bash
# pilot: one week
python3 download_aita.py --after 2026-05-01 --before 2026-05-08 --out data/pilot_comments.ndjson
python3 build_rater_histories.py data/pilot_comments.ndjson --min-verdicts 5 --out-dir data/pilot_out

# full pull (background, resumable)
nohup python3 download_aita.py --after 2025-09-01 --before 2026-03-01 \
      --out data/aita_comments.ndjson --resume > data/download.log 2>&1 &
python3 build_rater_histories.py data/aita_comments.ndjson --min-verdicts 100 --out-dir data/aita_out
```

## Data policy

Raw NDJSON is kept locally and **not committed** (see `.gitignore`); only the
gzipped output CSVs are shared. Source: Arctic Shift (Reddit archive). See
`data/README.md` for the exact window, pull date, and filter rules.
