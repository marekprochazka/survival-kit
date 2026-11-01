# Layer 2 — the manual's map date comes from modules/services/maps/builtins.nix (one source,
# no hand copy): the built page shows it and no @MAPS_DATE@ placeholder is left anywhere.
{ pkgs, self, ... }:
let
  inherit (self.packages.${pkgs.stdenv.hostPlatform.system})
    survival-kit-manual
    survival-kit-devguide
    ;
in
pkgs.runCommand "manual-mapdate" { nativeBuildInputs = [ pkgs.zim-tools ]; } ''
  zimdump dump --dir=pages ${survival-kit-manual} >/dev/null
  page=$(find pages -name 'whats-on-this-box.html' | head -1)
  grep -q '2026-10-27' "$page" || { echo "map date missing in $page"; exit 1; }
  if grep -rq '@MAPS_DATE@' pages; then echo "placeholder left in the manual"; exit 1; fi
  # the developer guide explains the placeholder, so it must stay literal there
  zimdump dump --dir=dev ${survival-kit-devguide} >/dev/null
  grep -q '@MAPS_DATE@' "$(find dev -name 'maps.html' | head -1)" ||
    { echo "devguide maps page lost its @MAPS_DATE@ text"; exit 1; }
  touch $out
''
