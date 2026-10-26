"""survival-kit chat — the worker: answers one question at a time, wiki first (ADR-0005).

  1. lookup (book map → plan → search → read)  — the lookup service
  2. answer from the articles, citing them; the model replies NOT_IN_WIKI if they don't help
  3. otherwise (marker, no articles, wiki down): answer from the model's own knowledge,
     starting with the NOTICE
The first HOLD characters are held back so the marker is never shown.
"""

import threading

MARKER = "NOT_IN_WIKI"
NOTICE = "Not found in the wiki — this answer comes from the model's own training and may not be precise."
HOLD = 16
HISTORY_MESSAGES = 6
HISTORY_CHARS = 4000
QUESTION_CHARS = 2000

ANSWER_SYSTEM = """You are the assistant of an offline computer. Answer the user's question using ONLY the wiki articles below.
Be clear and practical. Mention the titles of the articles you used.
If the articles do not answer the question, reply with exactly {marker} and nothing else.

{articles}"""

FALLBACK_SYSTEM = """You are the assistant of an offline computer. Its offline wiki has nothing on this question, so answer from your own knowledge, briefly and carefully. Say so when you are unsure."""


class _Gone(Exception):
    """The job was deleted (its chat was) while being answered."""


def _starts_with_marker(text):
    # small models like to wrap it: **NOT_IN_WIKI**, `NOT_IN_WIKI`, "NOT_IN_WIKI"
    return text.lstrip(" \t\r\n*`\"'").startswith(MARKER)


def _cut(text, limit):
    """At most `limit` characters, cut on a word boundary (the "…" counts)."""
    if len(text) <= limit:
        return text
    return (text[: max(limit - 1, 0)].rsplit(" ", 1)[0] + "…") if limit > 1 else ""


def trim_history(messages):
    """The most recent messages that fit the budget (newest kept first)."""
    out, used = [], 0
    for m in reversed(messages[-HISTORY_MESSAGES:]):
        content = _cut(m["content"], HISTORY_CHARS - used)
        if used >= HISTORY_CHARS or not content:
            break
        out.append({"role": m["role"], "content": content})
        used += len(content)
    return list(reversed(out))


class Worker:
    """lookup_call(question, model, history) → {plan, hits, articles, error};
    model_stream(model, messages) → iterator of text chunks; models() → installed model names;
    on_event(job_id, kind, data) with kind in status | token | done | error."""

    def __init__(self, store, lookup_call, model_stream, models, on_event=lambda *a: None):
        self.store = store
        self.lookup_call = lookup_call
        self.model_stream = model_stream
        self.models = models
        self.on_event = on_event
        self._wake = threading.Event()

    def wake(self):
        """A new question arrived (or stop was requested)."""
        self._wake.set()

    def loop(self, stop):
        while not stop.is_set():
            if not self.run_one():
                self._wake.wait(5)
                self._wake.clear()

    def run_one(self):
        job = self.store.next_job()
        if job is None:
            return False
        try:
            self._answer(job)
        except _Gone:
            pass  # deleted mid-answer: stop, free the CPU for the next question
        except Exception as e:  # noqa: BLE001 — one failed answer must not stop the queue
            message = f"the answer failed: {e}"
            self.store.fail(job["id"], message)
            self.on_event(job["id"], "error", message)
        return True

    def _status(self, job_id, text):
        if self.store.job(job_id) is None:
            raise _Gone
        self.store.set_status(job_id, text)
        self.on_event(job_id, "status", text)

    def _emit(self, job_id, text):
        if self.store.job(job_id) is None:
            raise _Gone
        self.store.append_text(job_id, text)
        self.on_event(job_id, "token", text)

    def _stream(self, job_id, model, messages, hold):
        """Stream an answer to the page. With hold: return None if it starts with MARKER."""
        held, text, released = "", "", not hold
        for chunk in self.model_stream(model, messages):
            text += chunk
            if released:
                self._emit(job_id, chunk)
                continue
            held += chunk
            if _starts_with_marker(held):
                return None  # the articles don't answer it; stop reading
            if len(held.lstrip()) >= HOLD:
                released = True
                self._emit(job_id, held)
        if not released:
            if _starts_with_marker(held):
                return None
            if held:
                self._emit(job_id, held)
        return text

    def _answer(self, job):
        jid, model = job["id"], job["model"]
        if model not in self.models():
            raise RuntimeError(f"the model {model} is not on this box anymore (see Content)")
        # the conversation as context — without this question and without questions asked
        # after it (they may already be waiting); answers to earlier questions stay in
        qid = job["question_msg"]
        history = trim_history(
            [m for m in self.store.messages(job["chat"]) if m["id"] != qid and not (m["role"] == "user" and m["id"] > qid)]
        )
        asked = _cut(job["question"], QUESTION_CHARS)
        question = {"role": "user", "content": asked}

        self._status(jid, "Looking at the book map")
        try:
            found = self.lookup_call(asked, model, history)
        except Exception:  # noqa: BLE001 — no wiki → the model's own knowledge, with the notice
            found = {"plan": None, "articles": [], "error": "the wiki lookup is not available"}
        articles = found.get("articles") or []
        plan = found.get("plan")
        if plan:
            self._status(jid, f'Searching {", ".join(plan["books"])} for "{plan["words"]}"')

        answer, sources, notice = None, [], False
        if articles:
            self._status(jid, f"Reading {len(articles)} article{'s' if len(articles) > 1 else ''}")
            text = "\n\n".join(f"[{a['title']}]\n{a['text']}" for a in articles)
            system = ANSWER_SYSTEM.format(marker=MARKER, articles=text)
            self._status(jid, "Writing the answer")
            answer = self._stream(jid, model, [{"role": "system", "content": system}, *history, question], hold=True)
            sources = [{"title": a["title"], "url": a["url"]} for a in articles]
        if answer is None or not answer.strip():
            if answer is not None:  # the wiki answer came back empty
                raise RuntimeError("the model returned an empty answer")
            self.store.reset_text(jid)
            self._status(jid, "Not found in the wiki — answering from the model's own knowledge")
            self._emit(jid, NOTICE + "\n\n")
            body = self._stream(
                jid, model, [{"role": "system", "content": FALLBACK_SYSTEM}, *history, question], hold=False
            )
            if not body or not body.strip():
                raise RuntimeError("the model returned an empty answer")
            answer, sources, notice = NOTICE + "\n\n" + body.strip(), [], True

        if not self.store.finish(jid, answer.strip(), sources, notice):
            raise _Gone
        self.on_event(jid, "done", {"notice": notice, "sources": sources})
