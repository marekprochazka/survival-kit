# The installer command. flakeSrc = this flake's source, bundled for offline installs.
{
  writeShellApplication,
  lib,
  coreutils,
  util-linux,
  cryptsetup,
  gnugrep,
  findutils,
  git,
  nixos-install-tools,
  disko,
  flakeSrc,
}:
writeShellApplication {
  name = "survival-kit-install";
  runtimeInputs = [
    coreutils
    util-linux # lsblk, mountpoint, umount
    cryptsetup # close a leftover cryptroot
    gnugrep
    findutils # xargs
    git
    nixos-install-tools # nixos-install, nixos-generate-config
    disko
  ];
  text = ''
    FLAKE_SRC=${lib.escapeShellArg "${flakeSrc}"}
  ''
  + builtins.readFile ./survival-kit-install.sh;
}
