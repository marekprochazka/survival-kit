// Chat page: the chat list, the conversation, and following an answer as it is written.
// The model's Markdown is rendered with marked and then cleaned with DOMPurify before it
// becomes HTML (no scripts, images, forms, styles); only links into this box stay clickable.
// Everything else (questions, titles, status) is inserted as text (textContent).
"use strict";

const $ = (id) => document.getElementById(id);
let current = null; // the open chat's id
let follow = null; // the EventSource of the answer being followed

async function api(method, url, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(url, opts);
  let data = {};
  try { data = await r.json(); } catch (_) { /* e.g. an HTML error page */ }
  if (!r.ok) throw new Error(data.error || `the box answered ${r.status}`);
  return data;
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function day(t) {
  return new Date(t * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

async function loadModels() {
  const { models } = await api("GET", "/api/models");
  const select = $("model");
  select.textContent = "";
  for (const m of models) select.appendChild(el("option", "", m)).value = m;
  if (!models.length) {
    const p = el("p", "error", "No AI model on this box yet — add one under ");
    const a = el("a", "", "Content");
    a.href = "https://content.deck";
    p.append(a, ".");
    $("messages").replaceChildren(p);
    $("ask").hidden = true;
  }
  return models;
}

async function loadChats() {
  const chats = await api("GET", "/api/chats");
  const nav = $("chats");
  nav.textContent = "";
  for (const c of chats) {
    const b = el("button", "chat-item", c.title);
    b.appendChild(el("small", "", day(c.updated)));
    if (c.id === current) b.setAttribute("aria-current", "true");
    b.addEventListener("click", () => openChat(c.id));
    nav.appendChild(b);
  }
}

// the box's own domain ("deck" from "chat.deck") — links there work offline, others don't
const BOX = location.hostname.replace(/^[^.]+\./, "");

function renderMarkdown(container, text) {
  const html = marked.parse(text, { gfm: true, breaks: true });
  container.innerHTML = DOMPurify.sanitize(html, {
    FORBID_TAGS: ["img", "style", "form", "input", "button", "iframe", "video", "audio", "svg", "math"],
    FORBID_ATTR: ["style"],
  });
  for (const a of container.querySelectorAll("a")) {
    const href = a.getAttribute("href") || "";
    let local = false;
    try {
      const u = new URL(href, location.href);
      local = /^https?:$/.test(u.protocol) && (u.hostname === BOX || u.hostname.endsWith("." + BOX));
    } catch (_) { /* not a URL */ }
    if (local) {
      a.target = "_blank";
      a.rel = "noopener";
    } else { // off-box (made up, or unreachable offline): show it, don't link it
      const span = el("span", "offline-link", href && href !== a.textContent ? `${a.textContent} (${href})` : a.textContent);
      a.replaceWith(span);
    }
  }
}

function sourcesBlock(sources) {
  const div = el("div", "sources", "Sources: ");
  for (const s of sources) {
    if (!/^https?:\/\//.test(s.url)) continue; // only real links
    const a = el("a", "", s.title);
    a.href = s.url;
    a.target = "_blank";
    div.appendChild(a);
  }
  return div;
}

function showMessage(m) {
  const div = el("div", `msg ${m.role}${m.notice ? " notice" : ""}`);
  if (m.role === "assistant") renderMarkdown(div, m.content);
  else div.textContent = m.content; // your own question: plain text
  if (m.sources && m.sources.length) div.appendChild(sourcesBlock(m.sources));
  $("messages").appendChild(div);
  return div;
}

async function openChat(id) {
  if (follow) { follow.close(); follow = null; }
  current = id;
  const { chat, messages, job } = await api("GET", `/api/chats/${id}`);
  $("title").textContent = chat.title;
  $("rename").hidden = $("delete").hidden = false;
  if ([...$("model").options].some((o) => o.value === chat.model)) $("model").value = chat.model;
  $("messages").replaceChildren();
  messages.forEach(showMessage);
  if (job && (job.state === "failed" || job.state === "cancelled")) {
    $("messages").appendChild(el("p", "status error", `No answer: ${job.error || job.state}`));
  }
  const open = job && (job.state === "queued" || job.state === "running");
  setAsking(!open); // one open question per chat: follow-ups wait until it is answered
  if (open) followJob(job.id);
  loadChats();
}

function setAsking(on) {
  $("question").disabled = !on;
  $("ask").querySelector("button").disabled = !on;
  $("question").placeholder = on ? "Ask something…" : "Wait for the answer to finish…";
}

// follow one answer: replay (text so far) first, then live events
function followJob(jobId) {
  const box = $("messages");
  const status = el("p", "status", "Waiting…");
  const answer = el("div", "msg assistant", "");
  const cancel = el("button", "", "Cancel");
  cancel.hidden = true;
  cancel.addEventListener("click", () => api("DELETE", `/api/jobs/${jobId}`).catch(() => {}));
  box.append(status, cancel, answer);
  let text = "";
  const src = new EventSource(`/api/jobs/${jobId}/events`);
  follow = src;
  const show = () => { renderMarkdown(answer, text); box.scrollTop = box.scrollHeight; };
  const waiting = (n) => {
    status.textContent = `Waiting — another answer is being written${n > 1 ? ` (${n - 1} more ahead)` : ""}.`;
    cancel.hidden = false;
  };
  src.addEventListener("replay", (e) => {
    const r = JSON.parse(e.data);
    text = r.text;
    show();
    if (r.state === "queued") waiting(r.position);
    else if (r.status) status.textContent = r.status;
  });
  src.addEventListener("queue", (e) => waiting(JSON.parse(e.data).position));
  src.addEventListener("status", (e) => {
    cancel.hidden = true;
    status.textContent = JSON.parse(e.data).text;
  });
  src.addEventListener("token", (e) => {
    const t = JSON.parse(e.data);
    const start = t.end - t.text.length;
    if (t.end > text.length) text += t.text.slice(Math.max(text.length - start, 0)); // skip what we have
    show();
  });
  src.addEventListener("done", () => { src.close(); follow = null; openChat(current); });
  src.addEventListener("error", (e) => {
    if (!e.data) {
      // a dropped connection: EventSource reconnects by itself — unless the server refused
      if (src.readyState !== EventSource.CLOSED) return;
      follow = null;
      status.className = "status error";
      status.textContent = "Connection lost — reload the page to see the answer.";
      return;
    }
    src.close();
    follow = null;
    cancel.remove();
    status.className = "status error";
    status.textContent = `No answer: ${JSON.parse(e.data).error}`;
    setAsking(true);
  });
}

$("ask").addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = $("question").value.trim();
  if (!question) return;
  const model = $("model").value;
  try {
    if (current === null) current = (await api("POST", "/api/chats", { model })).id;
    const { job } = await api("POST", `/api/chats/${current}/ask`, { question, model });
    $("question").value = "";
    await openChat(current);
    if (!follow) followJob(job);
  } catch (err) {
    $("messages").appendChild(el("p", "error", err.message));
  }
});

$("question").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("ask").requestSubmit(); }
});

$("new").addEventListener("click", () => {
  if (follow) { follow.close(); follow = null; }
  current = null;
  $("title").textContent = "New chat";
  $("rename").hidden = $("delete").hidden = true;
  $("messages").replaceChildren(el("p", "empty", "Ask anything. The box looks in its wiki first."));
  loadChats();
});

$("rename").addEventListener("click", async () => {
  const title = prompt("Name for this chat:", $("title").textContent);
  if (title === null) return;
  await api("PATCH", `/api/chats/${current}`, { title });
  openChat(current);
});

$("delete").addEventListener("click", async () => {
  if (!confirm(`Delete "${$("title").textContent}"?`)) return;
  await api("DELETE", `/api/chats/${current}`);
  $("new").click();
});

loadModels().then(() => loadChats()).catch((err) => $("messages").appendChild(el("p", "error", err.message)));
