"""Tests for the chat's storage, queue and worker (store.py, worker.py) — stand-ins for lookup/model."""

import tempfile
import threading
import time
import unittest
from pathlib import Path

import store
import worker

ARTICLE = {"title": "Burn", "book": "med", "url": "https://wiki.deck/content/med/Burn", "text": "Cool the burn."}


def make_store():
    return store.Store(Path(tempfile.mkdtemp()) / "chats.db")


class FakeModel:
    """Streams a scripted reply; `answer` for the wiki prompt, `fallback` for the other one."""

    def __init__(self, answer="Cool it under water [Burn].", fallback="Probably cool it."):
        self.answer, self.fallback = answer, fallback
        self.calls = []

    def __call__(self, model, messages):
        self.calls.append(messages)
        wiki = "ONLY the wiki articles" in messages[0]["content"]  # the article prompt
        reply = self.answer if wiki else self.fallback
        if isinstance(reply, Exception):
            raise reply
        for i in range(0, len(reply), 4):  # small chunks, like tokens
            yield reply[i : i + 4]


class Rig:
    def __init__(self, lookup_result=None, model=None, models=("m",), lookup_raises=False):
        self.store = make_store()
        self.model = model or FakeModel()
        self.events = []
        self.lookups = []

        def lookup_call(question, model, history):
            self.lookups.append((question, history))
            if lookup_raises:
                raise OSError("lookup service down")
            return lookup_result if lookup_result is not None else {
                "plan": {"books": ["med"], "words": "burn"}, "hits": [{}], "articles": [ARTICLE], "error": None}

        self.worker = worker.Worker(self.store, lookup_call, self.model, lambda: list(models),
                                    on_event=lambda j, k, d: self.events.append((j, k, d)))

    def ask(self, question="How do I treat a burn?", model="m"):
        chat = self.store.create_chat(model)
        return chat, self.store.ask(chat, question, model)


class StoreTest(unittest.TestCase):
    def test_store_roundtrip(self):
        s = make_store()
        chat = s.create_chat("m")
        job = s.ask(chat, "How do I treat a burn on my hand quickly and safely at home?", "m")
        [c] = s.chats()
        self.assertEqual(c["title"], "How do I treat a burn on my hand quickly and safely at home?"[:60])
        s.rename(chat, "Burns")
        self.assertEqual(s.chats()[0]["title"], "Burns")
        self.assertEqual(s.job(job)["state"], "queued")
        self.assertEqual([m["role"] for m in s.messages(chat)], ["user"])
        s.delete(chat)
        self.assertEqual(s.chats(), [])
        self.assertIsNone(s.job(job))

    def test_queue_one_at_a_time_fifo(self):
        s = make_store()
        a = s.ask(s.create_chat("m"), "first", "m")
        b = s.ask(s.create_chat("m"), "second", "m")
        self.assertEqual((s.queue_position(a), s.queue_position(b)), (0, 1))
        self.assertEqual(s.next_job()["id"], a)
        self.assertIsNone(s.next_job())  # one running → nothing else starts
        s.finish(a, "done", [], False)
        self.assertEqual(s.next_job()["id"], b)

    def test_cancel_queued_only(self):
        s = make_store()
        a = s.ask(s.create_chat("m"), "first", "m")
        b = s.ask(s.create_chat("m"), "second", "m")
        s.next_job()
        self.assertFalse(s.cancel(a))  # running
        self.assertTrue(s.cancel(b))
        self.assertEqual(s.job(b)["state"], "cancelled")

    def test_recover_marks_running_failed(self):
        s = make_store()
        a = s.ask(s.create_chat("m"), "first", "m")
        b = s.ask(s.create_chat("m"), "second", "m")
        s.next_job()
        s.recover()
        self.assertEqual((s.job(a)["state"], s.job(a)["error"]), ("failed", "interrupted — ask again"))
        self.assertEqual(s.job(b)["state"], "queued")

    def test_concurrent_reads_are_consistent(self):
        s = make_store()
        chat = s.create_chat("m")
        job = s.ask(chat, "q", "m")
        s.next_job()
        errors, stop = [], threading.Event()

        def read():
            while not stop.is_set():
                try:
                    if s.job(job) is None:
                        errors.append("job vanished")
                    for m in s.messages(chat):
                        m["sources"]
                    s.chats()
                except Exception as e:  # noqa: BLE001
                    errors.append(repr(e))

        readers = [threading.Thread(target=read) for _ in range(4)]
        for t in readers:
            t.start()
        for i in range(3000):
            s.append_text(job, "x")
        stop.set()
        for t in readers:
            t.join()
        self.assertEqual(errors[:3], [])

    def test_ids_never_reused(self):
        s = make_store()
        chat = s.create_chat("m")
        job = s.ask(chat, "q", "m")
        s.delete(chat)
        chat2 = s.create_chat("m")
        self.assertNotEqual(chat2, chat)
        self.assertNotEqual(s.ask(chat2, "q2", "m"), job)

    def test_text_saved_while_streaming(self):
        s = make_store()
        a = s.ask(s.create_chat("m"), "q", "m")
        s.next_job()
        s.append_text(a, "Cool ")
        s.append_text(a, "it")
        self.assertEqual(s.job(a)["text"], "Cool it")


class WorkerTest(unittest.TestCase):
    def test_answer_with_sources(self):
        r = Rig()
        chat, job = r.ask()
        self.assertTrue(r.worker.run_one())
        [_, answer] = r.store.messages(chat)
        self.assertEqual(answer["content"], "Cool it under water [Burn].")
        self.assertEqual(answer["sources"], [{"title": "Burn", "url": ARTICLE["url"]}])
        self.assertFalse(answer["notice"])
        self.assertIn("Cool the burn.", r.model.calls[0][0]["content"])  # the article is in the prompt
        kinds = [k for j, k, d in r.events]
        self.assertEqual(kinds[-1], "done")
        self.assertIn("status", kinds)

    def test_marker_triggers_fallback_with_notice(self):
        r = Rig(model=FakeModel(answer="NOT_IN_WIKI", fallback="Probably cool it."))
        chat, job = r.ask()
        r.worker.run_one()
        answer = r.store.messages(chat)[-1]
        self.assertTrue(answer["notice"])
        self.assertTrue(answer["content"].startswith(worker.NOTICE))
        self.assertIn("Probably cool it.", answer["content"])
        self.assertNotIn("NOT_IN_WIKI", answer["content"])
        self.assertEqual(answer["sources"], [])
        self.assertFalse(any(k == "token" and "NOT_IN" in d for j, k, d in r.events))  # never shown

    def test_no_hits_fallback(self):
        r = Rig(lookup_result={"plan": {"books": ["med"], "words": "x"}, "hits": [], "articles": [], "error": None})
        chat, _ = r.ask("What is the capital of Mars?")
        r.worker.run_one()
        self.assertTrue(r.store.messages(chat)[-1]["notice"])
        self.assertEqual(len(r.model.calls), 1)  # straight to the fallback

    def test_lookup_failure_falls_back(self):
        r = Rig(lookup_raises=True)
        chat, job = r.ask()
        r.worker.run_one()
        self.assertEqual(r.store.job(job)["state"], "done")
        self.assertTrue(r.store.messages(chat)[-1]["notice"])

    def test_marker_only_at_start(self):
        r = Rig(model=FakeModel(answer="Cool it. (Unlike NOT_IN_WIKI cases, this is covered.)"))
        chat, _ = r.ask()
        r.worker.run_one()
        answer = r.store.messages(chat)[-1]
        self.assertFalse(answer["notice"])
        self.assertIn("NOT_IN_WIKI cases", answer["content"])
        r2 = Rig(model=FakeModel(answer="  NOT_IN_WIKI."))
        chat2, _ = r2.ask()
        r2.worker.run_one()
        self.assertTrue(r2.store.messages(chat2)[-1]["notice"])

    def test_empty_answer_reported(self):
        r = Rig(model=FakeModel(answer="   ", fallback=""))
        chat, job = r.ask()
        r.worker.run_one()
        self.assertEqual(r.store.job(job)["state"], "failed")
        self.assertIn("empty", r.store.job(job)["error"])
        self.assertEqual([m["role"] for m in r.store.messages(chat)], ["user"])

    def test_job_failure_does_not_stop_queue(self):
        r = Rig(models=("other",))  # the chosen model was deleted while the question waited
        _, a = r.ask()
        r.store.ask(r.store.create_chat("other"), "second", "other")
        r.worker.run_one()
        self.assertEqual(r.store.job(a)["state"], "failed")
        self.assertIn("not on this box", r.store.job(a)["error"])
        self.assertTrue(r.worker.run_one())  # the next one still runs
        r3 = Rig(model=FakeModel(answer=OSError("ollama down")))
        _, c = r3.ask()
        r3.worker.run_one()
        self.assertEqual(r3.store.job(c)["state"], "failed")

    def test_history_trimmed_to_budget(self):
        r = Rig()
        chat = r.store.create_chat("m")
        for i in range(10):
            j = r.store.ask(chat, f"question {i} " + "x" * 2000, "m")
            r.store.next_job()
            r.store.finish(j, f"answer {i}", [], False)
        r.store.ask(chat, "y" * 20000, "m")  # a huge question
        r.worker.run_one()
        msgs = r.model.calls[-1]
        history = msgs[1:-1]
        self.assertLessEqual(len(history), worker.HISTORY_MESSAGES)
        self.assertLessEqual(sum(len(m["content"]) for m in history), worker.HISTORY_CHARS)
        self.assertLessEqual(len(msgs[-1]["content"]), worker.QUESTION_CHARS)
        self.assertEqual(msgs[-2]["content"], "answer 9")  # the most recent context is kept

    def test_deleted_chat_stops_its_answer(self):
        r = Rig()
        chat, job = r.ask()
        chunks = []

        def model(model, messages):
            yield "Cool it under the tap, "
            r.store.delete(chat)  # someone deletes the chat mid-answer
            for _ in range(50):
                chunks.append(1)
                yield "more "

        r.worker.model_stream = model
        chat2 = r.store.create_chat("m")
        job2 = r.store.ask(chat2, "other question", "m")
        self.assertTrue(r.worker.run_one())
        self.assertLess(len(chunks), 3)  # stopped right away, not after the whole answer
        self.assertIsNone(r.store.job(job))
        self.assertEqual(r.store.job(job2)["state"], "queued")
        self.assertEqual([m["role"] for m in r.store.messages(chat2)], ["user"])

    def test_followup_history_while_pending(self):
        r = Rig()
        chat = r.store.create_chat("m")
        r.store.ask(chat, "Q1", "m")
        r.store.ask(chat, "Q2", "m")  # asked before the first answer exists
        r.worker.run_one()
        self.assertEqual([m["content"] for m in r.model.calls[0][1:]], ["Q1"])  # no duplicate, no Q2
        r.worker.run_one()
        second = [m["content"] for m in r.model.calls[1][1:]]
        self.assertEqual(second, ["Q1", "Cool it under water [Burn].", "Q2"])

    def test_lookup_gets_trimmed_question(self):
        r = Rig()
        r.ask("z " * 20000)
        r.worker.run_one()
        self.assertLessEqual(len(r.lookups[0][0]), worker.QUESTION_CHARS)

    def test_wrapped_marker(self):
        for reply in ["**NOT_IN_WIKI**", "`NOT_IN_WIKI`", '"NOT_IN_WIKI"']:
            with self.subTest(reply=reply):
                r = Rig(model=FakeModel(answer=reply))
                chat, _ = r.ask()
                r.worker.run_one()
                self.assertTrue(r.store.messages(chat)[-1]["notice"])

    def test_loop_runs_until_stopped(self):
        r = Rig()
        chat, job = r.ask()
        stop = threading.Event()
        t = threading.Thread(target=r.worker.loop, args=(stop,), daemon=True)
        t.start()
        for _ in range(100):
            if r.store.job(job)["state"] == "done":
                break
            time.sleep(0.05)
        stop.set()
        r.worker.wake()
        t.join(2)
        self.assertEqual(r.store.job(job)["state"], "done")


if __name__ == "__main__":
    unittest.main()
