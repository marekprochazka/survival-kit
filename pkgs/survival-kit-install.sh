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

# A failed step 5/6 leaves the target mounted at /mnt (and LUKS open); the disk
# then counts as "in use" and a re-run couldn't offer it again. Release it.
release_target() {
  if mountpoint -q /mnt; then umount -R /mnt || true; fi
  if [[ -e /dev/mapper/cryptroot ]]; then cryptsetup close cryptroot || true; fi
}
trap 'echo >&2; echo "!! Install failed at step $step. Re-run survival-kit-install to start over." >&2; release_target' ERR

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

if mountpoint -q /mnt || [[ -e /dev/mapper/cryptroot ]]; then
  echo "Releasing leftovers of a previous install attempt (/mnt, cryptroot)…"
  release_target
fi

announce 1 "Choose the target disk"
candidates=()
while read -r name type ro size; do
  [[ $type == disk ]] || continue
  [[ $name == loop* || $name == sr* || $name == zram* || $name == fd* || $name == ram* ]] && continue
  # read-only (e.g. eMMC boot areas mmcblk0boot0/1) or empty (card reader without a card)
  [[ $ro == 0 && $size != 0 ]] || continue
  # skip disks with anything mounted — e.g. the USB stick we booted from.
  # Fail closed: if lsblk can't tell us (error), the disk is skipped, not offered.
  mounts=$(lsblk -nro MOUNTPOINTS "/dev/$name") || continue
  [[ -z $mounts ]] || continue
  candidates+=("$name")
done < <(lsblk -dnbro NAME,TYPE,RO,SIZE)
if ((${#candidates[@]} == 0)); then
  echo "No usable disk found (all disks are in use or none attached)." >&2
  exit 1
fi
lsblk -do NAME,SIZE,MODEL,TRAN "${candidates[@]/#//dev/}"
read -rp "Disk to install to (e.g. ${candidates[0]}): " disk
printf '%s\n' "${candidates[@]}" | grep -qxF -- "$disk" || {
  echo "'$disk' is not one of the listed disks." >&2
  exit 1
}
# GRUB and disko get a stable name: /dev/sdX can change between boots (e.g.
# when the USB stick is removed); /dev/disk/by-id/… follows the disk itself.
# Prefer model/serial names (ata-…, nvme-…, usb-…) over wwn-/eui identifiers.
device=""
for link in /dev/disk/by-id/*; do
  [[ -e $link && $(readlink -f "$link") == "/dev/$disk" ]] || continue
  case $(basename "$link") in
  wwn-* | nvme-eui.*) [[ -n $device ]] || device=$link ;;
  *)
    device=$link
    break
    ;;
  esac
done
if [[ -z $device ]]; then
  device="/dev/$disk"
  echo "Note: no stable /dev/disk/by-id name for $disk; using $device."
fi

announce 2 "Encryption"
read -rp "Encrypt the disk? A passphrase is then needed at every boot. [y/N] " answer
encrypt=false
if [[ $answer == [yY]* ]]; then
  encrypt=true
  # disko asks for the passphrase itself (twice) while formatting, in step 5;
  # it is never written to disk
  echo "You will be asked for the passphrase (twice) during step 5."
fi

announce 3 "Confirm"
info=$(lsblk -dno SIZE,MODEL "/dev/$disk" | tr -s ' ') # squeeze spaces (xargs chokes on quotes)
info=${info# }
echo "ALL DATA ON /dev/$disk ($info) WILL BE ERASED."
read -rp "Type the disk name ($disk) to continue: " confirm
[[ $confirm == "$disk" ]] || {
  echo "Aborted — nothing was changed."
  exit 1
}

announce 4 "Prepare the configuration"
work=$(mktemp -d /tmp/survival-kit.XXXXXX)
# keep file modes (executable scripts stay executable), drop store ownership,
# then make everything writable (store copies are read-only)
cp -r --no-preserve=ownership "$FLAKE_SRC"/. "$work"/
chmod -R u+w "$work"
host="$work/hosts/survival-kit"
cat >"$host/selection.nix" <<EOF
# Written by survival-kit-install on $(date -I). Edit + rebuild to change
# (a changed configuration needs network to rebuild; see the manual).
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

announce 5 "Partition and format /dev/$disk"
disko --mode destroy,format,mount --yes-wipe-all-disks --flake "path:$work#survival-kit"

announce 6 "Install (copies the whole system — this takes a while)"
# Offline: without internet, nix turns substitution off — then it can't even copy
# the pinned flake inputs from this live system into /mnt and tries GitHub.
# - substitute=true keeps copying from the live store (nixos-install adds it as
#   the "auto" substituter; don't override `substituters`, that drops it again);
# - always-allow-substitutes: copy even derivations marked "build locally"
#   (buildEnv, writeText, …) — rebuilding them needs tools the ISO doesn't carry.
# Verified by an offline QEMU install from the ISO (round B review).
nixos-install --flake "path:$work#survival-kit" --no-root-passwd --no-channel-copy \
  --option substitute true --option always-allow-substitutes true

announce 7 "Hand the configuration over to /etc/nixos"
mkdir -p /mnt/etc/nixos
cp -r "$work"/. /mnt/etc/nixos/
git -C /mnt/etc/nixos init -q
# repo-local identity so `sudo git commit` works on the installed machine
git -C /mnt/etc/nixos config user.name "survival-kit owner"
git -C /mnt/etc/nixos config user.email "owner@survival-kit.local"
git -C /mnt/etc/nixos add -A
git -C /mnt/etc/nixos -c user.name="survival-kit installer" -c user.email="installer@survival-kit.local" \
  commit -qm "installed by survival-kit-install on $(date -I) (disk $disk, encrypted: $encrypt)"

trap - ERR
cat <<EOF

Done! survival-kit is installed on /dev/$disk.

Next:
  1. Shut down:   sudo poweroff
  2. Remove the install medium (USB stick / DVD — in a VM: eject the ISO),
     otherwise the machine starts this installer again.
  3. Switch on again. The first start asks for your name and a password.
EOF
