# The real survival-kit host as a VM-test node, shared by all VM tests.
{ inputs }:
{ pkgs, ... }:
{
  imports = [
    ../hosts/survival-kit
    inputs.disko.nixosModules.disko
    (import ./test-maps.nix { inherit pkgs; }).module # stand-ins, not the 390 MB maps
  ];
  virtualisation.memorySize = 2048; # XFCE + Firefox need more than the 1 GB default
  survivalKit.firstBoot.enable = false; # the firstboot test re-enables it
}
