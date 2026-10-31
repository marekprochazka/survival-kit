# Language (translator, dictionary, thesaurus)

`modules/services/language/` (service + page) and `modules/services/content/app/langfiles.py`
(names and checks, shared with the content manager) — `https://language.deck`, both profiles.
A Python program on `127.0.0.1:8340` behind nginx: translate (Argos Translate models),
dictionary (dictd files), thesaurus (Moby). ADR-0007.

## Content: two kinds

| Kind (folder) | File | Stored as | Checked by |
|---|---|---|---|
| `translate/` | an Argos package, `translate-<from>_<to>-<version>.argosmodel` | `<from>_<to>.argosmodel` (one per direction) | `langfiles.check_model`: a zip with `metadata.json` (`from_code`, `to_code`, names), `model/model.bin` and `sentencepiece.model` or `bpe.model`; no unsafe paths, ≤ 2 GiB unpacked; the pair must match the name |
| `dict/` | a FreeDict dictd archive, `freedict-<name>-<version>.dictd.tar.xz` | `<name>.dictd.tar.xz` | `langfiles.check_dict`: one `.index` (≤ 32 MB) + one `.dict`/`.dict.dz` (≤ 512 MB unpacked), index lines parse and point inside the data; title from `00-database-short`. Read as a stream (xz with a 128 MB memory cap): a small crafted archive can't fill the memory of the root content manager |

Both go through the usual machinery ([Storage](storage.html)): on any location, the library
index (`library/translate/`, `library/dict/`), newer duplicate wins, invalid files marked,
auto-resolve, the content manager's *Languages* section. A dictionary stays **one file** —
the archive as published; only the service unpacks it.

## The service

`app/server.py` — `Catalog` + a small JSON API (`/api/languages`, `/api/translate`,
`/api/define`, `/api/synonyms`); the page is `app/static/` + the dashboard's `style.css`.

- **What is installed** = the built-ins (`survivalKit.services.language.builtinDir`) and the
  library index; a library file of a built-in's name replaces it. One file that can't be
  used — broken, gone, a damaged cache folder (removed and unpacked again), anything else —
  is left out and logged; it never takes the rest down. The catalog is rebuilt on
  the next request when the index changes (library.py swaps a symlink) or a file is gone (a
  drive pulled out) — no restart. A file that can't be used is left out and logged
  (`journalctl -u survival-kit-language`).
- **Unpacking** (`archives.py`): each file once into `/var/cache/survival-kit-language/<key>/`
  (key = real path + size + time; `.done` marks a finished folder). Models keep
  `metadata.json`, `model/`, the tokenizer and `info.json`; dictionaries become `dict.index` +
  `dict.dict` (`.dz` decompressed — entries are read by offset). Folders no longer in use are
  removed.
- **Translate** (`translate.py`): text → paragraphs (blank lines) → sentences (after `. ! ? …`
  unless the next word starts with a small letter — scripts without capitals split too —,
  after `。！？`, and at line breaks; a sentence over 400 characters is cut at a comma or a
  space, because a model silently cuts off what is much longer) → tokens → CTranslate2 (CPU,
  beam 4) → text. Two tokenizer kinds, as in argostranslate 1.11:
  - **SentencePiece** (`sentencepiece.model`, older packages);
  - **Moses + BPE** (`bpe.model`, the OPUS-MT 1.9.x packages incl. the built-in en↔cs):
    `sacremoses` normalizes and tokenizes, Argos's `apply_bpe.py` (subword-nmt, MIT — copied
    at build time from `python3Packages.argostranslate.src`, not the package itself) splits
    words; `@@ ` joins them again, Moses detokenizes.

  No argostranslate/LibreTranslate: they pull in PyTorch, spaCy and Stanza (GBs). A pair
  without a model goes **through English** when both halves exist (`/api/languages` →
  `targets` and `direct`). One translation at a time (a lock); at most 5 000 characters.
  Models load on first use; at most **two** stay in memory (enough for a translation
  through English), the one used longest ago is unloaded (`translate.Loaded`, under
  `MemoryHigh=1G`). The lock and that count belong to the catalog, so a rebuild during a long
  translation doesn't start a second one.
- **Dictionary** (`dictd.py`): the index in memory (WordNet: ~147 000 words), case and outer
  spaces ignored; no match → words that start the same.
- **Thesaurus** (`thesaurus.py`): Moby's 25 MB file, only the line offsets in memory.

Confined: `DynamicUser`, `ProtectSystem=strict`, writes only its cache. No access log —
what people look up stays theirs.

## Built-ins

`default.nix` pins, by hash: Argos `translate-en_cs-1_9_6` and `translate-cs_en-1_9_6`
(argos-net.com; OPUS-MT, CC-BY 4.0) and the Moby Thesaurus (Project Gutenberg 3202, public
domain). WordNet comes from nixpkgs (`dictdDBs.wordnet`) and is packed at build time into
the same `.dictd.tar.xz` form as an import. To update a model: change the URL and hash
(`nix store prefetch-file <url>`). Python: `ctranslate2`, `sentencepiece`, `sacremoses` from
nixpkgs. Together ≈ +480 MB unpacked on the system (2026-10-31).

## Testing

Unit tests (`checks/language-unit.nix`): `test_words` (unpacking, dictionary, thesaurus),
`test_translate` (splitting, both tokenizers with a stand-in model, routes, limits),
`test_server` (catalog, API); the content side in `test_langfiles` (content-unit). Eval:
`checks/eval-language.nix` (registry, profiles, confinement, no PyTorch). VM test
`checks/language.nix`: the real models translate en ↔ cs, WordNet and Moby answer, a
dictionary and a model imported through the content manager, confinement, reboot.
