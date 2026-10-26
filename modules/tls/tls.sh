# survival-kit-tls — the box's own certificate authority (CA) + the site certificate.
# Runs at every boot before nginx.
#   CA:   created once, never replaced automatically (that would break trust).
#   site: re-issued when missing, when the wanted names changed, when it isn't valid
#         for the current clock, or when key and certificate don't belong together.
# Inputs (prepended by the module): TLS_DIR, CA_SUBJECT, PERMITTED, NAMES, KEY_GROUP
# (PERMITTED/NAMES are space-separated DNS names; KEY_GROUP may read deck.key, "" = root only).

install -d -m 0755 "$TLS_DIR"
umask 077 # everything created from here on is root-only unless chmod'ed
work=$(mktemp -d "$TLS_DIR/.work.XXXXXX")
trap 'rm -rf "$work"' EXIT
# wide validity: old machines often boot with a wrong clock (dead CMOS battery)
validity=(-not_before 20000101000000Z -not_after 21000101000000Z)

# --- the CA ---------------------------------------------------------------------
if [[ ! -s $TLS_DIR/ca.key || ! -s $TLS_DIR/ca.crt ]]; then
  # name constraints: this CA can only vouch for our own names, never e.g. a bank
  constraints=""
  for n in $PERMITTED; do constraints+="permitted;DNS:$n,"; done
  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes \
    -keyout "$work/ca.key" -out "$work/ca.crt" -subj "/CN=$CA_SUBJECT" "${validity[@]}" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "nameConstraints=critical,${constraints%,}"
  chmod 0644 "$work/ca.crt"
  mv "$work/ca.key" "$TLS_DIR/ca.key"
  mv "$work/ca.crt" "$TLS_DIR/ca.crt"
  rm -f "$TLS_DIR/deck.crt" # a new CA needs a new site certificate
  echo "survival-kit-tls: created a new certificate authority"
fi

# --- the site certificate ---------------------------------------------------------
want=""
for n in $NAMES; do want+="DNS:$n,"; done
want=${want%,}

site_ok() {
  [[ -s $TLS_DIR/deck.crt && -s $TLS_DIR/deck.key ]] || return 1
  # names as issued (openssl prints them in issue order)
  [[ $(openssl x509 -in "$TLS_DIR/deck.crt" -noout -ext subjectAltName | tail -n 1 | tr -d ' ') == "$want" ]] || return 1
  # chain + validity for the current clock
  openssl verify -CAfile "$TLS_DIR/ca.crt" "$TLS_DIR/deck.crt" >/dev/null 2>&1 || return 1
  # key and certificate belong together (a power cut between the two moves)
  [[ $(openssl x509 -in "$TLS_DIR/deck.crt" -noout -pubkey) == "$(openssl pkey -in "$TLS_DIR/deck.key" -pubout)" ]]
}

if ! site_ok; then
  openssl req -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes \
    -keyout "$work/deck.key" -out "$work/deck.csr" -subj "/CN=${NAMES%% *}"
  printf 'subjectAltName=%s\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\n' \
    "$want" >"$work/ext"
  openssl x509 -req -in "$work/deck.csr" -CA "$TLS_DIR/ca.crt" -CAkey "$TLS_DIR/ca.key" \
    -out "$work/deck.crt" -extfile "$work/ext" "${validity[@]}"
  chmod 0644 "$work/deck.crt"
  mv "$work/deck.key" "$TLS_DIR/deck.key"
  mv "$work/deck.crt" "$TLS_DIR/deck.crt"
  echo "survival-kit-tls: issued the site certificate for: $NAMES"
fi

# the web server runs unprivileged and must read the site key (not the CA key);
# set on every run, so wrong ownership repairs itself
if [[ -n $KEY_GROUP ]]; then
  chgrp "$KEY_GROUP" "$TLS_DIR/deck.key"
  chmod 0640 "$TLS_DIR/deck.key"
fi
