#!/usr/bin/env python3
"""
build_rater_histories.py -- parse per-rater moral-verdict histories from an
NDJSON of r/AmItheAsshole comments. Python stdlib only.

A "verdict" is the standard AITA acronym in a TOP-LEVEL comment (parent is the
submission, i.e. parent_id starts with "t3_"). Matching is CASE-SENSITIVE on a
word boundary so the casual words "nah"/"info"/"info:" don't create false
positives; the first acronym in the body wins. YWBTA/YWNBTA fold to YTA/NTA.

For each post we rank its non-bot top-level comments by created_utc
(comment_rank = 1 is the earliest commenter) as a proxy for how much social
information the rater had seen.

Outputs (restricted to raters with >= --min-verdicts), written to --out-dir:
  verdicts.csv        comment_id, author, post_id, verdict, created_utc, score, comment_rank
  rater_summary.csv   author, n_verdicts, n_{YTA,NTA,ESH,NAH,INFO}, frac_esh_nah, n_posts, first_utc, last_utc
  post_coverage.csv   post_id, n_verdicts, n_raters, n_{YTA,NTA,ESH,NAH,INFO}
  stats.json          overall (unfiltered) summary stats

Overall stats (over ALL raters) are also printed. Bots and deleted authors are
excluded everywhere.

Usage:
  python3 build_rater_histories.py data/pilot_comments.ndjson --min-verdicts 5 --out-dir data/pilot_out
"""
import argparse, json, os, re, csv, sys
from collections import Counter, defaultdict

VERDICTS = ["YTA", "NTA", "ESH", "NAH", "INFO"]
VERDICT_RE = re.compile(r"\b(YWNBTA|YWBTA|YTA|NTA|ESH|NAH|INFO)\b")   # case-sensitive
FOLD = {"YWBTA": "YTA", "YWNBTA": "NTA"}
BOTS = {"AutoModerator", "Judgement_Bot_AITA", "AmItheAsshole-ModTeam", None, "[deleted]", ""}


def parse_verdict(body):
    if not body:
        return None
    m = VERDICT_RE.search(body)
    if not m:
        return None
    v = m.group(1)
    return FOLD.get(v, v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--min-verdicts", type=int, default=100)
    ap.add_argument("--out-dir", default="data/aita_out")
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    n_comments = n_toplevel = n_toplevel_nonbot = 0
    # per post: list of (created_utc, comment_id, author, verdict, score) for non-bot top-level
    by_post = defaultdict(list)

    with open(args.input) as f:
        for line in f:
            if not line.strip():
                continue
            c = json.loads(line)
            n_comments += 1
            if not str(c.get("parent_id", "")).startswith("t3_"):
                continue
            n_toplevel += 1
            author = c.get("author")
            if author in BOTS:
                continue
            n_toplevel_nonbot += 1
            v = parse_verdict(c.get("body"))
            by_post[c["link_id"]].append(
                (int(c["created_utc"]), c["id"], author, v, c.get("score")))

    # rank non-bot top-level comments per post by time; collect parsed verdicts
    verdict_rows = []          # comment_id, author, post_id, verdict, created_utc, score, rank
    for post, lst in by_post.items():
        lst.sort(key=lambda t: (t[0], t[1]))
        for rank, (utc, cid, author, v, score) in enumerate(lst, start=1):
            if v is not None:
                verdict_rows.append((cid, author, post, v, utc, score, rank))

    n_verdicts = len(verdict_rows)

    # per-rater aggregation (ALL raters, for stats + depth distribution)
    rater = defaultdict(lambda: {"counts": Counter(), "posts": set(),
                                 "first": None, "last": None})
    for cid, author, post, v, utc, score, rank in verdict_rows:
        r = rater[author]
        r["counts"][v] += 1
        r["posts"].add(post)
        r["first"] = utc if r["first"] is None else min(r["first"], utc)
        r["last"] = utc if r["last"] is None else max(r["last"], utc)

    def depth(a):
        return sum(rater[a]["counts"].values())

    # ---- overall stats -----------------------------------------------------
    vdist = Counter(row[3] for row in verdict_rows)
    parse_rate = n_verdicts / n_toplevel_nonbot if n_toplevel_nonbot else 0.0
    depths = sorted((depth(a) for a in rater), reverse=True)
    def n_ge(k): return sum(1 for d in depths if d >= k)

    stats = {
        "input": args.input,
        "n_comments": n_comments,
        "n_toplevel": n_toplevel,
        "n_toplevel_nonbot": n_toplevel_nonbot,
        "toplevel_share": round(n_toplevel / n_comments, 4) if n_comments else 0,
        "n_verdicts": n_verdicts,
        "parse_rate_of_nonbot_toplevel": round(parse_rate, 4),
        "n_unique_raters": len(rater),
        "verdict_distribution": {v: vdist.get(v, 0) for v in VERDICTS},
        "verdict_proportions": {v: round(vdist.get(v, 0) / n_verdicts, 4) if n_verdicts else 0
                                for v in VERDICTS},
        "raters_ge": {k: n_ge(k) for k in (5, 10, 20, 25, 50, 100, 250, 500)},
        "min_verdicts_for_csv": args.min_verdicts,
    }
    json.dump(stats, open(os.path.join(args.out_dir, "stats.json"), "w"), indent=2)

    print("=" * 60)
    print(f"INPUT: {args.input}")
    print(f"  comments total            {n_comments:,}")
    print(f"  top-level                 {n_toplevel:,}  ({stats['toplevel_share']:.1%} of comments)")
    print(f"  top-level non-bot         {n_toplevel_nonbot:,}")
    print(f"  parsed verdicts           {n_verdicts:,}  "
          f"(parse rate {parse_rate:.1%} of non-bot top-level)")
    print(f"  unique raters             {len(rater):,}")
    print("  verdict distribution:")
    for v in VERDICTS:
        print(f"     {v:5} {vdist.get(v,0):>8,}  {stats['verdict_proportions'][v]:6.1%}")
    print("  depth distribution (raters with >= k verdicts in this window):")
    for k in (5, 10, 20, 25, 50, 100, 250, 500):
        print(f"     >= {k:<4} {n_ge(k):>7,}")
    modal = max(VERDICTS, key=lambda v: vdist.get(v, 0)) if n_verdicts else None
    print(f"  SANITY: modal verdict = {modal}; parse_rate={parse_rate:.1%}; "
          f"bots in raters = {sorted(set(rater) & BOTS) or 'none'}")

    # ---- CSV outputs (restricted to deep raters) ---------------------------
    deep = {a for a in rater if depth(a) >= args.min_verdicts}
    with open(os.path.join(args.out_dir, "verdicts.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["comment_id", "author", "post_id", "verdict", "created_utc", "score", "comment_rank"])
        for cid, author, post, v, utc, score, rank in verdict_rows:
            if author in deep:
                w.writerow([cid, author, post, v, utc, score, rank])

    with open(os.path.join(args.out_dir, "rater_summary.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["author", "n_verdicts"] + [f"n_{v}" for v in VERDICTS] +
                   ["frac_esh_nah", "n_posts", "first_utc", "last_utc"])
        for a in sorted(deep, key=depth, reverse=True):
            r = rater[a]; n = sum(r["counts"].values())
            esh_nah = (r["counts"]["ESH"] + r["counts"]["NAH"]) / n if n else 0
            w.writerow([a, n] + [r["counts"].get(v, 0) for v in VERDICTS] +
                       [round(esh_nah, 4), len(r["posts"]), r["first"], r["last"]])

    post_agg = defaultdict(lambda: {"raters": set(), "counts": Counter()})
    for cid, author, post, v, utc, score, rank in verdict_rows:
        if author in deep:
            post_agg[post]["raters"].add(author)
            post_agg[post]["counts"][v] += 1
    with open(os.path.join(args.out_dir, "post_coverage.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["post_id", "n_verdicts", "n_raters"] + [f"n_{v}" for v in VERDICTS])
        for post, d in sorted(post_agg.items(), key=lambda kv: -len(kv[1]["raters"])):
            w.writerow([post, sum(d["counts"].values()), len(d["raters"])] +
                       [d["counts"].get(v, 0) for v in VERDICTS])

    print(f"\n  deep raters (>= {args.min_verdicts}): {len(deep):,}")
    print(f"  wrote verdicts.csv / rater_summary.csv / post_coverage.csv / stats.json -> {args.out_dir}/")


if __name__ == "__main__":
    main()
