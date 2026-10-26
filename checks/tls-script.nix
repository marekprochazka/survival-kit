# Layer 2 — the TLS script (openssl only, in the build sandbox): creates the CA and
# site certificate once, keeps them, re-issues the site certificate when names change
# or key and certificate don't match — and never replaces the CA.
{ pkgs, ... }:
pkgs.runCommand "tls-script" { nativeBuildInputs = [ pkgs.openssl ]; } ''
  run() {
    TLS_DIR=$PWD/tls CA_SUBJECT="test CA" PERMITTED="deck .deck box.local" NAMES="$1" KEY_GROUP=$(id -gn) \
      bash -euo pipefail ${../modules/tls/tls.sh}
  }
  fail() { echo "FAIL: $*"; exit 1; }

  res=$(run "deck wiki.deck box.local")
  grep -q "created a new certificate authority" <<<"$res" || fail "CA not created"
  grep -q "issued the site certificate" <<<"$res" || fail "site cert not issued"
  openssl verify -CAfile tls/ca.crt tls/deck.crt >/dev/null || fail "chain"
  ca=$(sha256sum < tls/ca.crt)

  res=$(run "deck wiki.deck box.local")
  [[ -z $res ]] || fail "second run should change nothing: $res"

  res=$(run "deck wiki.deck vault.deck box.local")
  grep -q "issued the site certificate" <<<"$res" || fail "new name must re-issue"
  openssl x509 -in tls/deck.crt -noout -ext subjectAltName | grep -q "DNS:vault.deck" || fail "vault.deck missing"
  [[ $(sha256sum < tls/ca.crt) == "$ca" ]] || fail "CA must never change"

  openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out tls/deck.key 2>/dev/null
  res=$(run "deck wiki.deck vault.deck box.local")
  grep -q "issued the site certificate" <<<"$res" || fail "mismatched key must re-issue"

  [[ $(stat -c %a tls/ca.key) == 600 ]] || fail "the CA key must be 0600"
  [[ $(stat -c '%a %G' tls/deck.key) == "640 $(id -gn)" ]] || fail "the site key must be 0640, group KEY_GROUP"
  # (find, not a glob: the build environment sets nullglob)
  [[ -z $(find tls -maxdepth 1 -name '.work.*') ]] || fail "temp dir left behind"
  touch $out
''
