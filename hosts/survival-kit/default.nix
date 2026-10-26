{ lib, ... }:
{
  # pull in the base system + disk layout
  imports = [
    ../../modules/base
    ../../modules/services
    ../../modules/dashboard
    ../../modules/desktop
    ../../modules/firstboot
    ../../modules/tls
    ./disko.nix
  ]
  # written by survival-kit-install on installed machines (disk choice);
  # absent in the dev repo → defaults (/dev/vda, unencrypted)
  ++ lib.optional (builtins.pathExists ./selection.nix) ./selection.nix;

  networking.hostName = "survival-kit";

  # services (no lite/full profiles yet — ADR-0002 profiles come with ≥2 services)
  survivalKit.services.kiwix.enable = true;

  # The owner's account. Fixed name (autologin needs it at build time); the
  # display name and password are set by the first-boot prompt (modules/firstboot).
  users.users.deck = {
    isNormalUser = true;
    extraGroups = [ "wheel" ]; # sudo rights
    initialHashedPassword = "!"; # locked until first boot sets it
  };

  survivalKit.desktop = {
    enable = true;
    autoLoginUser = "deck";
  };

  # dev VM (utils/run) only — XFCE + Firefox need more than the 1 GB default
  virtualisation.vmVariant.virtualisation.memorySize = 2048;

  # The release this system was first installed with. Keeps stateful services
  # compatible with their existing on-disk data. Never bump it on upgrades.
  system.stateVersion = "26.05";

  # GRUB boots legacy BIOS (via the EF02 partition) and UEFI; disko sets
  # boot.loader.grub.devices to the target disk. The removable EFI path
  # (EFI/BOOT/BOOTX64.EFI) needs no firmware boot entry — robust for moved
  # disks and VirtualBox.
  boot.loader.grub = {
    enable = true;
    efiSupport = true;
    efiInstallAsRemovable = true;
    # each generation's kernel+initrd is ~45 MB on the 512 MB ESP; older
    # generations stay in the Nix store (rollback via nixos-rebuild still works)
    configurationLimit = 10;
  };
}
