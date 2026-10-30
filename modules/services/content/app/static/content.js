// Content manager page: imports (one upload per file, with progress), deletes, drives and
// auto-resolve. The lists themselves are rendered by the server, so viewing works without
// this script.
"use strict";

const log = document.getElementById("log");
const saveTo = document.getElementById("save-to");

function say(text, isError) {
  const p = document.createElement("p");
  p.textContent = text;
  if (isError) p.className = "error";
  log.appendChild(p);
  return p;
}

async function api(method, url) {
  const r = await fetch(url, { method });
  let body = {};
  try { body = await r.json(); } catch (_) { /* e.g. nginx's own HTML error page */ }
  if (!r.ok) throw new Error(body.error || `the box answered ${r.status} ${r.statusText}`.trim());
  return body;
}

// "book.zim" → "book", "czechia.pmtiles" → "czechia"
const title = (name) => name.replace(/\.(zim|pmtiles)$/, "");

// the chosen place for books and maps (models always go to this device)
const where = () => saveTo.options[saveTo.selectedIndex].textContent.replace(/ \(.*\)$/, "");

// one file: ask the box first (name, clash, space), confirm a replacement, then upload
async function importOne(kind, file, model) {
  const q = new URLSearchParams({ kind, file: file.name, size: file.size });
  if (model) q.set("model", model);
  if (kind !== "model") q.set("to", saveTo.value);
  const check = await api("GET", "/api/check?" + q);
  const noun = kind === "map" ? "map" : "book";
  if (check.exists === "import" && !confirm(
    `"${title(check.name)}" is already on this box. Replace it with this file` +
    (kind === "model" ? "?" : ` (saved to ${where()})?`))) {
    return say(`${file.name}: skipped`);
  }
  if (check.exists === "builtin" && !confirm(
    `"${title(check.name)}" came with the box. Replace the built-in ${noun} with this file?\n` +
    "Deleting the import later brings the built-in back.")) {
    return say(`${file.name}: skipped`);
  }
  const line = say(`${file.name}: uploading…`);
  const bar = document.createElement("progress");
  bar.max = file.size;
  line.appendChild(bar);
  q.delete("size");
  let result;
  try {
    result = await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("PUT", "/api/upload?" + q);
      xhr.upload.onprogress = (e) => { bar.value = e.loaded; };
      xhr.upload.onload = () => { line.firstChild.textContent = `${file.name}: adding…`; };
      xhr.onload = () => {
        let body = {};
        try { body = JSON.parse(xhr.responseText); } catch (_) { /* keep empty */ }
        xhr.status === 200 ? resolve(body) : reject(new Error(body.error || xhr.statusText));
      };
      xhr.onerror = () => reject(new Error("the connection was lost; nothing was imported"));
      xhr.send(file);
    });
  } catch (e) {
    line.remove(); // the "uploading/adding…" line and its bar; the caller shows the error
    throw e;
  }
  bar.remove();
  line.textContent = `${file.name}: ${result.result} as "${title(result.name)}"` +
    (kind === "model" ? "" : ` on ${where()}`);
  if (result.note) say(`${file.name}: note — ${result.note}`);
}

async function importFiles(input) {
  const kind = input.dataset.import;
  let files = Array.from(input.files);
  if (kind === "wiki") {
    const skipped = files.filter((f) => !/\.zim$/i.test(f.name));
    files = files.filter((f) => /\.zim$/i.test(f.name));
    if (skipped.length) say(`skipped (not .zim): ${skipped.map((f) => f.name).join(", ")}`);
  }
  for (const file of files) {
    let model;
    if (kind === "model") {
      const suggested = file.name.replace(/\.gguf$/i, "").toLowerCase().replace(/[^a-z0-9._-]+/g, "-");
      model = prompt("Name for this model:", suggested);
      if (model === null) { say(`${file.name}: skipped`); continue; }
    }
    try {
      await importOne(kind, file, model);
    } catch (e) {
      say(`${file.name}: ${e.message}`, true);
    }
  }
  input.value = "";
  say("Done. Reload the page to see the updated lists.");
}

// a button's action: confirm first where it matters, then reload the page
function onClick(selector, action) {
  document.querySelectorAll(selector).forEach((button) => {
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        if (await action(button.dataset) !== false) location.reload();
      } catch (e) {
        say(e.message, true);
      }
      button.disabled = false;
    });
  });
}

document.querySelectorAll("input[data-import]").forEach((input) => {
  input.addEventListener("change", () => importFiles(input));
});

onClick("button[data-delete]", async ({ delete: kind, name, at, file }) => {
  if (!confirm(`Delete "${title(name)}"` + (at ? "" : " from this box") + "?")) return false;
  const q = new URLSearchParams();
  if (at) q.set("at", at);
  if (file) q.set("file", file);
  await api("DELETE", `/api/${kind}/${encodeURIComponent(name)}?` + q);
});

onClick("button[data-action=add]", async ({ drive, name }) => {
  const chosen = prompt("Name for this drive:", name);
  if (chosen === null) return false;
  say(`${chosen}: adding…`);
  const r = await api("POST", "/api/drives/add?" + new URLSearchParams({ uuid: drive, name: chosen }));
  if (!r.mounted) {
    say(`${r.name}: added, but it can't be used: ${r.error}`, true);
    return false;
  }
});

onClick("button[data-action=reconnect]", async ({ drive }) => {
  const r = await api("POST", `/api/drives/${encodeURIComponent(drive)}/reconnect`);
  if (!r.mounted) {
    say(`still not available: ${r.error}`, true);
    return false;
  }
});

onClick("button[data-action=forget]", async ({ drive, name }) => {
  if (!confirm(`Stop using "${name}"?\nIts books and maps disappear from the box; the files stay on the drive.`)) {
    return false;
  }
  await api("POST", `/api/drives/${encodeURIComponent(drive)}/forget`);
});

onClick("button[data-resolve]", async ({ resolve: at, count }) => {
  if (!confirm(`Move ${count} file(s) that are not in use into a "set-aside" folder?\nNothing is deleted.`)) {
    return false;
  }
  const r = await api("POST", "/api/resolve?" + new URLSearchParams({ at }));
  say(`moved aside: ${r.moved.join(", ")}`);
});
