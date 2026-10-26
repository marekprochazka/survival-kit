# Layer 2 — the chat's Python code (stdlib unittest, no VM): storage, the one-at-a-time
# queue, the wiki-first answer pipeline and the HTTP/event API, with stand-ins for the
# lookup service and the model.
{ pkgs, ... }:
pkgs.runCommand "chat-unit" { nativeBuildInputs = [ pkgs.python3 ]; } ''
  cp -r ${../modules/services/chat/app} app
  chmod -R u+w app
  cd app
  python3 -m unittest -v test_chat 2>&1
  touch $out
''
