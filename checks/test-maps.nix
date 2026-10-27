# Tiny stand-in maps (one empty tile each) for tests, so no check needs the real built-in
# maps from `utils/fetch-maps` — only the ISO and a real system build do.
{ pkgs }:
rec {
  mkTestMap =
    name: zoom: box:
    pkgs.runCommand "${name}.pmtiles" { } ''
      ${pkgs.python3}/bin/python3 ${../modules/services/content/app/pmtiles_fixture.py} $out ${toString zoom} ${box}
    '';
  czechia = mkTestMap "czechia" 12 "12.0,48.5,18.9,51.1";
  austria = mkTestMap "austria" 12 "9.5,46.4,17.2,49.0";
  # a module: the built-in maps → stand-ins
  module.survivalKit.services.maps.builtins = {
    world = mkTestMap "world" 5 "-180,-85,180,85";
    inherit czechia;
  };
}
