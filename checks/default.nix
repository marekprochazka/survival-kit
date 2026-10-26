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
    eval-desktop = import ./eval-desktop.nix args;
    eval-install = import ./eval-install.nix args;
    eval-firstboot = import ./eval-firstboot.nix args;
    eval-iso = import ./eval-iso.nix args;
    firstboot-script = import ./firstboot-script.nix args;
    panel-drift = import ./panel-drift.nix args;
    eval-tls = import ./eval-tls.nix args;
    eval-vaultwarden = import ./eval-vaultwarden.nix args;
    eval-ollama = import ./eval-ollama.nix args;
    eval-profiles = import ./eval-profiles.nix args;
    content-unit = import ./content-unit.nix args;
    eval-content = import ./eval-content.nix args;
    lookup-unit = import ./lookup-unit.nix args;
    tls-script = import ./tls-script.nix args;
  };
in
evalChecks
// {
  lint = import ./lint.nix args;
  eval = pkgs.linkFarm "eval" (
    pkgs.lib.mapAttrsToList (name: path: { inherit name path; }) evalChecks
  );
  boot = import ./boot.nix args;
  services = import ./services.nix args;
  desktop = import ./desktop.nix args;
  firstboot = import ./firstboot.nix args;
  lite-closure = import ./lite-closure.nix args; # local only: builds the lite system
}
