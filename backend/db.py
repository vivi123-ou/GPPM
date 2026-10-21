import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "testpilot.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS requirements(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS test_cases(
  id TEXT PRIMARY KEY,
  requirement_id TEXT,
  json TEXT NOT NULL,
  version INTEGER DEFAULT 1,
  status TEXT DEFAULT 'active');

CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT DEFAULT CURRENT_TIMESTAMP,
  finished_at TEXT,
  bug_flags_snapshot TEXT,
  summary TEXT);

CREATE TABLE IF NOT EXISTS results(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER, test_case_id TEXT, data_set TEXT,
  status TEXT, error_msg TEXT, duration_ms INTEGER,
  ai_analysis_json TEXT);

CREATE TABLE IF NOT EXISTS step_results(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  result_id INTEGER, idx INTEGER, action TEXT,
  status TEXT, screenshot_path TEXT, detail TEXT);

CREATE TABLE IF NOT EXISTS healing_patches(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  result_id INTEGER, test_case_id TEXT, step_idx INTEGER,
  old_target TEXT, new_target TEXT, reason TEXT,
  status TEXT DEFAULT 'pending');
"""

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()