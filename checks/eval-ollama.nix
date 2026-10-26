# Layer 2 — eval assertions: Ollama (local AI, full profile), offline and loopback-only.
{ pkgs, self, ... }:
let
  inherit (pkgs) lib;
  cfg = self.nixosConfigurations.survival-kit.config;
  ol = cfg.services.ollama;
in
assert lib.assertMsg ol.enable "ollama must be enabled (dev default: full profile)";
assert lib.assertMsg (
  ol.host == "127.0.0.1" && ol.port == 11434
) "ollama listens on 127.0.0.1:11434 only";
assert lib.assertMsg (ol.loadModels == [ ]) "nothing may pull models at boot (offline box)";
assert lib.assertMsg (
  !(cfg.survivalKit.registry ? ollama)
) "no web page yet → no registry entry, tile or certificate name";
assert lib.assertMsg (lib.any (
  p: lib.getName p == "ollama"
) cfg.environment.systemPackages) "the ollama CLI must be installed";
pkgs.runCommand "eval-ollama" { } "touch $out"
