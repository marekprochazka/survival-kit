# All service modules are always imported; each is inert until its
# survivalKit.services.<name>.enable is set (import ≠ enable).
{
  imports = [
    ./web.nix
  ];
}
