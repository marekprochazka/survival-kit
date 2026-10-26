# Installer & ISO

## Disk layout (`hosts/survival-kit/disko.nix`)

One GPT disk that boots on **both legacy BIOS and UEFI** machines:

| Partition | Size | Purpose |
|---|---|---|
| `bios` (type EF02) | 1 MB | GRUB's BIOS boot code |
| `ESP` (EF00) | 512 MB | vfat at `/boot`: GRUB's UEFI files, kernels |
| `root` | rest | ext4 at `/` (`noatime`), optionally inside LUKS (`cryptroot`) |

Options: `survivalKit.disk.device` and `survivalKit.disk.encrypt`. GRUB is installed for both
`i386-pc` and `x86_64-efi`, the EFI part at the fallback path `EFI/BOOT/BOOTX64.EFI`
(`efiInstallAsRemovable`) so firmware finds it without a boot entry. disko sets GRUB's
target disk itself (because of the EF02 partition). The boot menu keeps at most 10
generations (`configurationLimit`), so the 512 MB ESP can't fill up; older generations
stay in the store.

## The installer (`pkgs/survival-kit-install.sh`)

Interactive, 7 steps:

1. Choose a disk — only whole, writable, non-empty, unmounted disks are offered (not
   loop/CD/floppy/zram, eMMC boot areas, or card readers without a card). Type the name
   exactly as listed.
2. Encryption yes/no — disko asks for the passphrase (twice) during step 5.
3. Confirm — type the disk name, or nothing happens.
4. Copy this flake (bundled on the ISO) to `/tmp`, write
   `hosts/survival-kit/selection.nix` (disk + encryption) and `hardware-detected.nix`
   (`nixos-generate-config`, reference only). File modes are kept (scripts stay
   executable). The disk is recorded by its stable
   `/dev/disk/by-id/…` name, so later bootloader updates can't hit another disk if `/dev/sdX`
   names change.
5. `disko --mode destroy,format,mount` → the new disk at `/mnt`.
6. `nixos-install --flake path:<copy>#survival-kit`.
7. Copy the flake to `/mnt/etc/nixos`, `git init`, first commit.

`hosts/survival-kit/default.nix` imports `selection.nix` only if it exists, so the same repo
works for development (defaults) and on installed boxes. A failed run unmounts `/mnt` and
closes `cryptroot`, so it can simply be re-run.

## How the install works offline

- The ISO carries (`modules/installer`, `system.extraDependencies`) the complete target
  system **prebuilt** in two variants (with and without encryption), the disko scripts,
  and the **build inputs** of the few things that depend on the disk name (the system's
  top level, GRUB's install script, the disko script). An install then copies almost
  everything and builds about four tiny derivations.
- `nixos-install` gets `--option substitute true` (otherwise Nix stops copying from the
  live system when it sees no internet) and `--option always-allow-substitutes true` (copy
  even things marked "build locally" — rebuilding them needs tools the ISO lacks).

## The ISO

`nixosConfigurations.installer` = nixpkgs' minimal installation CD + `hosts/installer`:
BIOS/UEFI/USB bootable, volume `SURVIVAL_KIT`, file `survival-kit-<date>-<rev>.iso`. On
tty1 the live user's login shell starts `sudo survival-kit-install` once per boot; other
consoles are plain shells. Build: `nix build .#iso` (~3 GB, several minutes).
