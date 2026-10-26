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
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, model TEXT NOT NULL,
  created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, chat INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
  role TEXT NOT NULL, content TEXT NOT NULL, sources TEXT NOT NULL DEFAULT '[]',
  notice INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, chat INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
  question TEXT NOT NULL, question_msg INTEGER NOT NULL, model TEXT NOT NULL, state TEXT NOT NULL,
  text TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT '', error TEXT,
  created REAL NOT NULL);
"""
# AUTOINCREMENT: ids are never reused — a deleted chat's still-running answer can't land in a
# new chat that happens to get the same id.
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

    # every statement, *including reading its rows*, happens under the lock: the connection is
    # shared by the server threads and the worker, and a cursor read outside it sees garbage
    def _q(self, sql, *args):
        with self.lock:
            cur = self.db.execute(sql, args)
            return cur.lastrowid, cur.rowcount

    def _all(self, sql, *args):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def _one(self, sql, *args):
        with self.lock:
            row = self.db.execute(sql, args).fetchone()
            return dict(row) if row else None

    # --- chats --------------------------------------------------------------------

    def chats(self):
        return self._all("SELECT * FROM chats ORDER BY updated DESC, id DESC")

    def chat(self, chat_id):
        return self._one("SELECT * FROM chats WHERE id = ?", chat_id)

    def create_chat(self, model):
        now = time.time()
        return self._q(
            "INSERT INTO chats (title, model, created, updated) VALUES (?, ?, ?, ?)", NEW_TITLE, model, now, now
        )[0]

    def rename(self, chat_id, title):
        self._q("UPDATE chats SET title = ? WHERE id = ?", title.strip()[:TITLE_CHARS] or NEW_TITLE, chat_id)

    def delete(self, chat_id):
        self._q("DELETE FROM chats WHERE id = ?", chat_id)  # messages + jobs cascade

    def messages(self, chat_id, before=None):
        """A chat's messages; with `before`, only those older than that message id."""
        rows = self._all(
            "SELECT * FROM messages WHERE chat = ? AND id < ? ORDER BY id", chat_id, before if before else 2**62
        )
        for m in rows:
            m["sources"] = json.loads(m["sources"])
            m["notice"] = bool(m["notice"])
        return rows

    def _add_message(self, chat_id, role, content, sources=(), notice=False):
        now = time.time()
        msg = self._q(
            "INSERT INTO messages (chat, role, content, sources, notice, created) VALUES (?, ?, ?, ?, ?, ?)",
            chat_id, role, content, json.dumps(list(sources)), int(notice), now,
        )[0]
        self._q("UPDATE chats SET updated = ? WHERE id = ?", now, chat_id)
        return msg

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
            msg = self._add_message(chat_id, "user", question)
            return self._q(
                "INSERT INTO jobs (chat, question, question_msg, model, state, created)"
                " VALUES (?, ?, ?, ?, 'queued', ?)",
                chat_id, question, msg, model, time.time(),
            )[0]

    def job(self, job_id):
        return self._one("SELECT * FROM jobs WHERE id = ?", job_id)

    def open_job(self, chat_id):
        return self._one(
            "SELECT * FROM jobs WHERE chat = ? AND state IN ('queued', 'running') ORDER BY id DESC LIMIT 1", chat_id
        )

    def last_failed_job(self, chat_id):
        """The chat's newest job if it failed or was cancelled (so a reloaded page can say why)."""
        job = self._one("SELECT * FROM jobs WHERE chat = ? ORDER BY id DESC LIMIT 1", chat_id)
        return job if job and job["state"] in ("failed", "cancelled") else None

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
        """False if the job is gone (its chat was deleted meanwhile)."""
        with self.lock:
            job = self.job(job_id)
            if job is None:
                return False
            self._add_message(job["chat"], "assistant", answer, sources, notice)
            self._q("UPDATE jobs SET state = 'done', text = ? WHERE id = ?", answer, job_id)
            return True

    def fail(self, job_id, message):
        self._q("UPDATE jobs SET state = 'failed', error = ? WHERE id = ?", message, job_id)

    def cancel(self, job_id):
        """Only a waiting question can be cancelled (a running answer finishes)."""
        return self._q("UPDATE jobs SET state = 'cancelled' WHERE id = ? AND state = 'queued'", job_id)[1] == 1

    def recover(self):
        """After a restart: the answer that was running is lost; waiting ones go on."""
        self._q("UPDATE jobs SET state = 'failed', error = 'interrupted — ask again' WHERE state = 'running'")
