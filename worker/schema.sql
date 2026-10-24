-- Pacific Classics visit statistics (no IP addresses or cookies stored)
CREATE TABLE IF NOT EXISTS hits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,            -- unix ms
  day TEXT NOT NULL,              -- YYYY-MM-DD (Europe/Prague)
  kind TEXT NOT NULL,             -- page | car | quote
  ref TEXT,                       -- car code PC-xxxxxx
  title TEXT,
  view TEXT,                      -- listings | models | service | legal
  country TEXT, city TEXT, lat REAL, lon REAL,   -- city-level, from Cloudflare
  visitor TEXT,                   -- hash(ip+ua+daily salt): counts unique visitors per day, cannot be reversed
  referrer TEXT,                  -- referring host only
  device TEXT                     -- mobile | desktop
);
CREATE INDEX IF NOT EXISTS hits_day ON hits(day);
CREATE INDEX IF NOT EXISTS hits_ref ON hits(ref);
