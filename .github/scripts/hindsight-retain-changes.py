#!/usr/bin/env python3
"""Retain home-ops change context (merged PRs + direct commits) into Hindsight.

Used by .github/workflows/hindsight-changes.yaml (#713). Stdlib only.

Modes:
  push      -- every commit in the push (GitHub compare before...after).
               A commit that belongs to a merged PR is stored once as the
               PR (document_id pr-<n>); otherwise as the commit
               (document_id commit-<sha>).
  backfill  -- the last --prs merged human PRs, plus (optionally) human
               direct commits on main since --commits-since.

Bot authors (login ending in "[bot]", e.g. renovate[bot]) are skipped.
document_id makes every write an idempotent upsert, so re-runs are safe.

Env: GITHUB_TOKEN, GITHUB_REPOSITORY, HINDSIGHT_URL, HINDSIGHT_API_KEY,
     HINDSIGHT_BANK (default home-ops-changes). --dry-run prints instead
     of retaining (HINDSIGHT_* not needed).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

GITHUB_API = "https://api.github.com"
REPO = os.environ.get("GITHUB_REPOSITORY", "j0sh3rs/home-ops")
BANK = os.environ.get("HINDSIGHT_BANK", "home-ops-changes")
MAX_BODY_CHARS = 6000
MAX_PATHS = 80
MAX_TAGS = 10
BATCH = 10


def _request(url: str, *, data: dict | None = None, headers: dict, method: str | None = None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def gh(path: str, **params) -> object:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    return _request(f"{GITHUB_API}{path}{query}", headers=headers)


def is_bot(login: str | None) -> bool:
    return bool(login) and login.endswith("[bot]")


def tags_for(paths: list[str], kind: str) -> list[str]:
    tags = ["home-ops", f"kind:{kind}"]
    for p in paths:
        parts = p.split("/")
        if parts[:2] == ["kubernetes", "apps"] and len(parts) >= 5:
            tag = f"app:{parts[2]}/{parts[3]}"
        elif parts[0] in ("talos", "docs", "archive", "bootstrap"):
            tag = f"area:{parts[0]}"
        elif parts[0] in (".github", ".renovate", ".taskfiles"):
            tag = "area:ci"
        else:
            continue
        if tag not in tags:
            tags.append(tag)
        if len(tags) >= MAX_TAGS:
            break
    return tags


def paths_block(paths: list[str]) -> str:
    shown = "\n".join(f"- {p}" for p in paths[:MAX_PATHS])
    more = f"\n- ... and {len(paths) - MAX_PATHS} more" if len(paths) > MAX_PATHS else ""
    return f"Changed paths:\n{shown}{more}" if paths else "Changed paths: (none)"


def pr_item(number: int) -> dict | None:
    pr = gh(f"/repos/{REPO}/pulls/{number}")
    if not pr.get("merged_at") or is_bot(pr["user"]["login"]):
        return None
    files: list[str] = []
    page = 1
    while len(files) < 300:
        batch = gh(f"/repos/{REPO}/pulls/{number}/files", per_page=100, page=page)
        files += [f["filename"] for f in batch]
        if len(batch) < 100:
            break
        page += 1
    body = (pr.get("body") or "").strip()[:MAX_BODY_CHARS]
    content = (
        f"home-ops pull request #{number} \"{pr['title']}\" by {pr['user']['login']}, "
        f"merged into {pr['base']['ref']} at {pr['merged_at']}.\n\n"
        f"Description:\n{body or '(no description)'}\n\n{paths_block(files)}"
    )
    return {
        "content": content,
        "context": "home-ops merged pull request: why this change was made",
        "document_id": f"pr-{number}",
        "timestamp": pr["merged_at"],
        "tags": tags_for(files, "pr"),
        "metadata": {
            "kind": "pr",
            "pr": str(number),
            "url": pr["html_url"],
            "merge_sha": pr.get("merge_commit_sha") or "",
        },
    }


def commit_item(sha: str, detail: dict | None = None) -> dict | None:
    c = detail or gh(f"/repos/{REPO}/commits/{sha}")
    login = (c.get("author") or {}).get("login") or c["commit"]["author"]["name"]
    if is_bot(login) or len(c.get("parents", [])) > 1:  # bots, merge commits
        return None
    files = [f["filename"] for f in c.get("files", [])]
    message = c["commit"]["message"].strip()[:MAX_BODY_CHARS]
    date = c["commit"]["author"]["date"]
    content = (
        f"home-ops commit {sha[:10]} by {c['commit']['author']['name']}, pushed "
        f"directly to main (no pull request), authored {date}.\n\n"
        f"Commit message:\n{message}\n\n{paths_block(files)}"
    )
    return {
        "content": content,
        "context": "home-ops direct commit to main: why this change was made",
        "document_id": f"commit-{sha}",
        "timestamp": date,
        "tags": tags_for(files, "commit"),
        "metadata": {"kind": "commit", "sha": sha, "url": c["html_url"]},
    }


def merged_pr_for(sha: str) -> int | None:
    for pr in gh(f"/repos/{REPO}/commits/{sha}/pulls"):
        if pr.get("merged_at") and pr["base"]["ref"] == "main":
            return pr["number"]
    return None


def collect_push(before: str, after: str) -> list[dict]:
    if set(before) == {"0"}:
        shas = [after]
    else:
        cmp = gh(f"/repos/{REPO}/compare/{before}...{after}")
        shas = [c["sha"] for c in cmp.get("commits", [])]
    items: dict[str, dict] = {}
    for sha in shas:
        pr = merged_pr_for(sha)
        doc = f"pr-{pr}" if pr else f"commit-{sha}"
        if doc in items:
            continue
        item = pr_item(pr) if pr else commit_item(sha)
        if item:
            items[doc] = item
    return list(items.values())


def collect_backfill(prs: int, commits_since: str) -> list[dict]:
    items: list[dict] = []
    if prs:
        found, page = 0, 1
        while found < prs and page <= 10:
            batch = gh(
                f"/repos/{REPO}/pulls",
                state="closed", base="main", sort="updated", direction="desc",
                per_page=100, page=page,
            )
            if not batch:
                break
            for pr in batch:
                if found >= prs:
                    break
                if pr.get("merged_at") and not is_bot(pr["user"]["login"]):
                    if item := pr_item(pr["number"]):
                        items.append(item)
                        found += 1
            page += 1
    if commits_since:
        page = 1
        while True:
            batch = gh(
                f"/repos/{REPO}/commits",
                sha="main", since=f"{commits_since}T00:00:00Z", per_page=100, page=page,
            )
            for c in batch:
                login = (c.get("author") or {}).get("login") or c["commit"]["author"]["name"]
                if is_bot(login) or len(c.get("parents", [])) > 1:
                    continue
                if merged_pr_for(c["sha"]):
                    continue  # covered by the PR backfill / its own pr-<n> doc
                if item := commit_item(c["sha"]):
                    items.append(item)
            if len(batch) < 100:
                break
            page += 1
    return items


def retain(items: list[dict]) -> None:
    url = os.environ["HINDSIGHT_URL"].rstrip("/")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.environ['HINDSIGHT_API_KEY']}",
    }
    endpoint = f"{url}/v1/default/banks/{urllib.parse.quote(BANK, safe='')}/memories"
    for i in range(0, len(items), BATCH):
        chunk = items[i : i + BATCH]
        _request(endpoint, data={"items": chunk, "async": True}, headers=headers, method="POST")
        print(f"retained {', '.join(it['document_id'] for it in chunk)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("push")
    p.add_argument("--before", required=True)
    p.add_argument("--after", required=True)
    b = sub.add_parser("backfill")
    b.add_argument("--prs", type=int, default=20)
    b.add_argument("--commits-since", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.mode == "push":
        items = collect_push(args.before, args.after)
    else:
        items = collect_backfill(args.prs, args.commits_since)

    print(f"{len(items)} item(s) to retain into bank {BANK}")
    if args.dry_run:
        for it in items:
            print(json.dumps(it, indent=2)[:1500])
        return 0
    if items:
        retain(items)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code} {e.url}: {e.read()[:300]!r}", file=sys.stderr)
        sys.exit(1)
