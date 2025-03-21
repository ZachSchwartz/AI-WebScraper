-- Create tables based on SQLAlchemy models
DROP TABLE IF EXISTS scraped_items;

CREATE TABLE scraped_items (
    id SERIAL PRIMARY KEY,
    keyword VARCHAR,
    source_url VARCHAR,
    relevance_score FLOAT,
    href_url VARCHAR,
    raw_data JSONB,
    processed_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes to improve query performance
CREATE INDEX IF NOT EXISTS idx_scraped_items_source_url ON scraped_items(source_url);
CREATE INDEX IF NOT EXISTS idx_scraped_items_url ON scraped_items(href_url);
CREATE INDEX IF NOT EXISTS idx_scraped_items_keyword ON scraped_items(keyword);
CREATE INDEX IF NOT EXISTS idx_scraped_items_relevance ON scraped_items(relevance_score);

-- Grant appropriate permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO postgres;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO postgres;

-- Add a comment to the table for documentation
COMMENT ON TABLE scraped_items IS 'Stores scraped items from web pages with relevance analysis';