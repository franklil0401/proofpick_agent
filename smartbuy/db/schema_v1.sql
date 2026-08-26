PRAGMA foreign_keys = ON;

CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE products (
    model_id TEXT PRIMARY KEY,
    brand TEXT NOT NULL,
    model_name TEXT NOT NULL,
    region TEXT NOT NULL,
    display_size_inch REAL,
    resolution TEXT,
    refresh_rate_hz REAL,
    panel_type TEXT,
    is_oled INTEGER CHECK (is_oled IN (0, 1) OR is_oled IS NULL),
    has_usb_c INTEGER CHECK (has_usb_c IN (0, 1) OR has_usb_c IS NULL),
    usb_c_video INTEGER CHECK (usb_c_video IN (0, 1) OR usb_c_video IS NULL),
    usb_c_power_delivery_w REAL CHECK (usb_c_power_delivery_w > 0 OR usb_c_power_delivery_w IS NULL),
    stand_adjustment TEXT,
    width_mm REAL CHECK (width_mm > 0 OR width_mm IS NULL),
    weight_kg REAL CHECK (weight_kg > 0 OR weight_kg IS NULL),
    warranty TEXT,
    release_date TEXT,
    official_source_id TEXT NOT NULL,
    source_updated_at TEXT NOT NULL,
    FOREIGN KEY (official_source_id) REFERENCES source_records(source_id) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE source_records (
    source_id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    is_official INTEGER NOT NULL CHECK (is_official IN (0, 1)),
    region TEXT NOT NULL,
    published_at TEXT,
    accessed_at TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    redistribution_status TEXT NOT NULL,
    notes TEXT,
    FOREIGN KEY (model_id) REFERENCES products(model_id) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE price_observations (
    observation_id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    price_cny REAL NOT NULL CHECK (price_cny > 0),
    seller TEXT NOT NULL,
    region TEXT NOT NULL,
    stock_status TEXT NOT NULL,
    url TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    price_type TEXT NOT NULL,
    FOREIGN KEY (model_id) REFERENCES products(model_id)
);

CREATE TABLE evidence_records (
    evidence_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    normalized_field TEXT NOT NULL,
    normalized_value TEXT NOT NULL,
    original_value TEXT NOT NULL,
    evidence_location TEXT NOT NULL,
    confidence_level TEXT NOT NULL CHECK (confidence_level IN ('high', 'medium', 'low')),
    effective_time TEXT,
    conflict_group TEXT,
    FOREIGN KEY (source_id) REFERENCES source_records(source_id),
    FOREIGN KEY (model_id) REFERENCES products(model_id)
);

CREATE INDEX idx_products_brand_region ON products(brand, region);
CREATE INDEX idx_prices_model_time ON price_observations(model_id, observed_at DESC);
CREATE INDEX idx_sources_model ON source_records(model_id);
CREATE INDEX idx_evidence_model_field ON evidence_records(model_id, normalized_field);
CREATE INDEX idx_evidence_conflict ON evidence_records(conflict_group) WHERE conflict_group IS NOT NULL;
