# survival-kit-install — put survival-kit onto this machine's disk. No network needed.
# Steps: choose disk → encryption → confirm → prepare config → partition (disko)
#        → install (nixos-install) → hand the config over to /etc/nixos (git repo).

usage() {
  cat <<'EOF'
Usage: sudo survival-kit-install

Interactive installer. Erases ONE disk you choose and installs survival-kit on it.
The installed disk boots on both legacy-BIOS and UEFI machines.
EOF
}

if [[ ${1:-} == "--help" || ${1:-} == "-h" ]]; then
  usage
  exit 0
fi

step=0
announce() {
  step=$1
  echo
  echo "==> [$1/7] $2"
}
trap 'echo >&2; echo "!! Install failed at step $step. Re-run survival-kit-install to start over (the target disk is wiped again)." >&2' ERR

[[ $EUID -eq 0 ]] || {
  echo "Run as root: sudo survival-kit-install" >&2
  exit 1
}
[[ -f "$FLAKE_SRC/flake.nix" ]] || {
  echo "Bundled configuration missing at $FLAKE_SRC" >&2
  exit 1
}

cat <<'EOF'
survival-kit installer
This ERASES one disk you choose and installs survival-kit on it.
No network needed. Press Ctrl+C at any prompt to abort.
EOF

announce 1 "Choose the target disk"
candidates=()
while read -r name type; do
  [[ $type == disk ]] || continue
  [[ $name == loop* || $name == sr* || $name == zram* ]] && continue
  # skip disks with anything mounted — e.g. the USB stick we booted from
  if lsblk -nro MOUNTPOINTS "/dev/$name" | grep -q .; then continue; fi
  candidates+=("$name")
done < <(lsblk -dnro NAME,TYPE)
if ((${#candidates[@]} == 0)); then
  echo "No usable disk found (all disks are in use or none attached)." >&2
  exit 1
fi
lsblk -do NAME,SIZE,MODEL,TRAN "${candidates[@]/#//dev/}"
read -rp "Disk to install to (e.g. ${candidates[0]}): " disk
printf '%s\n' "${candidates[@]}" | grep -qx -- "$disk" || {
  echo "'$disk' is not one of the listed disks." >&2
  exit 1
}
device="/dev/$disk"

announce 2 "Encryption"
read -rp "Encrypt the disk? A passphrase is then needed at every boot. [y/N] " answer
encrypt=false
if [[ $answer == [yY]* ]]; then
  encrypt=true
  while true; do
    read -rsp "Passphrase: " password
    echo
    read -rsp "Repeat passphrase: " password2
    echo
    [[ -n $password && $password == "$password2" ]] && break
    echo "Empty or not matching — try again."
  done
  export password # read by disko's LUKS step; never written to disk
fi

announce 3 "Confirm"
info=$(lsblk -dno SIZE,MODEL "$device" | xargs)
echo "ALL DATA ON $device ($info) WILL BE ERASED."
read -rp "Type the disk name ($disk) to continue: " confirm
[[ $confirm == "$disk" ]] || {
  echo "Aborted — nothing was changed."
  exit 1
}

announce 4 "Prepare the configuration"
work=$(mktemp -d /tmp/survival-kit.XXXXXX)
cp -r --no-preserve=mode,ownership "$FLAKE_SRC"/. "$work"/
host="$work/hosts/survival-kit"
cat >"$host/selection.nix" <<EOF
# Written by survival-kit-install on $(date -I). Edit, then rebuild, to change.
{
  survivalKit.disk = {
    device = "$device";
    encrypt = $encrypt;
  };
}
EOF
{
  echo "# Detected by survival-kit-install on $(date -I) — REFERENCE ONLY, not imported."
  echo "# survival-kit uses hardware.enableAllHardware instead; see the manual."
  nixos-generate-config --no-filesystems --show-hardware-config
} >"$host/hardware-detected.nix"

announce 5 "Partition and format $device"
disko --mode destroy,format,mount --yes-wipe-all-disks --flake "path:$work#survival-kit"

announce 6 "Install (copies the whole system — this takes a while)"
nixos-install --flake "path:$work#survival-kit" --no-root-passwd --no-channel-copy

announce 7 "Hand the configuration over to /etc/nixos"
mkdir -p /mnt/etc/nixos
cp -r "$work"/. /mnt/etc/nixos/
git -C /mnt/etc/nixos init -q
git -C /mnt/etc/nixos add -A
git -C /mnt/etc/nixos -c user.name="survival-kit installer" -c user.email="installer@survival-kit.local" \
  commit -qm "installed by survival-kit-install on $(date -I) (disk $disk, encrypted: $encrypt)"

trap - ERR
echo
echo "Done. Remove the install medium and reboot."
