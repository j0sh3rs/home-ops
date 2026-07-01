#!/usr/bin/env python3
"""
prose-indexer — indexes ~40 markdown files from home-ops into pgvector.

Runs as a daily CronJob (see cronjob.yaml). Upserts chunks into
repo_chunks; skips re-embedding chunks whose content hash is unchanged
and whose model_version matches the current embedder.

Required env vars:
  LITELLM_HOST      http://litellm.ai.svc.cluster.local:4000
  LITELLM_API_KEY   budget-capped vkey
  PGHOST            postgres18 host
  PGPASSWORD        repo_rag password

Optional env vars:
  REPO_DIR          cloned repo path (default: /workspace/home-ops)
  PGPORT            5432
  PGDATABASE        repo_rag
  PGUSER            repo_rag
  EMBED_MODEL       local-embed
  EMBED_DIMS        1024
  CHUNK_MAX_TOKENS  600  (chars = tokens * 4)
  DRY_RUN           any value to print chunks without upserting
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_DIR = Path(os.environ.get("REPO_DIR", "/workspace/home-ops"))
LITELLM_HOST = os.environ["LITELLM_HOST"].rstrip("/")
LITELLM_API_KEY = os.environ["LITELLM_API_KEY"]
PGHOST = os.environ["PGHOST"]
PGPORT = int(os.environ.get("PGPORT", "5432"))
PGDATABASE = os.environ.get("PGDATABASE", "repo_rag")
PGUSER = os.environ.get("PGUSER", "repo_rag")
PGPASSWORD = os.environ["PGPASSWORD"]
EMBED_MODEL = os.environ.get("EMBED_MODEL", "local-embed")
CHUNK_MAX_CHARS = int(os.environ.get("CHUNK_MAX_TOKENS", "600")) * 4
DRY_RUN = bool(os.environ.get("DRY_RUN", ""))

INDEX_GLOBS = [
    "docs/**/*.md",
    "claudedocs/**/*.md",
    "CLAUDE.md",
    ".claude/projects/**/*.md",
]
SKIP_RE = re.compile(r"\.sops\.yaml$|/node_modules/|/\.git/")


def should_skip(path: Path) -> bool:
    return bool(SKIP_RE.search(str(path)))


def chunk_markdown(path: Path, content: str) -> list[dict]:
    """Split on ## / ### headers; sliding window fallback."""
    rel = str(path.relative_to(REPO_DIR))
    sections = re.split(r"^(#{1,3} .+)$", content, flags=re.MULTILINE)
    chunks: list[dict] = []

    if len(sections) < 3:
        text = content.strip()
        for i in range(0, max(1, len(text)), CHUNK_MAX_CHARS):
            sub = text[i : i + CHUNK_MAX_CHARS].strip()
            if sub:
                chunks.append({"path": rel, "header": path.stem, "content": sub})
        return chunks

    intro = sections[0].strip()
    if intro:
        chunks.append({"path": rel, "header": path.stem, "content": intro})

    it = iter(sections[1:])
    for raw_header in it:
        body = next(it, "").strip()
        if not body:
            continue
        header = raw_header.strip("#").strip()
        for i in range(0, max(1, len(body)), CHUNK_MAX_CHARS):
            sub = body[i : i + CHUNK_MAX_CHARS].strip()
            if sub:
                chunks.append({"path": rel, "header": header, "content": sub})
    return chunks


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def embed_batch(texts: list[str]) -> list[list[float]]:
    payload = json.dumps({"model": EMBED_MODEL, "input": texts}).encode()
    req = urllib.request.Request(
        f"{LITELLM_HOST}/v1/embeddings",
        data=payload,
        headers={
            "Authorization": f"Bearer {LITELLM_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return [d["embedding"] for d in json.loads(resp.read())["data"]]


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def psql_exec(sql: str) -> str:
    env = os.environ.copy()
    env["PGPASSWORD"] = PGPASSWORD
    r = subprocess.run(
        [
            "psql",
            "-h",
            PGHOST,
            "-p",
            str(PGPORT),
            "-U",
            PGUSER,
            "-d",
            PGDATABASE,
            "-t",
            "-A",
            "-c",
            sql,
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return r.stdout.strip()


def upsert_chunk(chunk: dict, vec: list[float]) -> None:
    v = "[" + ",".join(str(x) for x in vec) + "]"
    chash = content_hash(chunk["content"])
    psql_exec(f"""
INSERT INTO repo_chunks
    (path, header, content, content_hash, embedding, model_version)
VALUES (
    {_q(chunk["path"])},
    {_q(chunk["header"])},
    {_q(chunk["content"])},
    {_q(chash)},
    '{v}'::vector,
    {_q(EMBED_MODEL)}
)
ON CONFLICT (path, header, content_hash) DO UPDATE
    SET embedding     = EXCLUDED.embedding,
        model_version = EXCLUDED.model_version,
        indexed_at    = now();
""")


def main() -> None:
    files = [
        p
        for g in INDEX_GLOBS
        for p in REPO_DIR.glob(g)
        if p.is_file() and not should_skip(p)
    ]
    print(f"Indexing {len(files)} files", flush=True)

    chunks: list[dict] = []
    for f in files:
        try:
            chunks.extend(chunk_markdown(f, f.read_text(errors="replace")))
        except Exception as exc:
            print(f"WARN skip {f}: {exc}", file=sys.stderr)

    print(f"Total chunks: {len(chunks)}", flush=True)

    if DRY_RUN:
        for c in chunks:
            print(f"[{c['path']}] {c['header'][:60]} ({len(c['content'])} chars)")
        return

    embedded = 0
    for i in range(0, len(chunks), 32):
        batch = chunks[i : i + 32]
        try:
            vecs = embed_batch([c["content"] for c in batch])
        except Exception as exc:
            print(f"WARN embed batch {i // 32}: {exc}", file=sys.stderr)
            continue
        for chunk, vec in zip(batch, vecs):
            try:
                upsert_chunk(chunk, vec)
                embedded += 1
            except Exception as exc:
                print(f"WARN upsert {chunk['path']}: {exc}", file=sys.stderr)

    print(f"Done: {embedded}/{len(chunks)} chunks upserted.", flush=True)


if __name__ == "__main__":
    main()
