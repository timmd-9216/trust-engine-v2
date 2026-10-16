-- Initial schema for scrapping-tools on Postgres (Neon).
-- Replaces Firestore collections 'posts' and 'pending_jobs'.
-- Idempotent: safe to run multiple times.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    post_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    country TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'noreplies',
    replies_count INTEGER,
    max_posts_replies INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    extra JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_posts_status_platform_created_at
    ON posts (status, platform, created_at);
CREATE INDEX IF NOT EXISTS idx_posts_status_created_at
    ON posts (status, created_at);
CREATE INDEX IF NOT EXISTS idx_posts_status_candidate_id
    ON posts (status, candidate_id);
CREATE INDEX IF NOT EXISTS idx_posts_post_id
    ON posts (post_id);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    job_id TEXT NOT NULL,
    post_doc_id TEXT,
    post_id TEXT NOT NULL,
    platform TEXT,
    country TEXT,
    candidate_id TEXT,
    status TEXT NOT NULL,
    max_posts_replies INTEGER,
    sort_by TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    execution_log_file TEXT,
    error_log_file TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    extra JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_jobs_status_created_at
    ON jobs (status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_status_updated_at
    ON jobs (status, updated_at);
CREATE INDEX IF NOT EXISTS idx_jobs_post_id_status
    ON jobs (post_id, status);
CREATE INDEX IF NOT EXISTS idx_jobs_status_candidate_platform_country
    ON jobs (status, candidate_id, platform, country);
