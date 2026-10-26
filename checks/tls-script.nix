# Layer 2 — the TLS script (openssl only, in the build sandbox): creates the CA and
# site certificate once, keeps them, re-issues the site certificate when names change
# or key and certificate don't match — and replaces the CA only when the box's names
# (its name constraints) change.
{ pkgs, ... }:
pkgs.runCommand "tls-script" { nativeBuildInputs = [ pkgs.openssl ]; } ''
  run() {
    TLS_DIR=$PWD/tls CA_SUBJECT="test CA" PERMITTED="''${PERMITTED:-deck .deck box.local}" NAMES="$1" \
      KEY_GROUP=$(id -gn) RELOAD_UNIT="" bash -euo pipefail ${../modules/tls/tls.sh}
  }
  fail() { echo "FAIL: $*"; exit 1; }

  res=$(run "deck wiki.deck box.local")
  grep -q "created a new certificate authority" <<<"$res" || fail "CA not created"
  grep -q "issued the site certificate" <<<"$res" || fail "site cert not issued"
  openssl verify -CAfile tls/ca.crt tls/deck.crt >/dev/null || fail "chain"
  openssl x509 -in tls/deck.crt -noout -startdate | grep -q "1970" || fail "validity must start in 1970 (wrong clocks)"
  ca=$(sha256sum < tls/ca.crt)

  res=$(run "deck wiki.deck box.local")
  [[ -z $res ]] || fail "second run should change nothing: $res"

  res=$(run "deck wiki.deck vault.deck box.local")
  grep -q "issued the site certificate" <<<"$res" || fail "new name must re-issue"
  openssl x509 -in tls/deck.crt -noout -ext subjectAltName | grep -q "DNS:vault.deck" || fail "vault.deck missing"
  [[ $(sha256sum < tls/ca.crt) == "$ca" ]] || fail "a new service must not change the CA"

  openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out tls/deck.key 2>/dev/null
  res=$(run "deck wiki.deck vault.deck box.local")
  grep -q "issued the site certificate" <<<"$res" || fail "mismatched key must re-issue"

  # a power cut during an earlier run left a temp dir behind
  mkdir tls/.work.stale
  res=$(run "deck wiki.deck vault.deck box.local")
  [[ -z $res ]] || fail "a stale temp dir alone must change nothing: $res"

  [[ $(stat -c %a tls/ca.key) == 600 ]] || fail "the CA key must be 0600"
  [[ $(stat -c '%a %G' tls/deck.key) == "640 $(id -gn)" ]] || fail "the site key must be 0640, group KEY_GROUP"
  # (find, not a glob: the build environment sets nullglob)
  [[ -z $(find tls -maxdepth 1 -name '.work.*') ]] || fail "temp dirs left behind"

  # the box was renamed: the old CA may not vouch for lab.local → new CA, valid chain
  res=$(PERMITTED="deck .deck lab.local" run "deck wiki.deck vault.deck lab.local")
  grep -q "recreated the certificate authority" <<<"$res" || fail "rename must recreate the CA: $res"
  grep -q "issued the site certificate" <<<"$res" || fail "rename must re-issue the site cert"
  openssl verify -CAfile tls/ca.crt tls/deck.crt >/dev/null || fail "chain after rename"
  res=$(PERMITTED="deck .deck lab.local" run "deck wiki.deck vault.deck lab.local")
  [[ -z $res ]] || fail "after a rename, the next run should change nothing: $res"
  touch $out
''
