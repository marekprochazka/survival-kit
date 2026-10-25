# First boot (ADR-0001 §7): set the owner's display name and password, once.
# Runs on tty1 before the desktop starts. The password is never echoed, stored
# or logged — it goes to chpasswd on stdin only.
marker=/var/lib/survival-kit/firstboot-done

printf '\033c' # clear the console
cat <<'EOF'

  Welcome to survival-kit!
  This box is new. Two quick questions, then the desktop starts.

EOF

while true; do
  read -rp "Your name (shown on the desktop): " name
  [[ -n $name && $name != *:* ]] && break
  echo "Please type a name (without ':')."
done

while true; do
  read -rsp "Choose a password (for sudo and the text console): " pass1
  echo
  read -rsp "Repeat the password: " pass2
  echo
  [[ -n $pass1 && $pass1 == "$pass2" ]] && break
  echo "Empty or not matching — try again."
done

usermod -c "$name" "$FIRSTBOOT_USER"
printf '%s:%s\n' "$FIRSTBOOT_USER" "$pass1" | chpasswd
unset pass1 pass2

mkdir -p "$(dirname "$marker")"
touch "$marker"
echo
echo "Done. Starting the desktop…"
sleep 2
