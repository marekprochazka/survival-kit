# Layer 2 — the first-boot prompt script with scripted input and stand-ins for
# usermod/chpasswd (fast, no VM): input edge cases from the round-B review.
{ pkgs, ... }:
let
  inherit (pkgs) lib;
  script = ../modules/firstboot/firstboot.sh;
  # run the script like writeShellApplication does (errexit, nounset, pipefail)
  run = name: input: ''
    echo "== ${name}"
    rm -f "$CALLS" marker name
    printf ${lib.escapeShellArg input} \
      | FIRSTBOOT_USER=deck FIRSTBOOT_MARKER=$PWD/marker FIRSTBOOT_NAME_FILE=$PWD/name bash -euo pipefail ${script} >/dev/null 2>&1
  '';
  expect = line: ''
    grep -Fxq -- ${lib.escapeShellArg line} "$CALLS" || { echo "missing: ${line}"; cat "$CALLS"; exit 1; }
  '';
in
pkgs.runCommand "firstboot-script" { } ''
  mkdir bin
  cat > bin/usermod <<'EOF'
  #!/bin/sh
  # like shadow: refuses control characters; "Bad Name" simulates any other failure
  case "$2" in *[[:cntrl:]]* | "Bad Name") exit 1 ;; esac
  printf 'usermod %s\n' "$2" >> "$CALLS"
  EOF
  cat > bin/chpasswd <<'EOF'
  #!/bin/sh
  printf 'chpasswd [%s]\n' "$(cat)" >> "$CALLS"
  EOF
  chmod +x bin/*
  export PATH=$PWD/bin:$PATH CALLS=$PWD/calls

  ${run "arrow keys while typing the name are rejected" "Te\\x1b[Dst\\nTest Person\\npw\\npw\\n"}
  ${expect "usermod Test Person"}
  grep -Fxq "Test Person" name || { echo "display-name file not written"; exit 1; }

  ${run "password keeps leading/trailing spaces" "Name\\n pass word \\n pass word \\n"}
  ${expect "chpasswd [deck: pass word ]"}

  ${run "comma in the name (splits GECOS) is rejected" "Smith, John\\nJohn Smith\\npw\\npw\\n"}
  ${expect "usermod John Smith"}

  ${run "a failing name never costs the password" "Bad Name\\npw\\npw\\n"}
  ${expect "chpasswd [deck:pw]"}
  test -e marker || { echo "marker missing after name failure"; exit 1; }

  touch $out
''
