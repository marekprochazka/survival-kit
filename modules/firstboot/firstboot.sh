# First boot (ADR-0001 §7): set the owner's display name and password, once.
# Runs on tty1 before the desktop starts. The password is never echoed, stored
# or logged — it goes to chpasswd on stdin only.
marker=${FIRSTBOOT_MARKER:-/var/lib/survival-kit/firstboot-done}
# NixOS rewrites /etc/passwd at every boot; the module re-applies this file
namefile=${FIRSTBOOT_NAME_FILE:-/var/lib/survival-kit/display-name}

printf '\033c' # clear the console
cat <<'EOF'

  Welcome to survival-kit!
  This box is new. Two quick questions, then the desktop starts.

EOF

while true; do
  read -rp "Your name (shown on the desktop): " name
  # printable only (arrow keys/tab insert control characters on the console);
  # ':' and ',' would split the /etc/passwd name field
  [[ $name =~ ^[[:print:]]+$ && $name != *[:,]* ]] && break
  echo "Please type just your name (letters, spaces; no ':' or ',')."
done

while true; do
  # IFS= keeps leading/trailing spaces — the password is exactly what was typed
  IFS= read -rsp "Choose a password (for sudo and the text console): " pass1
  echo
  IFS= read -rsp "Repeat the password: " pass2
  echo
  [[ -n $pass1 && $pass1 == "$pass2" ]] && break
  echo "Empty or not matching — try again."
done

# The password matters most: set it (and the marker) first, so a problem with
# the name can never leave the account without a password.
printf '%s:%s\n' "$FIRSTBOOT_USER" "$pass1" | chpasswd
unset pass1 pass2
mkdir -p "$(dirname "$marker")"
touch "$marker"

printf '%s\n' "$name" >"$namefile"
if ! usermod -c "$name" "$FIRSTBOOT_USER"; then
  echo "Note: couldn't set the name shown on the desktop; everything else is done."
fi
echo
echo "Done. Starting the desktop…"
sleep 2
