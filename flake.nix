{
  description = "survival-kit system";
  inputs = {
    # this version must match version in default.nix of hosts/survival-kit
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
  };
  outputs = { self, nixpkgs, ... }@inputs: {
    nixosConfigurations.survival-kit = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
        specialArgs = { inherit inputs self; };
        modules = [
          ./hosts/survival-kit
        ];
    };
  };
}