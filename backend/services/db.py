"""
SportsCaster Pro - Database Service (Final)
admin/admin is GUARANTEED on every startup via INSERT OR REPLACE.
Never need to delete the database manually.
"""
import sqlite3, os, logging
from pathlib import Path

logger = logging.getLogger("sportscaster.db")
DB_PATH = os.environ.get("DB_PATH", "../config/sportscaster.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn(); c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT DEFAULT 'admin'
    )""")
    # INSERT OR REPLACE guarantees admin/admin works even if DB is from old version
    c.execute("INSERT OR REPLACE INTO users (username,password,role) VALUES ('admin','admin','admin')")

    c.execute("""CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY, username TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sport TEXT NOT NULL, team_a TEXT NOT NULL, team_b TEXT NOT NULL,
        state_json TEXT DEFAULT '{}',
        created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER NOT NULL, event_type TEXT NOT NULL,
        payload TEXT DEFAULT '{}', ts TEXT DEFAULT (datetime('now'))
    )""")
    # Cricket-specific tables
    c.execute("""CREATE TABLE IF NOT EXISTS match_state (
        id INTEGER PRIMARY KEY, data TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT DEFAULT (datetime('now'))
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS squads_data (
        id INTEGER PRIMARY KEY, data TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT DEFAULT (datetime('now'))
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS ui_state (
        id INTEGER PRIMARY KEY, data TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT DEFAULT (datetime('now'))
    )""")
    c.execute("INSERT OR IGNORE INTO ui_state (id,data) VALUES (1,'{\"scorebar\":true,\"scorecard\":false}')")
    c.execute("""CREATE TABLE IF NOT EXISTS undo_stack (
        id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL,
        label TEXT DEFAULT '', created_at TEXT DEFAULT (datetime('now'))
    )""")
    for sport in ("football","hockey","volleyball","custom"):
        c.execute(f"""CREATE TABLE IF NOT EXISTS {sport}_state (
            id INTEGER PRIMARY KEY, data TEXT NOT NULL DEFAULT '{{}}',
            updated_at TEXT DEFAULT (datetime('now'))
        )""")
    c.execute("""CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_name TEXT NOT NULL, player_name TEXT NOT NULL,
        position INTEGER DEFAULT 0, sport TEXT DEFAULT 'cricket',
        created_at TEXT DEFAULT (datetime('now')),
        UNIQUE(team_name, player_name, sport)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS camera_sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        label TEXT NOT NULL, url TEXT NOT NULL UNIQUE,
        type TEXT DEFAULT 'ip', active INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    c.execute("INSERT OR IGNORE INTO camera_sources (label,url,type,active) VALUES ('USB Camera 0','0','usb',1)")
    c.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY, value TEXT NOT NULL
    )""")
    for k,v in {
        "stream_url":"","stream_key":"","camera_source":"0",
        "ai_enabled":"false","ai_model":"default",
        "hotspot_ssid":"SportsCaster","hotspot_pass":"broadcast1",
        "session_expiry_days":"7",
    }.items():
        c.execute("INSERT OR IGNORE INTO settings (key,value) VALUES (?,?)", (k,v))

    conn.commit(); conn.close()
    logger.info(f"DB ready: {DB_PATH} (admin/admin guaranteed)")


def get_setting(key, default=None):
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, str(value)))
    conn.commit(); conn.close()
