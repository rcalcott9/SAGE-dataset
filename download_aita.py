#!/usr/bin/env python3
"""
download_aita.py -- pull r/AmItheAsshole comments from the Arctic Shift API into
an NDJSON file. Python stdlib only.

Arctic Shift behaviour (verified 2026-07-15):
  * endpoint: https://arctic-shift.photon-reddit.com/api/comments/search
  * params: subreddit, after (epoch s), before (epoch s), sort=asc, limit (MAX 100)
  * REQUIRES a real User-Agent header (default urllib UA -> HTTP 403)
  * returns {"data": [ {...comment...}, ... ]} ascending by created_utc when sort=asc
  * limit > 100 -> HTTP 400

Pagination: request [after, before) ascending in pages of 100, advancing `after`
to the last created_utc of each page and de-duplicating same-second boundary rows
by id. Progress is checkpointed to <out>.checkpoint after every page so the pull
is resumable; rerun with --resume (continue from checkpoint) or --after to override.

Only the fields we need are kept, to keep the NDJSON small:
  id, author, link_id, parent_id, created_utc, score, body

Usage:
  python3 download_aita.py --after 2026-05-01 --before 2026-05-08 --out data/pilot_comments.ndjson
  python3 download_aita.py --after 2025-09-01 --before 2026-03-01 --out data/aita_comments.ndjson --resume
"""
import argparse, json, os, sys, time, urllib.request, urllib.error, datetime as dt

BASE = "https://arctic-shift.photon-reddit.com/api/comments/search"
UA = "SAGE-research-dataset/0.1 (moral-judgment replication; contact rcalcott@g.harvard.edu)"
KEEP = ("id", "author", "link_id", "parent_id", "created_utc", "score", "body")
MAX_LIMIT = 100


def to_epoch(s):
    """Accept an epoch int/str or an ISO date/datetime (UTC)."""
    s = str(s)
    if s.isdigit():
        return int(s)
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return int(dt.datetime.strptime(s, fmt).replace(tzinfo=dt.timezone.utc).timestamp())
        except ValueError:
            continue
    raise ValueError(f"cannot parse time: {s!r}")


def fetch(after, before, subreddit, retries=6):
    q = f"subreddit={subreddit}&after={after}&before={before}&sort=asc&limit={MAX_LIMIT}"
    req = urllib.request.Request(f"{BASE}?{q}", headers={"User-Agent": UA})
    delay = 2.0
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)["data"]
        except urllib.error.HTTPError as e:
            # 422 is intermittently thrown by this API for otherwise-valid
            # requests (identical retry succeeds), so treat it as transient.
            if e.code in (408, 422, 429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(delay); delay = min(delay * 2, 60); continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries - 1:
                time.sleep(delay); delay = min(delay * 2, 60); continue
            raise
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--after", help="start (inclusive) epoch or ISO date, UTC")
    ap.add_argument("--before", required=True, help="end (exclusive) epoch or ISO date, UTC")
    ap.add_argument("--out", required=True)
    ap.add_argument("--subreddit", default="AmItheAsshole")
    ap.add_argument("--sleep", type=float, default=1.0, help="seconds between requests (>=1.0)")
    ap.add_argument("--resume", action="store_true", help="continue from <out>.checkpoint")
    args = ap.parse_args()

    sleep = max(1.0, args.sleep)                       # never hammer the API
    before = to_epoch(args.before)
    ckpt = args.out + ".checkpoint"

    if args.after is not None:
        after = to_epoch(args.after)
    elif args.resume and os.path.exists(ckpt):
        after = int(json.load(open(ckpt))["after"])
        print(f"[resume] continuing from checkpoint after={after} "
              f"({dt.datetime.utcfromtimestamp(after)}Z)", flush=True)
    else:
        sys.exit("need --after (or --resume with an existing checkpoint)")

    mode = "a" if (args.resume and os.path.exists(args.out)) else "w"
    total = 0
    if mode == "a":
        total = sum(1 for _ in open(args.out))
        print(f"[resume] {total} rows already in {args.out}", flush=True)

    prev_boundary = set()                              # ids at the last-second of prev page
    t0 = time.time()
    with open(args.out, mode) as f:
        page = 0
        while after < before:
            batch = fetch(after, before, args.subreddit)
            if not batch:
                break
            new = [c for c in batch if c["id"] not in prev_boundary]
            for c in new:
                f.write(json.dumps({k: c.get(k) for k in KEEP}) + "\n")
            f.flush()
            total += len(new)
            last = batch[-1]["created_utc"]
            page += 1
            # checkpoint every page
            with open(ckpt, "w") as ck:
                json.dump({"after": last, "before": before, "total": total,
                           "utc": str(dt.datetime.utcfromtimestamp(last)) + "Z"}, ck)
            if page % 25 == 0 or len(batch) < MAX_LIMIT:
                rate = total / max(1e-9, time.time() - t0)
                print(f"[page {page}] {dt.datetime.utcfromtimestamp(last)}Z  "
                      f"total={total:,}  (+{len(new)})  ~{rate:.0f} rows/s", flush=True)
            # advance; guard against a single second holding a full page
            after = last + 1 if (last == after and len(batch) == MAX_LIMIT) else last
            prev_boundary = {c["id"] for c in batch if c["created_utc"] == last}
            time.sleep(sleep)

    print(f"[done] wrote {total:,} rows -> {args.out} "
          f"(reached {dt.datetime.utcfromtimestamp(min(after,before))}Z)", flush=True)


if __name__ == "__main__":
    main()
