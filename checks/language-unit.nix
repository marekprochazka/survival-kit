# Layer 2 — the Language service's Python code (unittest, no VM): unpacking, the dictionary
# and thesaurus readers, the translation pipeline with a stand-in model, the HTTP API. Uses the
# content manager's langfiles.py and its fixture builders, and Argos's apply_bpe.py (as the
# service does).
{ pkgs, ... }:
let
  python = pkgs.python3.withPackages (ps: [
    ps.sacremoses
    ps.sentencepiece
  ]);
  content = ../modules/services/content/app;
in
pkgs.runCommand "language-unit" { nativeBuildInputs = [ python ]; } ''
  cp -r ${../modules/services/language/app} app
  chmod -R u+w app
  cp ${content}/langfiles.py ${content}/content.py ${content}/test_langfiles.py app/
  cp ${pkgs.python3Packages.argostranslate.src}/argostranslate/apply_bpe.py app/
  cd app
  python3 -m unittest -v test_words test_translate test_server 2>&1
  touch $out
''
