# Ollama — local AI models (full profile), used from the terminal: `ollama run <model>`.
# CPU only (target: ≥ 8 GB RAM, i5-class, no GPU). Models never ship in the image:
# they are copied in from external media (GGUF + `ollama create`; later the importer)
# and live in /var/lib/ollama/models. No web page yet → not in the registry (the
# browser chat brings its tile).
{ config, lib, ... }:
let
  cfg = config.survivalKit.services.ollama;
in
{
  options.survivalKit.services.ollama.enable = lib.mkEnableOption "Ollama local AI (CPU)";

  config = lib.mkIf cfg.enable {
    services.ollama = {
      enable = true;
      host = "127.0.0.1"; # only the box itself talks to it
      port = 11434;
      # loadModels stays empty: pulling at boot needs internet (offline box)
    };
    # the CLI; it talks to 127.0.0.1:11434 by default
    environment.systemPackages = [ config.services.ollama.package ];
  };
}
