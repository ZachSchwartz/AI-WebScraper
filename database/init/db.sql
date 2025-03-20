-- File: ./database/db.sql

-- Create the database if it doesn't exist
-- This is handled at runtime in your Python code, but adding as a safeguard
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_database WHERE datname = 'scraper') THEN
        CREATE DATABASE scraper;
    END IF;
END
$$;
-- Connect to the scraper database
\c scraper;

-- Create tables based on SQLAlchemy models
CREATE TABLE IF NOT EXISTS scraped_items (
    id SERIAL PRIMARY KEY,
    url VARCHAR NOT NULL,
    title VARCHAR,
    text_content TEXT,
    source_url VARCHAR,
    keyword VARCHAR,
    relevance_score FLOAT,
    processed_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    raw_data JSONB
);

-- Create indexes to improve query performance
CREATE INDEX IF NOT EXISTS idx_scraped_items_url ON scraped_items(url);
CREATE INDEX IF NOT EXISTS idx_scraped_items_keyword ON scraped_items(keyword);
CREATE INDEX IF NOT EXISTS idx_scraped_items_relevance ON scraped_items(relevance_score);

-- Grant appropriate permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO postgres;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO postgres;

-- Add a comment to the table for documentation
COMMENT ON TABLE scraped_items IS 'Stores scraped items from web pages with relevance analysis';