// Content manager page: imports (one upload per file, with progress) and deletes.
// The lists themselves are rendered by the server, so viewing works without this script.
"use strict";

const log = document.getElementById("log");

function say(text, isError) {
  const p = document.createElement("p");
  p.textContent = text;
  if (isError) p.className = "error";
  log.appendChild(p);
  return p;
}

async function api(method, url) {
  const r = await fetch(url, { method });
  const body = await r.json();
  if (!r.ok) throw new Error(body.error || r.statusText);
  return body;
}

// one file: ask the box first (name, clash, space), confirm a replacement, then upload
async function importOne(kind, file, model) {
  const q = new URLSearchParams({ kind, file: file.name, size: file.size });
  if (model) q.set("model", model);
  const check = await api("GET", "/api/check?" + q);
  const title = check.name.replace(/\.zim$/, "");
  if (check.exists === "import" && !confirm(`"${title}" is already on this box. Replace it?`)) {
    return say(`${file.name}: skipped`);
  }
  if (check.exists === "builtin" && !confirm(
    `"${title}" came with the box. Replace the built-in book with this file?\n` +
    "Deleting the import later brings the built-in back.")) {
    return say(`${file.name}: skipped`);
  }
  const line = say(`${file.name}: uploading…`);
  const bar = document.createElement("progress");
  bar.max = file.size;
  line.appendChild(bar);
  q.delete("size");
  const result = await new Promise((resolve, reject) => {
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
  bar.remove();
  line.textContent = `${file.name}: ${result.result} as "${result.name.replace(/\.zim$/, "")}"`;
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

document.querySelectorAll("input[data-import]").forEach((input) => {
  input.addEventListener("change", () => importFiles(input));
});

document.querySelectorAll("button[data-delete]").forEach((button) => {
  button.addEventListener("click", async () => {
    const { delete: kind, name } = button.dataset;
    const title = name.replace(/\.zim$/, "");
    if (!confirm(`Delete "${title}" from this box?`)) return;
    try {
      await api("DELETE", `/api/${kind}/${encodeURIComponent(name)}`);
      location.reload();
    } catch (e) {
      say(`${title}: ${e.message}`, true);
    }
  });
});
