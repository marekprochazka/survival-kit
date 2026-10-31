# Language at https://language.<domain>: translate (Argos Translate models run by CTranslate2 —
# no argostranslate package, no PyTorch), a dictionary (dictd files) and a thesaurus (Moby).
# Built in: English ↔ Czech, WordNet, Moby; more models and dictionaries are imported in the
# content manager (Languages section) and reach the service through the library index.
# A small Python program (./app) behind nginx; both profiles.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.survivalKit.services.language;
  storage = config.survivalKit.storage;
  port = 8340;
  # Argos's English ↔ Czech models (OPUS-MT, CC-BY 4.0; THIRD-PARTY.md) and the Moby Thesaurus
  # (public domain, Project Gutenberg 3202), pinned by hash
  enCs = pkgs.fetchurl {
    url = "https://argos-net.com/v1/translate-en_cs-1_9_6.argosmodel";
    hash = "sha256-8vW5P8Wlqjqmvs6Z4PqfgEh7uaLqTgw971jWpK83yB8=";
  };
  csEn = pkgs.fetchurl {
    url = "https://argos-net.com/v1/translate-cs_en-1_9_6.argosmodel";
    hash = "sha256-8Wg7GsXoJsfj2ysOpdcxkc3WldZSOxEjY9inaSA9y2I=";
  };
  moby = pkgs.fetchurl {
    url = "https://www.gutenberg.org/files/3202/files/mthesaur.txt";
    hash = "sha256-fJdCse2UQ1qJPAcZtCZyXtuKUkL4xSanVGG9bO4t/TI=";
  };
  # the built-ins in the same form as imports: WordNet packed like a FreeDict archive
  builtinFiles = pkgs.runCommand "language-builtins" { nativeBuildInputs = [ pkgs.xz ]; } ''
    mkdir -p $out/translate $out/dict wordnet
    cp ${enCs} $out/translate/en_cs.argosmodel
    cp ${csEn} $out/translate/cs_en.argosmodel
    cp ${moby} $out/moby.txt
    cp ${pkgs.dictdDBs.wordnet}/share/dictd/wn.index wordnet/wordnet.index
    cp ${pkgs.dictdDBs.wordnet}/share/dictd/wn.dict wordnet/wordnet.dict
    tar --sort=name --owner=0 --group=0 --numeric-owner --mtime=@1 -cJf $out/dict/wordnet.dictd.tar.xz wordnet
  '';
  # the app + the content manager's file checks + Argos's BPE code (MIT)
  app = pkgs.runCommand "language-app" { } ''
    mkdir $out
    cp ${./app}/*.py $out/
    rm $out/test_*.py
    cp ${../content/app/langfiles.py} ${../content/app/content.py} $out/
    cp ${pkgs.python3Packages.argostranslate.src}/argostranslate/apply_bpe.py $out/
  '';
  static = pkgs.runCommand "language-static" { } ''
    mkdir $out
    cp ${./app/static}/* $out/
    cp ${../../dashboard/style.css} $out/style.css
  '';
  pythonLibs = with pkgs.python3Packages; [
    ctranslate2
    sentencepiece
    sacremoses
  ];
  python = pkgs.python3.withPackages (_: pythonLibs);
in
{
  options.survivalKit.services.language = {
    enable = lib.mkEnableOption "Language (translator, dictionary, thesaurus)";
    builtinDir = lib.mkOption {
      type = lib.types.path;
      default = builtinFiles;
      readOnly = true;
      description = "The built-ins: translate/*.argosmodel, dict/*.dictd.tar.xz, moby.txt.";
    };
    pythonLibs = lib.mkOption {
      type = lib.types.listOf lib.types.package;
      default = pythonLibs;
      readOnly = true;
      internal = true; # the eval check looks at what they pull in
      description = "The Python libraries the service runs with.";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.services.survival-kit-language = {
      description = "survival-kit Language (translator, dictionary, thesaurus)";
      wantedBy = [ "multi-user.target" ];
      after = [ "survival-kit-library.service" ];
      environment = {
        LANGUAGE_PORT = toString port;
        LIBRARY_DIR = storage.libraryDir;
        BUILTINS_DIR = "${builtinFiles}";
        CACHE_DIR = "/var/cache/survival-kit-language";
        STATIC_DIR = "${static}";
        PYTHONUNBUFFERED = "1";
      };
      serviceConfig = {
        ExecStart = "${python}/bin/python3 ${app}/server.py";
        DynamicUser = true;
        CacheDirectory = "survival-kit-language"; # unpacked models and dictionaries
        Restart = "on-failure";
        MemoryHigh = "1G"; # two loaded models ≈ 300 MB; slow down rather than starve the box
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        NoNewPrivileges = true;
      };
    };

    survivalKit.registry.language = {
      subdomain = "language";
      inherit port;
      title = "Language";
      description = "Translate, look up words and synonyms";
      order = 13; # after Chat (12), before Passwords (15)
      healthPath = "/health";
    };

    # a long text can take a while on a slow CPU
    services.nginx.virtualHosts."language.${config.survivalKit.web.domain}".extraConfig = ''
      proxy_read_timeout 300s;
    '';
  };
}
