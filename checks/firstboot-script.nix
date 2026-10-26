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

  echo "== Ctrl+C (SIGINT) during the prompt is ignored"
  rm -f "$CALLS" marker name
  mkfifo keys
  # background jobs start with SIGINT ignored; restore the default like a real tty would
  FIRSTBOOT_USER=deck FIRSTBOOT_MARKER=$PWD/marker FIRSTBOOT_NAME_FILE=$PWD/name \
    env --default-signal=INT bash -euo pipefail ${script} < keys >/dev/null 2>&1 &
  pid=$!
  exec 3>keys            # open the writer side so the prompt starts reading
  sleep 1
  kill -INT "$pid"
  sleep 1
  printf 'Name\npw\npw\n' >&3
  exec 3>&-
  wait "$pid"
  ${expect "chpasswd [deck:pw]"}

  echo "== Ctrl+D (end of input) re-asks, then gives up visibly without a marker"
  rm -f "$CALLS" marker name
  result=$(printf 'Name\n' | FIRSTBOOT_USER=deck FIRSTBOOT_MARKER=$PWD/marker FIRSTBOOT_NAME_FILE=$PWD/name \
    bash -euo pipefail ${script} 2>&1) && { echo "should have given up"; exit 1; }
  grep -q "giving up" <<<"$result" || { echo "no 'giving up' message"; echo "$result"; exit 1; }
  test ! -e marker || { echo "marker written without a password"; exit 1; }

  touch $out
''
