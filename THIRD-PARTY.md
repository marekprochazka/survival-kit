# Third-party code shipped with survival-kit

Besides NixOS packages (each with its own licence, see nixpkgs), survival-kit ships these
files directly. Each is pinned by version and hash and fetched by Nix at build time; the
licence texts are installed next to them.

| What | Version | Licence | Used in | Source |
|---|---|---|---|---|
| marked (`lib/marked.umd.js`) | 18.1.2 | MIT | chat page: Markdown → HTML | https://registry.npmjs.org/marked/-/marked-18.1.2.tgz |
| DOMPurify (`dist/purify.js`) | 3.4.17 | MPL-2.0 OR Apache-2.0 | chat page: cleans that HTML | https://registry.npmjs.org/dompurify/-/dompurify-3.4.17.tgz |
| MapLibre GL JS (`dist/maplibre-gl*.mjs`, `.css`) | 6.14.0 | BSD-3-Clause | map page: draws the map | https://registry.npmjs.org/maplibre-gl/-/maplibre-gl-6.14.0.tgz |
| pmtiles (`dist/pmtiles.js`) | 4.5.0 | BSD-3-Clause | map page: reads `.pmtiles` by byte ranges | https://registry.npmjs.org/pmtiles/-/pmtiles-4.5.0.tgz (licence: PMTiles repo `aec8fa1`) |
| @protomaps/basemaps (`dist/basemaps.js`) | 5.7.2 | BSD-3-Clause | map page: the map style | https://registry.npmjs.org/@protomaps/basemaps/-/basemaps-5.7.2.tgz (licence: basemaps repo `42ffaaa`) |
| Protomaps basemaps-assets: fonts (Noto Sans) | `028c18f` | OFL-1.1 | map page: label glyphs | https://github.com/protomaps/basemaps-assets |
| Protomaps basemaps-assets: sprites v4 | `028c18f` | MIT (derived from tangrams/icons) | map page: map icons | https://github.com/protomaps/basemaps-assets |

On the box: the chat service's static directory (`marked.js`, `purify.js`,
`licenses/marked-LICENSE`, `licenses/dompurify-LICENSE`); the maps site (`vendor/`, `fonts/`,
`sprites/`, `licenses/`). To update: bump the version and the hash in
`modules/services/chat/default.nix` or `modules/services/maps/default.nix`
(`nix store prefetch-file <url>`) and this table.

## Language data and code

| What | Version | Licence | Used in | Source |
|---|---|---|---|---|
| Argos Translate models `translate-en_cs`, `translate-cs_en` (made from Helsinki-NLP **OPUS-MT** models) | 1.9.6 | CC-BY 4.0 | Language: built-in English ↔ Czech | https://argos-net.com/v1/translate-en_cs-1_9_6.argosmodel, …/translate-cs_en-1_9_6.argosmodel |
| Argos Translate `apply_bpe.py` (from subword-nmt, Rico Sennrich) | argostranslate 1.11.0 (nixpkgs source) | MIT | Language: BPE word splitting | https://github.com/argosopentech/argos-translate |
| WordNet (dictd database, nixpkgs `dictdDBs.wordnet`) | 542 | WordNet 3.0 licence (Princeton, permissive) | Language: English dictionary | https://wordnet.princeton.edu/ |
| Moby Thesaurus (Grady Ward) | Project Gutenberg #3202 | public domain | Language: thesaurus | https://www.gutenberg.org/files/3202/files/mthesaur.txt |

OPUS-MT: Jörg Tiedemann and Santhosh Thottingal, "OPUS-MT — Building open translation
services for the World", EAMT 2020; models © University of Helsinki, CC-BY 4.0. Imported
FreeDict dictionaries carry their own licences (mostly GPL), inside each archive.

## Map data

The built-in maps (`modules/services/maps/builtins.nix`) are cut from the Protomaps daily
planet build, made from **OpenStreetMap** data — © OpenStreetMap contributors, available
under the Open Database License (ODbL), <https://www.openstreetmap.org/copyright> — and
Natural Earth (public domain). The map page shows the attribution.
