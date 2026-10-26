# Layer 2 — the wiki lookup's Python code (stdlib unittest, no VM): Kiwix catalog/search/article
# parsing (fixtures captured from Kiwix 3.8.2), the lookup pipeline, the HTTP and MCP fronts.
{ pkgs, ... }:
pkgs.runCommand "lookup-unit" { nativeBuildInputs = [ pkgs.python3 ]; } ''
  cp -r ${../modules/services/lookup/app} app
  chmod -R u+w app
  cd app
  python3 -m unittest -v test_lookup test_fronts 2>&1
  touch $out
''
