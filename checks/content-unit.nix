# Layer 2 — the content manager's Python code (stdlib unittest, no VM): names, space
# checks, uploads, wiki/model handling and the HTTP API, with stand-ins for kiwix/ollama.
{ pkgs, ... }:
pkgs.runCommand "content-unit" { nativeBuildInputs = [ pkgs.python3 ]; } ''
  cp -r ${../modules/services/content/app} app
  chmod -R u+w app
  cd app
  python3 -m unittest -v test_content 2>&1
  touch $out
''
