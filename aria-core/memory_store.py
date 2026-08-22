# -*- coding: utf-8 -*-
import sqlite3
from pathlib import Path
import contextlib

DB_PATH = Path(__file__).parent / "aria_memory.db"

def get_db_connection():
    # Added timeout to wait for locks instead of crashing instantly under load
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with contextlib.closing(get_db_connection()) as conn:
        with conn:
            c = conn.cursor()
            
            # 1. Facts / Profile Store
            c.execute("""
                CREATE TABLE IF NOT EXISTS facts (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 2. Conversation History
            c.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    message TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 3. Security Audit Log
            c.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    status TEXT NOT NULL,
                    output TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 4. Proactive Memory Triggers
            c.execute("""
                CREATE TABLE IF NOT EXISTS triggers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    trigger_phrase TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 5. Engine Metrics
            c.execute("""
                CREATE TABLE IF NOT EXISTS engine_metrics (
                    provider TEXT PRIMARY KEY,
                    tokens_consumed INTEGER DEFAULT 0,
                    status_code INTEGER,
                    latency REAL,
                    consecutive_failures INTEGER DEFAULT 0,
                    cooldown_timestamp REAL DEFAULT 0.0
                )
            """)

            # 6. Agent Plans
            c.execute("""
                CREATE TABLE IF NOT EXISTS agent_plans (
                    goal_id TEXT PRIMARY KEY,
                    plan_json TEXT NOT NULL,
                    step_states TEXT,
                    execution_history TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Ensure WAL mode
            c.execute("PRAGMA journal_mode=WAL")

def set_fact(key: str, value: str):
    with contextlib.closing(get_db_connection()) as conn:
        with conn:
            conn.execute("""
                INSERT INTO facts (key, value, updated_at) 
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET 
                    value = excluded.value, 
                    updated_at = CURRENT_TIMESTAMP
            """, (key.strip(), str(value).strip()))

def get_fact(key: str) -> str | None:
    with contextlib.closing(get_db_connection()) as conn:
        c = conn.execute("SELECT value FROM facts WHERE key = ?", (key.strip(),))
        row = c.fetchone()
        return row["value"] if row else None

def get_all_facts() -> dict:
    with contextlib.closing(get_db_connection()) as conn:
        c = conn.execute("SELECT key, value FROM facts")
        return {row["key"]: row["value"] for row in c.fetchall()}

def add_message(user_id: int, role: str, message: str):
    with contextlib.closing(get_db_connection()) as conn:
        with conn:
            conn.execute("INSERT INTO history (user_id, role, message) VALUES (?, ?, ?)", (user_id, role, message))

def get_recent_history(user_id: int, limit: int = 6) -> str:
    with contextlib.closing(get_db_connection()) as conn:
        c = conn.execute("""
            SELECT role, message FROM history 
            WHERE user_id = ? 
            ORDER BY id DESC LIMIT ?
        """, (user_id, limit))
        rows = c.fetchall()
        if not rows:
            return "No prior conversation history."
        history_lines = [f"{r['role'].capitalize()}: {r['message']}" for r in reversed(rows)]
        return "\n".join(history_lines)

def log_audit(user_id: int, action: str, risk: str, summary: str, status: str, output: str = None):
    with contextlib.closing(get_db_connection()) as conn:
        with conn:
            conn.execute("""
                INSERT INTO audit_log (user_id, action, risk_level, summary, status, output)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, action, risk, summary, status, output))

def set_trigger(user_id: int, trigger_phrase: str, payload: str):
    with contextlib.closing(get_db_connection()) as conn:
        with conn:
            conn.execute("""
                INSERT INTO triggers (user_id, trigger_phrase, payload)
                VALUES (?, ?, ?)
            """, (user_id, trigger_phrase.strip().lower(), payload.strip()))

def get_triggers(user_id: int) -> list[dict]:
    with contextlib.closing(get_db_connection()) as conn:
        c = conn.execute("SELECT id, trigger_phrase, payload FROM triggers WHERE user_id = ?", (user_id,))
        return [{"id": r["id"], "trigger_phrase": r["trigger_phrase"], "payload": r["payload"]} for r in c.fetchall()]

def get_engine_metric(provider: str) -> dict | None:
    with contextlib.closing(get_db_connection()) as conn:
        c = conn.execute("SELECT * FROM engine_metrics WHERE provider = ?", (provider,))
        row = c.fetchone()
        return dict(row) if row else None

def update_engine_metric(provider: str, tokens: int, status: int, latency: float, failures: int, cooldown: float):
    with contextlib.closing(get_db_connection()) as conn:
        with conn:
            conn.execute("""
                INSERT INTO engine_metrics (provider, tokens_consumed, status_code, latency, consecutive_failures, cooldown_timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider) DO UPDATE SET
                    tokens_consumed = tokens_consumed + excluded.tokens_consumed,
                    status_code = excluded.status_code,
                    latency = excluded.latency,
                    consecutive_failures = excluded.consecutive_failures,
                    cooldown_timestamp = excluded.cooldown_timestamp
            """, (provider, tokens, status, latency, failures, cooldown))

def set_agent_plan(goal_id: str, plan_json: str, step_states: str, execution_history: str):
    with contextlib.closing(get_db_connection()) as conn:
        with conn:
            conn.execute("""
                INSERT INTO agent_plans (goal_id, plan_json, step_states, execution_history, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(goal_id) DO UPDATE SET
                    plan_json = excluded.plan_json,
                    step_states = excluded.step_states,
                    execution_history = excluded.execution_history,
                    updated_at = CURRENT_TIMESTAMP
            """, (goal_id, plan_json, step_states, execution_history))

def get_agent_plan(goal_id: str) -> dict | None:
    with contextlib.closing(get_db_connection()) as conn:
        c = conn.execute("SELECT * FROM agent_plans WHERE goal_id = ?", (goal_id,))
        row = c.fetchone()
        return dict(row) if row else None

try:
    init_db()
except Exception as _db_err:
    import logging
    logging.warning(f"[memory_store] DB init failed — {_db_err}. Memory features will be unavailable.")