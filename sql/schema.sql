CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS sources (
    id BIGSERIAL PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_key TEXT NOT NULL UNIQUE,
    title TEXT,
    url TEXT,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chunks (
    id BIGSERIAL PRIMARY KEY,
    source_id BIGINT REFERENCES sources(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    embedding VECTOR(1536),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(source_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS reports (
    id BIGSERIAL PRIMARY KEY,
    title TEXT,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
