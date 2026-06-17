-- repo_rag schema — run once by the init-db Job.
-- Requires pgvector extension (already present in postgres18).
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS repo_chunks (
    id            bigserial    PRIMARY KEY,
    path          text         NOT NULL,
    header        text         NOT NULL,
    content       text         NOT NULL,
    content_hash  text         NOT NULL,
    embedding     vector(1024),
    model_version text         NOT NULL,
    indexed_at    timestamptz  NOT NULL DEFAULT now(),
    UNIQUE (path, header, content_hash)
);

-- ivfflat index — sequential scan is fine at <1K chunks but pre-create
-- for when the index grows. lists=10 is appropriate for ~200 chunks.
CREATE INDEX IF NOT EXISTS repo_chunks_embedding_idx
    ON repo_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 10);
