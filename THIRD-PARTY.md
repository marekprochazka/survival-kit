# Third-party code shipped with survival-kit

Besides NixOS packages (each with its own licence, see nixpkgs), survival-kit ships these
files directly. Each is pinned by version and hash and fetched by Nix at build time; the
licence texts are installed next to them.

| What | Version | Licence | Used in | Source |
|---|---|---|---|---|
| marked (`lib/marked.umd.js`) | 18.1.2 | MIT | chat page: Markdown → HTML | https://registry.npmjs.org/marked/-/marked-18.1.2.tgz |
| DOMPurify (`dist/purify.js`) | 3.4.17 | MPL-2.0 OR Apache-2.0 | chat page: cleans that HTML | https://registry.npmjs.org/dompurify/-/dompurify-3.4.17.tgz |

On the box: the chat service's static directory (`marked.js`, `purify.js`,
`licenses/marked-LICENSE`, `licenses/dompurify-LICENSE`). To update: bump the version and the
hash in `modules/services/chat/default.nix` (`nix store prefetch-file <url>`) and this table.
