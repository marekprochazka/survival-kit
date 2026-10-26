# First boot (ADR-0001 §7): set the owner's display name and password, once.
# Runs on tty1 before the desktop starts. The password is never echoed, stored
# or logged — it goes to chpasswd on stdin only.
marker=${FIRSTBOOT_MARKER:-/var/lib/survival-kit/firstboot-done}
# NixOS rewrites /etc/passwd at every boot; the module re-applies this file
namefile=${FIRSTBOOT_NAME_FILE:-/var/lib/survival-kit/display-name}

# Ctrl+C / Ctrl+\ / Ctrl+Z must not abort the setup half-way
trap '' INT QUIT TSTP

# ask [read options…] — read one answer into $REPLY, exactly as typed (read
# without a variable name never trims spaces). Ctrl+D (end of input) counts as an
# empty answer; three in a row → give up for now: no marker, so the prompt comes
# back at the next start.
eofs=0
ask() {
  if read -r "$@"; then
    eofs=0
    return 0
  fi
  REPLY=""
  echo
  eofs=$((eofs + 1))
  if ((eofs >= 3)); then
    echo "No input — giving up for now; you'll be asked again at the next start." >&2
    exit 1
  fi
}

printf '\033c' # clear the console
cat <<'EOF'

  Welcome to survival-kit!
  This box is new. Two quick questions, then the desktop starts.

EOF

while true; do
  ask -p "Your name (shown on the desktop): "
  name=$REPLY
  # printable only (arrow keys/tab insert control characters on the console);
  # ':' and ',' would split the /etc/passwd name field
  [[ $name =~ ^[[:print:]]+$ && $name != *[:,]* ]] && break
  echo "Please type just your name (letters, spaces; no ':' or ',')."
done

while true; do
  ask -s -p "Choose a password (for sudo and the text console): "
  pass1=$REPLY
  echo
  ask -s -p "Repeat the password: "
  pass2=$REPLY
  echo
  [[ -n $pass1 && $pass1 == "$pass2" ]] && break
  echo "Empty or not matching — try again."
done

# The password matters most: set it (and the marker) first, so a problem with
# the name can never leave the account without a password.
printf '%s:%s\n' "$FIRSTBOOT_USER" "$pass1" | chpasswd
unset pass1 pass2 REPLY
mkdir -p "$(dirname "$marker")"
touch "$marker"

printf '%s\n' "$name" >"$namefile"
if ! usermod -c "$name" "$FIRSTBOOT_USER"; then
  echo "Note: couldn't set the name shown on the desktop; everything else is done."
fi
echo
echo "Done. Starting the desktop…"
sleep 2
