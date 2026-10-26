# Layer 2 — eval assertions: disk layout for plain vs LUKS root.
{ pkgs, self, ... }:
let
  inherit (pkgs) lib;
  withEncrypt =
    encrypt:
    (self.nixosConfigurations.survival-kit.extendModules {
      modules = [ { survivalKit.disk.encrypt = encrypt; } ];
    }).config;
  plain = withEncrypt false;
  luks = withEncrypt true;
  parts = plain.disko.devices.disk.main.content.partitions;
  grub = plain.boot.loader.grub;
in
assert lib.assertMsg (
  plain.fileSystems."/".device == "/dev/disk/by-partlabel/disk-main-root"
) "plain: root should mount from the disko partlabel";
assert lib.assertMsg (plain.boot.initrd.luks.devices == { }) "plain: expected no LUKS devices";
assert lib.assertMsg (
  luks.fileSystems."/".device == "/dev/mapper/cryptroot"
) "luks: root should mount from /dev/mapper/cryptroot";
assert lib.assertMsg (luks.boot.initrd.luks.devices ? cryptroot) "luks: expected cryptroot device";
assert lib.assertMsg (
  parts.bios.type == "EF02"
) "need a BIOS-boot partition (EF02) for legacy BIOS";
assert lib.assertMsg (parts.ESP.type == "EF00") "need an ESP (EF00) for UEFI";
assert lib.assertMsg (
  grub.enable && grub.efiSupport && grub.efiInstallAsRemovable
) "GRUB must boot both BIOS and UEFI (removable EFI path)";
assert lib.assertMsg (
  !plain.boot.loader.systemd-boot.enable
) "systemd-boot cannot boot legacy BIOS";
assert lib.assertMsg (
  grub.devices == [ "/dev/vda" ]
) "GRUB installs to the target disk (set by disko)";
assert lib.assertMsg (
  grub.configurationLimit == 10
) "keep at most 10 generations in the boot menu so the 512 MB ESP can't fill up";
pkgs.runCommand "eval-disk" { } "touch $out"
