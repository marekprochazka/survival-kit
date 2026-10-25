# Live installer ISO: boots via BIOS, UEFI and USB, starts survival-kit-install
# on tty1, and carries everything an OFFLINE install needs (modules/installer).
{ lib, self, ... }:
{
  imports = [ ../../modules/installer ];

  survivalKit.installer.enable = true;

  isoImage = {
    makeBiosBootable = true;
    makeEfiBootable = true;
    makeUsbBootable = true;
    volumeID = "SURVIVAL_KIT";
  };
  # survival-kit-<YYYYMMDD>-<git rev>.iso
  image.baseName = lib.mkForce "survival-kit-${
    builtins.substring 0 8 (self.lastModifiedDate or "00000000")
  }-${self.shortRev or self.dirtyShortRev or "dev"}";

  # Start the installer on tty1, once per boot. Ctrl+C or finishing → a normal
  # shell; the other consoles (Alt+F2…) are plain shells for troubleshooting.
  programs.bash.loginShellInit = ''
    if [[ $(tty) == /dev/tty1 && $USER == nixos && ! -e /tmp/.survival-kit-installer-started ]]; then
      touch /tmp/.survival-kit-installer-started
      sudo survival-kit-install || true
    fi
  '';
  services.getty.helpLine = ''

    survival-kit installer: run `sudo survival-kit-install` to (re)start it.
  '';

  system.stateVersion = "26.05";
}
