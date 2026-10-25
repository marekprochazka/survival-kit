# The real survival-kit host as a VM-test node, shared by all VM tests.
{ inputs }:
{
  imports = [
    ../hosts/survival-kit
    inputs.disko.nixosModules.disko
  ];
  virtualisation.memorySize = 2048; # XFCE + Firefox need more than the 1 GB default
}
