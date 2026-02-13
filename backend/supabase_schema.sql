CREATE TABLE IF NOT EXISTS sites (
    id BIGSERIAL PRIMARY KEY,
    root_url TEXT NOT NULL UNIQUE,
    name TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    monitor_schedule TEXT,
    next_crawl_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS crawl_results (
    id BIGSERIAL PRIMARY KEY,
    site_id BIGINT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    finished_at TIMESTAMPTZ NOT NULL,
    page_count INTEGER NOT NULL,
    raw_pages JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS llms_txt (
    id BIGSERIAL PRIMARY KEY,
    site_id BIGINT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    crawl_result_id BIGINT NOT NULL REFERENCES crawl_results(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_crawl_results_site_id ON crawl_results(site_id);
CREATE INDEX IF NOT EXISTS idx_llms_txt_site_id ON llms_txt(site_id);
ALTER TABLE sites ADD COLUMN IF NOT EXISTS next_crawl_at TIMESTAMPTZ;
