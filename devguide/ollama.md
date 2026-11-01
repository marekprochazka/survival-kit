# Ollama (local AI)

`modules/services/ollama/` — local language models, **full profile only**
([Profiles](profiles.html)), via the nixpkgs `services.ollama` module.

- Listens on `127.0.0.1:11434` (the box only). CPU only — the target is an 8 GB, i5-class
  machine without a usable GPU (GPU support: `docs/todo`, later).
- Models live in `/var/lib/ollama/models` (the service runs as a systemd `DynamicUser`).
- `loadModels` stays empty: pulling models at boot needs internet. Models never ship in
  the image (2+ GB each); they come from external media as a **GGUF** file:

        printf 'FROM /path/to/model.gguf\n' > Modelfile
        ollama create <name> -f Modelfile

  The CLI uploads the file to the server, which stores it in its own blob store. A USB
  stick is mounted (under `/run/media/deck/<label>`) when first opened in the file manager
  (udisks2 + gvfs), not on plug-in — there is no thunar-volman automount.
  (The future importer — ADR-0004 — will automate this.)
- The `ollama` CLI is installed system-wide by the nixpkgs module and talks to `127.0.0.1:11434` by default:
  `ollama run/list/rm` work for `deck`.
- **Not in the registry:** Ollama has no web page of its own; the [Chat](chat.html) is its
  browser front end.
- Package: the CPU build, ~150 MB. Small models (3B, Q4, ~2 GB) answer at a few words per
  second on an i5; 7B models crawl.
- **Yields to the desktop:** Ollama runs in the top-level slice `background.slice` (defined in
  `modules/base`, shared with Jellyfin's scans), with `CPUWeight = 20`. A CPU weight only splits CPU among *siblings* in systemd's cgroup tree:
  at the top are `system.slice` (all services, 100), `user.slice` (the desktop session, 100)
  and now `background.slice` (20). Under contention the desktop gets about 100/120 ≈ 83 %
  against Ollama; with nothing else running, weights don't apply and Ollama uses every
  core. (Setting `CPUWeight` on the service itself would only weigh it against other
  services inside `system.slice`, not against Firefox.) Plus `Nice = 10` within its slice
  and the lowest best-effort disk priority. Not the `idle` class: an answer someone is
  waiting for must not stall. Check: `systemd-cgls`, `cat /sys/fs/cgroup/background.slice/cpu.weight`. Memory headroom comes from
  zram (see [Base](base.html)).
- Logs: `journalctl -u ollama`. API check: `curl http://127.0.0.1:11434/api/version`.
