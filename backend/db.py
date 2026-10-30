import json
import os
import re
import sqlite3
from pathlib import Path

DB_PATH = Path(os.getenv("TESTPILOT_DB") or Path(__file__).resolve().parent.parent / "testpilot.db")

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

-- Agent duyệt kịch bản: mỗi kịch bản giữ một bản đánh giá mới nhất
CREATE TABLE IF NOT EXISTS reviews(
  test_case_id TEXT PRIMARY KEY,
  score INTEGER, verdict TEXT, issues_json TEXT, source TEXT,
  decision TEXT, decision_reason TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP);

-- Nhật ký từng lượt pipeline agent (xem lại được: agent nào làm gì, bao lâu, dùng skill nào)
CREATE TABLE IF NOT EXISTS agent_runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT, target TEXT, requirement_id TEXT, trace_json TEXT, stats_json TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);

-- Skill do người dùng tạo và trạng thái bật/tắt (skill có sẵn nằm ở ai/skills/*.md)
CREATE TABLE IF NOT EXISTS skills(
  id TEXT PRIMARY KEY, name TEXT, description TEXT, agents_json TEXT, triggers_json TEXT,
  body TEXT, version TEXT DEFAULT '1.0', builtin INTEGER DEFAULT 0, enabled INTEGER DEFAULT 1,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP);

-- Bài học rút ra từ kết quả thật; phải được người duyệt (active) mới đưa vào prompt
CREATE TABLE IF NOT EXISTS lessons(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL, agent TEXT DEFAULT 'writer', source TEXT, host TEXT,
  status TEXT DEFAULT 'pending', uses INTEGER DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);

-- Ảnh chụp danh sách endpoint để phát hiện API thay đổi so với lúc sinh kịch bản
CREATE TABLE IF NOT EXISTS spec_snapshots(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  host TEXT, endpoints_json TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);

-- Câu trả lời của LLM theo băm prompt, để không gọi lại cho cùng một đầu vào
CREATE TABLE IF NOT EXISTS llm_cache(
  key TEXT PRIMARY KEY, response TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);

-- Kết quả đo khả năng phát hiện lỗi cài sẵn
CREATE TABLE IF NOT EXISTS benchmarks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  summary_json TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
"""

# Cột thêm sau: (bảng, cột, kiểu)
_COLUMNS = [("requirements", "parent_id", "INTEGER"),
            ("reviews", "verification", "TEXT"),
            ("results", "title", "TEXT"), ("results", "type", "TEXT"), ("results", "category", "TEXT"),
            ("results", "detail_json", "TEXT"), ("runs", "target", "TEXT"), ("runs", "cases_total", "INTEGER")]

USER_MARK, PASS_MARK = "__USERNAME__", "__PASSWORD__"
_SECRET_KEY = re.compile(r"pass|pwd", re.I)
_USER_KEY = re.compile(r"user|email|login|account", re.I)
# Mật khẩu sai do AI tự viết cho kịch bản âm tính: giữ nguyên, không phải tài khoản thật
_FAKE_SECRET = re.compile(r"wrong|sai|invalid|incorrect|fake|bad|khong|^x+$|^1234", re.I)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript(SCHEMA)
    for table, col, kind in _COLUMNS:
        if col not in {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {kind}")
    conn.commit()
    changed = scrub_secrets(conn)
    conn.close()
    if changed:      # VACUUM để giá trị cũ không còn nằm trong trang trống của file DB
        conn = get_conn()
        conn.execute("VACUUM")
        conn.close()


def scrub_secrets(conn: sqlite3.Connection) -> int:
    """Các bản cũ ghi mật khẩu thật vào data_sets của kịch bản Autopilot. Thay bằng dấu đánh dấu;
    giá trị thật chỉ đưa vào lúc thực thi (backend/vault.py). Chạy nhiều lần vẫn an toàn."""
    demo = os.getenv("SHOP_DEMO_PASSWORD") or ""
    autopilot = {f"REQ-{r['id']}" for r in conn.execute("SELECT id FROM requirements WHERE text LIKE '[Autopilot]%'")}
    rows = conn.execute("SELECT id, requirement_id, json FROM test_cases").fetchall()
    users: set[str] = set()
    parsed = []
    for r in rows:
        data = json.loads(r["json"])
        dirty = False
        for ds in data.get("data_sets") or []:
            values = ds.get("values") or {}
            for k, v in values.items():
                if not (_SECRET_KEY.search(k) and isinstance(v, str) and v) or v.startswith(("{{", "<", "__")):
                    continue
                if v == demo or (r["requirement_id"] in autopilot and not _FAKE_SECRET.search(v)):
                    values[k] = PASS_MARK
                    dirty = True
                    for uk, uv in values.items():
                        if _USER_KEY.search(uk) and isinstance(uv, str) and uv and not uv.startswith(("{{", "<", "__")):
                            users.add(uv)
                            values[uk] = USER_MARK
        parsed.append((r["id"], data, dirty))
    n = 0
    for tc_id, data, dirty in parsed:
        for ds in data.get("data_sets") or []:
            values = ds.get("values") or {}
            for k, v in values.items():
                if _USER_KEY.search(k) and v in users:
                    values[k] = USER_MARK
                    dirty = True
        if dirty:
            conn.execute("UPDATE test_cases SET json=? WHERE id=?", (json.dumps(data, ensure_ascii=False), tc_id))
            n += 1
    conn.commit()
    return n
