# Autostart (XDG): open the dashboard in Firefox, maximized.
# 1. Wait (≤120 s) for the dashboard to answer — autologin can beat nginx at boot,
#    and a slow first boot on old disks can take a while. Waiting costs nothing:
#    the alternative is Firefox stuck on "Unable to connect".
# 2. Start Firefox (its homepage is the dashboard, set by policy).
# 3. Firefox has no "start maximized" flag: wait (≤60 s) for its window and ask
#    the window manager to maximize it. On timeout just leave it as is.
url="${1:-https://deck}"
ca="${2:-/var/lib/survival-kit/tls/ca.crt}" # curl doesn't know the box's CA either

for _ in $(seq 1 120); do
  curl -sf --cacert "$ca" -o /dev/null "$url" && break
  sleep 1
done

firefox &

for _ in $(seq 1 120); do
  # match by window class (stable), not by title (changes with page and version)
  if wmctrl -lx | grep -q "Navigator.firefox"; then
    wmctrl -x -r Navigator.firefox -b add,maximized_vert,maximized_horz
    exit 0
  fi
  sleep 0.5
done
