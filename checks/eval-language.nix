# Layer 2 — eval assertions: Language (translator, dictionary, thesaurus) — in the registry, on
# in both profiles, confined, its built-ins offered to the content manager, and no PyTorch.
{ pkgs, self, ... }:
let
  inherit (pkgs) lib;
  base = self.nixosConfigurations.survival-kit;
  cfg = base.config;
  lite = (base.extendModules { modules = [ { survivalKit.profile = "lite"; } ]; }).config;
  lang = cfg.survivalKit.services.language;
  reg = cfg.survivalKit.registry.language;
  svc = cfg.systemd.services.survival-kit-language;
  content = cfg.systemd.services.survival-kit-content.environment;
  modules = map (p: p.pname or p.name) (pkgs.python3Packages.requiredPythonModules lang.pythonLibs);
in
assert lib.assertMsg (
  reg.port == 8340 && reg.order == 13 && reg.healthPath == "/health" && reg.subdomain == "language"
) "Language: port 8340, health /health, after Chat on the dashboard";
assert lib.assertMsg (
  lang.enable && lite.survivalKit.services.language.enable
) "Language is on in both profiles";
assert lib.assertMsg (
  svc.serviceConfig.DynamicUser && svc.serviceConfig.ProtectSystem == "strict"
) "the Language service runs confined, as a dynamic user";
assert lib.assertMsg (
  content.LANGUAGE == "1"
  && content.TRANSLATE_BUILTINS_DIR == "${lang.builtinDir}/translate"
  && content.DICT_BUILTINS_DIR == "${lang.builtinDir}/dict"
) "the content manager lists the Language built-ins";
assert lib.assertMsg (
  lib.elem "ctranslate2" modules && lib.all (m: !(lib.hasInfix "torch" m)) modules
) "translation runs on CTranslate2 without PyTorch";
pkgs.runCommand "eval-language" { } "touch $out"
