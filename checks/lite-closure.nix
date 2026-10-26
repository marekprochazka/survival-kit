# Local only (heavy: builds the lite system) — a lite box contains no Ollama at all,
# not even as a dependency somewhere in its closure.
{ pkgs, self, ... }:
let
  lite = self.nixosConfigurations.survival-kit.extendModules {
    modules = [ { survivalKit.profile = "lite"; } ];
  };
  info = pkgs.closureInfo { rootPaths = [ lite.config.system.build.toplevel ]; };
in
pkgs.runCommand "lite-closure" { } ''
  if grep -- '-ollama' ${info}/store-paths; then # the package, its unit, …
    echo "FAIL: the lite system contains the store paths above" >&2
    exit 1
  fi
  touch $out
''
