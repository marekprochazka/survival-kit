"""survival-kit chat — storage (SQLite, stdlib sqlite3): chats, messages and the job queue.

A question becomes a job: queued → running → done / failed / cancelled. Only one job runs at
a time (the box has one CPU-bound model); the worker takes the oldest queued one. The answer
text is saved as it streams, so a reloaded page can show what's there so far.
"""

import json
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, model TEXT NOT NULL,
  created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY, chat INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
  role TEXT NOT NULL, content TEXT NOT NULL, sources TEXT NOT NULL DEFAULT '[]',
  notice INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY, chat INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
  question TEXT NOT NULL, model TEXT NOT NULL, state TEXT NOT NULL,
  text TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT '', error TEXT,
  created REAL NOT NULL);
"""
NEW_TITLE = "New chat"
TITLE_CHARS = 60
OPEN = ("queued", "running")


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()  # one connection, shared by the server threads and the worker
        with self.lock:
            self.db.execute("PRAGMA foreign_keys = ON")
            self.db.execute("PRAGMA journal_mode = WAL")  # survives power loss; readers don't block
            self.db.executescript(SCHEMA)

    def _q(self, sql, *args):
        with self.lock:
            return self.db.execute(sql, args)

    def _one(self, sql, *args):
        row = self._q(sql, *args).fetchone()
        return dict(row) if row else None

    # --- chats --------------------------------------------------------------------

    def chats(self):
        return [dict(r) for r in self._q("SELECT * FROM chats ORDER BY updated DESC, id DESC")]

    def chat(self, chat_id):
        return self._one("SELECT * FROM chats WHERE id = ?", chat_id)

    def create_chat(self, model):
        now = time.time()
        return self._q(
            "INSERT INTO chats (title, model, created, updated) VALUES (?, ?, ?, ?)", NEW_TITLE, model, now, now
        ).lastrowid

    def rename(self, chat_id, title):
        self._q("UPDATE chats SET title = ? WHERE id = ?", title.strip()[:TITLE_CHARS] or NEW_TITLE, chat_id)

    def delete(self, chat_id):
        self._q("DELETE FROM chats WHERE id = ?", chat_id)  # messages + jobs cascade

    def messages(self, chat_id):
        out = []
        for r in self._q("SELECT * FROM messages WHERE chat = ? ORDER BY id", chat_id):
            m = dict(r)
            m["sources"] = json.loads(m["sources"])
            m["notice"] = bool(m["notice"])
            out.append(m)
        return out

    def _add_message(self, chat_id, role, content, sources=(), notice=False):
        now = time.time()
        self._q(
            "INSERT INTO messages (chat, role, content, sources, notice, created) VALUES (?, ?, ?, ?, ?, ?)",
            chat_id, role, content, json.dumps(list(sources)), int(notice), now,
        )
        self._q("UPDATE chats SET updated = ? WHERE id = ?", now, chat_id)

    # --- jobs ---------------------------------------------------------------------

    def ask(self, chat_id, question, model):
        """Store the question and queue a job to answer it."""
        with self.lock:
            chat = self.chat(chat_id)
            if chat is None:
                raise KeyError(chat_id)
            if chat["title"] == NEW_TITLE:
                self._q("UPDATE chats SET title = ? WHERE id = ?", question.strip()[:TITLE_CHARS], chat_id)
            self._q("UPDATE chats SET model = ? WHERE id = ?", model, chat_id)
            self._add_message(chat_id, "user", question)
            return self._q(
                "INSERT INTO jobs (chat, question, model, state, created) VALUES (?, ?, ?, 'queued', ?)",
                chat_id, question, model, time.time(),
            ).lastrowid

    def job(self, job_id):
        return self._one("SELECT * FROM jobs WHERE id = ?", job_id)

    def open_job(self, chat_id):
        return self._one(
            "SELECT * FROM jobs WHERE chat = ? AND state IN ('queued', 'running') ORDER BY id DESC LIMIT 1", chat_id
        )

    def next_job(self):
        """The oldest queued job, now running — or None while another one runs."""
        with self.lock:
            if self._one("SELECT id FROM jobs WHERE state = 'running'"):
                return None
            job = self._one("SELECT * FROM jobs WHERE state = 'queued' ORDER BY id LIMIT 1")
            if job:
                self._q("UPDATE jobs SET state = 'running' WHERE id = ?", job["id"])
                job["state"] = "running"
            return job

    def queue_position(self, job_id):
        """0 = running or next; n = n questions ahead of it."""
        row = self._one(
            "SELECT COUNT(*) AS n FROM jobs WHERE state IN ('queued', 'running') AND id < ?", job_id
        )
        return row["n"]

    def set_status(self, job_id, status):
        self._q("UPDATE jobs SET status = ? WHERE id = ?", status, job_id)

    def append_text(self, job_id, text):
        self._q("UPDATE jobs SET text = text || ? WHERE id = ?", text, job_id)

    def reset_text(self, job_id, text=""):
        self._q("UPDATE jobs SET text = ? WHERE id = ?", text, job_id)

    def finish(self, job_id, answer, sources, notice):
        with self.lock:
            job = self.job(job_id)
            self._add_message(job["chat"], "assistant", answer, sources, notice)
            self._q("UPDATE jobs SET state = 'done', text = ? WHERE id = ?", answer, job_id)

    def fail(self, job_id, message):
        self._q("UPDATE jobs SET state = 'failed', error = ? WHERE id = ?", message, job_id)

    def cancel(self, job_id):
        """Only a waiting question can be cancelled (a running answer finishes)."""
        return self._q("UPDATE jobs SET state = 'cancelled' WHERE id = ? AND state = 'queued'", job_id).rowcount == 1

    def recover(self):
        """After a restart: the answer that was running is lost; waiting ones go on."""
        self._q("UPDATE jobs SET state = 'failed', error = 'interrupted — ask again' WHERE state = 'running'")
