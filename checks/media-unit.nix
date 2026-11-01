# Layer 2 — the Media setup helper (stdlib unittest, no VM): Jellyfin's one-time setup
# against a fake Jellyfin (request shapes captured from a real 10.11.11).
{ pkgs, ... }:
pkgs.runCommand "media-unit" { nativeBuildInputs = [ pkgs.python3 ]; } ''
  cp -r ${../modules/services/media/app} app
  chmod -R u+w app
  cd app
  python3 -m unittest -v test_setup 2>&1
  touch $out
''
