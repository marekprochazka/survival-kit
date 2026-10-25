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
in
assert lib.assertMsg (
  plain.fileSystems."/".device == "/dev/disk/by-partlabel/disk-main-root"
) "plain: root should mount from the disko partlabel";
assert lib.assertMsg (plain.boot.initrd.luks.devices == { }) "plain: expected no LUKS devices";
assert lib.assertMsg (
  luks.fileSystems."/".device == "/dev/mapper/cryptroot"
) "luks: root should mount from /dev/mapper/cryptroot";
assert lib.assertMsg (luks.boot.initrd.luks.devices ? cryptroot) "luks: expected cryptroot device";
pkgs.runCommand "eval-disk" { } "touch $out"
