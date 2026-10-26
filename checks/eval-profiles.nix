# Layer 2 — eval assertions: lite/full profiles set service defaults; hand overrides win.
{ pkgs, self, ... }:
let
  inherit (pkgs) lib;
  base = self.nixosConfigurations.survival-kit;
  cfg = base.config;
  withModules = modules: (base.extendModules { inherit modules; }).config;
  lite = withModules [ { survivalKit.profile = "lite"; } ];
  liteOllama = withModules [
    {
      survivalKit.profile = "lite";
      survivalKit.services.ollama.enable = true;
    }
  ];
  hasOllamaPkg = c: lib.any (p: lib.getName p == "ollama") c.environment.systemPackages;
  svc = c: c.survivalKit.services;
in
# no selection.nix (dev repo, and older installs without a profile line) → full
assert lib.assertMsg (cfg.survivalKit.profile == "full") "the dev repo default is full";
assert lib.assertMsg (
  (svc cfg).kiwix.enable && (svc cfg).vaultwarden.enable && (svc cfg).ollama.enable
) "full: wiki, passwords and ollama";
assert lib.assertMsg (
  (svc lite).kiwix.enable && (svc lite).vaultwarden.enable
) "lite: wiki and passwords";
assert lib.assertMsg (
  !lite.services.ollama.enable && !(hasOllamaPkg lite) && !(lite.systemd.services ? ollama)
) "lite: no ollama service, no ollama package";
assert lib.assertMsg (
  (svc lite).content.enable && lite.systemd.services.survival-kit-content.environment.OLLAMA == "0"
) "lite: the content manager is on, without the models section";
assert lib.assertMsg liteOllama.services.ollama.enable
  "a hand override (lite + ollama.enable = true) must win over the profile default";
pkgs.runCommand "eval-profiles" { } "touch $out"
