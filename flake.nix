{
  description = "survival-kit system";
  inputs = {
    # NixOS release channel; bump this to upgrade packages.
    # Independent of system.stateVersion: do NOT change that one when bumping.
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    disko = {
      url = "github:nix-community/disko";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };
  outputs =
    {
      self,
      nixpkgs,
      disko,
      ...
    }@inputs:
    {
      nixosConfigurations.survival-kit = nixpkgs.lib.nixosSystem {
        system = "x86_64-linux";
        specialArgs = { inherit inputs self; };
        modules = [
          ./hosts/survival-kit
          disko.nixosModules.disko
        ];
      };
    };
}
