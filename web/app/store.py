from __future__ import annotations

import json
import re
import sqlite3
import time

import structlog

from app.config import DATA_DIR, logger


class MemoryStore:
    def __init__(self):
        self.db_path = DATA_DIR / "agent_memory.db"
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT, user_msg TEXT, tool_calls TEXT,
                    result_summary TEXT, ts REAL
                );
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE, value TEXT, source TEXT, ts REAL
                );
                CREATE TABLE IF NOT EXISTS procedures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trigger_pattern TEXT, tool_sequence TEXT,
                    success_count INTEGER DEFAULT 1, ts REAL
                );
                CREATE INDEX IF NOT EXISTS idx_ep_msg ON episodes(user_msg);
                CREATE INDEX IF NOT EXISTS idx_facts_key ON facts(key);
            """)

    def save_episode(self, session_id: str, user_msg: str, tool_calls: list, summary: str):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("INSERT INTO episodes(session_id,user_msg,tool_calls,result_summary,ts) VALUES(?,?,?,?,?)",
                         (session_id, user_msg[:500], json.dumps(tool_calls, ensure_ascii=False)[:2000], summary[:500], time.time()))

    def recall_episodes(self, query: str = "", limit: int = 3) -> list[dict]:
        words = re.findall(r"[\u4e00-\u9fff\w]{2,}", query)
        if not words:
            return []
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT session_id,user_msg,tool_calls,result_summary,ts FROM episodes ORDER BY ts DESC LIMIT 50"
            ).fetchall()
        scored = []
        for r in rows:
            text = f"{r[1]} {r[3]}"
            score = sum(1 for w in words if w in text)
            if score > 0:
                scored.append({"session_id": r[0], "user_msg": r[1], "tool_calls": r[2], "summary": r[3], "ts": r[4], "score": score})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    def save_fact(self, key: str, value: str, source: str = "agent"):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("INSERT OR REPLACE INTO facts(key,value,source,ts) VALUES(?,?,?,?)",
                         (key, value[:2000], source, time.time()))

    def recall_facts(self, query: str = "", limit: int = 5) -> list[dict]:
        words = re.findall(r"[\u4e00-\u9fff\w]{2,}", query)
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute("SELECT key,value,source FROM facts").fetchall()
        results = []
        for r in rows:
            score = sum(2 if w in r[0] else (1 if w in r[1] else 0) for w in words)
            if score > 0:
                results.append({"key": r[0], "value": r[1], "source": r[2], "score": score})
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    def save_procedure(self, trigger: str, tool_seq: list):
        seq_str = json.dumps(tool_seq, ensure_ascii=False)
        with sqlite3.connect(str(self.db_path)) as conn:
            existing = conn.execute("SELECT id,success_count FROM procedures WHERE trigger_pattern=?", (trigger,)).fetchone()
            if existing:
                conn.execute("UPDATE procedures SET success_count=success_count+1,ts=? WHERE id=?", (time.time(), existing[0]))
            else:
                conn.execute("INSERT INTO procedures(trigger_pattern,tool_sequence,ts) VALUES(?,?,?)", (trigger, seq_str, time.time()))

    def recall_procedures(self, query: str = "", limit: int = 3) -> list[dict]:
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute("SELECT trigger_pattern,tool_sequence,success_count FROM procedures ORDER BY success_count DESC LIMIT 20").fetchall()
        scored = []
        for r in rows:
            pattern_words = re.findall(r"[\u4e00-\u9fff\w]{2,}", r[0])
            score = sum(1 for w in pattern_words if w in query)
            if score > 0:
                scored.append({"trigger": r[0], "tools": r[1], "success": r[2], "score": score})
        scored.sort(key=lambda x: -x["score"])
        return scored[:limit]


memory = MemoryStore()


class ConversationStore:
    def __init__(self):
        self.db_path = DATA_DIR / "conversations.db"
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT DEFAULT '', created_at REAL, updated_at REAL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER, role TEXT, content TEXT,
                    html TEXT DEFAULT '', tool_name TEXT DEFAULT '',
                    tool_result TEXT DEFAULT '', ts REAL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id)
                );
            """)

    def create_conversation(self, title: str = "") -> int:
        now = time.time()
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute("INSERT INTO conversations(title,created_at,updated_at) VALUES(?,?,?)", (title or "新对话", now, now))
            return cursor.lastrowid

    def save_message(self, conv_id: int, role: str, content: str, html: str = "", tool_name: str = "", tool_result: str = ""):
        now = time.time()
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("INSERT INTO messages(conversation_id,role,content,html,tool_name,tool_result,ts) VALUES(?,?,?,?,?,?,?)",
                         (conv_id, role, content[:8000], html[:2000], tool_name, tool_result[:2000], now))
            conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conv_id))

    def get_messages(self, conv_id: int, limit: int = 50) -> list[dict]:
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute("SELECT role,content,html,tool_name,tool_result,ts FROM messages WHERE conversation_id=? ORDER BY ts ASC LIMIT ?", (conv_id, limit)).fetchall()
        return [{"role": r[0], "content": r[1], "html": r[2], "tool_name": r[3], "tool_result": r[4], "ts": r[5]} for r in rows]

    def list_conversations(self, limit: int = 20) -> list[dict]:
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute("SELECT id,title,created_at,updated_at FROM conversations ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": r[0], "title": r[1], "created_at": r[2], "updated_at": r[3]} for r in rows]

    def delete_conversation(self, conv_id: int):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("DELETE FROM messages WHERE conversation_id=?", (conv_id,))
            conn.execute("DELETE FROM conversations WHERE id=?", (conv_id,))

    def get_or_create(self, conv_id: int | None = None) -> int:
        if conv_id:
            with sqlite3.connect(str(self.db_path)) as conn:
                r = conn.execute("SELECT id FROM conversations WHERE id=?", (conv_id,)).fetchone()
                if r:
                    return r[0]
        return self.create_conversation()


conversations = ConversationStore()
