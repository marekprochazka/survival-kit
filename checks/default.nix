# All automated tests (ADR-0003). One file per check:
#   nix build .#checks.x86_64-linux.<name>   → run one
#   nix build .#checks.x86_64-linux.eval     → all layer-2 eval checks (what CI runs)
#   nix flake check                          → run everything (incl. VM tests)
{
  pkgs,
  self,
  inputs,
}:
let
  args = { inherit pkgs self inputs; };
  # Layer 2: add new eval checks here — CI picks them up via `eval` automatically.
  evalChecks = {
    eval-disk = import ./eval-disk.nix args;
    eval-web = import ./eval-web.nix args;
  };
in
evalChecks
// {
  lint = import ./lint.nix args;
  eval = pkgs.linkFarm "eval" (
    pkgs.lib.mapAttrsToList (name: path: { inherit name path; }) evalChecks
  );
  boot = import ./boot.nix args;
}
