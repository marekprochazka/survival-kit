// survival-kit Language page: three tabs over the JSON API (server.py).
"use strict";

const $ = (id) => document.getElementById(id);
let info = { languages: [], targets: {}, dictionaries: [], thesaurus: false };

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(path, opts);
  let data = {};
  try { data = await r.json(); } catch (_) { /* keep empty */ }
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

// --- tabs -----------------------------------------------------------------------------

const tabs = Array.from(document.querySelectorAll('[role="tab"]'));

function select(tab) {
  for (const t of tabs) {
    const on = t === tab;
    t.setAttribute("aria-selected", on);
    t.tabIndex = on ? 0 : -1;
    $(t.getAttribute("aria-controls")).hidden = !on;
  }
  tab.focus();
}

tabs.forEach((t, i) => {
  t.addEventListener("click", () => select(t));
  t.addEventListener("keydown", (e) => {
    const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
    if (step) select(tabs[(i + step + tabs.length) % tabs.length]);
  });
});

// --- translate ------------------------------------------------------------------------

const nameOf = (code) => (info.languages.find((l) => l.code === code) || { name: code }).name;
const direct = (from, to) => (info.direct[from] || []).includes(to);

// names come from imported files: set as text, never as HTML
const option = (value, text) => Object.assign(document.createElement("option"), { value, textContent: text });

function fillTo(keep) {
  const from = $("from").value;
  $("to").replaceChildren(...(info.targets[from] || []).map((code) =>
    option(code, nameOf(code) + (direct(from, code) ? "" : " (via English)"))));
  if (keep && (info.targets[from] || []).includes(keep)) $("to").value = keep;
  $("swap").disabled = !(info.targets[$("to").value] || []).includes(from);
}

async function translate() {
  const text = $("source").value;
  if (!text.trim() || !$("to").value) return;
  $("go").disabled = true;
  $("state").className = "muted";
  $("state").textContent = "Translating…";
  try {
    const r = await api("POST", "/api/translate", { text, from: $("from").value, to: $("to").value });
    $("result").value = r.text;
    $("state").textContent = "";
  } catch (e) {
    $("state").className = "error";
    $("state").textContent = e.message;
  } finally {
    $("go").disabled = false;
  }
}

$("from").addEventListener("change", () => fillTo($("to").value));
$("to").addEventListener("change", () => {
  $("swap").disabled = !(info.targets[$("to").value] || []).includes($("from").value);
});
$("swap").addEventListener("click", () => {
  const from = $("from").value;
  $("from").value = $("to").value;
  fillTo(from);
  if ($("result").value) [$("source").value, $("result").value] = [$("result").value, ""];
});
$("go").addEventListener("click", translate);
$("source").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) translate();
});
$("copy").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("result").value);
    $("state").textContent = "Copied.";
  } catch (_) {
    $("result").select(); // older browsers / no permission: select it for Ctrl+C
  }
});

// --- dictionary and thesaurus ----------------------------------------------------------

function words(list, onPick) {
  const box = document.createElement("div");
  box.className = "words";
  for (const w of list) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = w;
    b.addEventListener("click", () => onPick(w));
    box.appendChild(b);
  }
  return box;
}

function show(out, nodes) {
  out.replaceChildren(...nodes);
}

function line(text, cls) {
  const p = document.createElement("p");
  p.textContent = text;
  if (cls) p.className = cls;
  return p;
}

async function define(word) {
  $("define-word").value = word;
  const out = $("define-out");
  if (!word.trim()) return;
  try {
    const q = new URLSearchParams({ dict: $("dict").value, word });
    const r = await api("GET", "/api/define?" + q);
    if (r.entries.length) {
      show(out, r.entries.map((t) => Object.assign(document.createElement("pre"), { className: "entry", textContent: t })));
    } else {
      show(out, [line(`"${word}" is not in this dictionary.`, "muted"),
        ...(r.near.length ? [line("Words that start the same:"), words(r.near, define)] : [])]);
    }
  } catch (e) {
    show(out, [line(e.message, "error")]);
  }
}

async function synonyms(word) {
  $("syn-word").value = word;
  const out = $("syn-out");
  if (!word.trim()) return;
  try {
    const r = await api("GET", "/api/synonyms?" + new URLSearchParams({ word }));
    if (r.words.length) {
      show(out, [line(`${r.words.length} words for "${word}":`, "muted"), words(r.words, synonyms)]);
    } else {
      show(out, [line(`No synonyms for "${word}".`, "muted"),
        ...(r.near.length ? [line("Words that start the same:"), words(r.near, synonyms)] : [])]);
    }
  } catch (e) {
    show(out, [line(e.message, "error")]);
  }
}

$("define-form").addEventListener("submit", (e) => { e.preventDefault(); define($("define-word").value); });
$("syn-form").addEventListener("submit", (e) => { e.preventDefault(); synonyms($("syn-word").value); });
$("dict").addEventListener("change", () => define($("define-word").value));

// --- start ----------------------------------------------------------------------------

(async () => {
  try {
    info = await api("GET", "/api/languages");
  } catch (e) {
    $("state").className = "error";
    $("state").textContent = `Can't reach the Language service: ${e.message}`;
    return;
  }
  const sources = info.languages.filter((l) => (info.targets[l.code] || []).length);
  $("from").replaceChildren(...sources.map((l) => option(l.code, l.name)));
  if (sources.some((l) => l.code === "en")) $("from").value = "en";
  fillTo("cs");
  if (!sources.length) $("state").textContent = "No translation models on this box.";
  $("dict").replaceChildren(...info.dictionaries.map((d) => option(d.id, d.title)));
  $("dict-label").hidden = info.dictionaries.length < 2;
  if (!info.dictionaries.length) show($("define-out"), [line("No dictionaries on this box.", "muted")]);
  if (!info.thesaurus) show($("syn-out"), [line("No thesaurus on this box.", "muted")]);
})();
