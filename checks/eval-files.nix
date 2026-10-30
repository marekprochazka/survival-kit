# Layer 2 — eval assertions: Files (File Browser at files.deck, ADR-0006 amendment) — each
# person's space is built by a root service from bind mounts; File Browser itself is confined
# and can't see the content tree; no admin account, no sharing links.
{ pkgs, self, ... }:
let
  inherit (pkgs) lib;
  base = self.nixosConfigurations.survival-kit;
  cfg = base.config;
  lite = (base.extendModules { modules = [ { survivalKit.profile = "lite"; } ]; }).config;
  reg = cfg.survivalKit.registry.files;
  fb = cfg.systemd.services.filebrowser;
  view = cfg.systemd.services.survival-kit-files-view;
  viewDir = "/var/lib/survival-kit-files/view";
  watched = cfg.systemd.paths.survival-kit-files-view.pathConfig.PathChanged;
  setup = fb.preStart;
  root = cfg.systemd.tmpfiles.settings.filebrowser.${viewDir}.d;
in
assert lib.assertMsg (
  reg.port == 8330 && reg.healthPath == "/health" && reg.order == 16
) "Files: port 8330, health /health, after Passwords on the dashboard";
assert lib.assertMsg (
  lib.elem "/var/lib/survival-kit" fb.serviceConfig.InaccessiblePaths
  && fb.serviceConfig.ProtectSystem == "strict"
) "File Browser can't see the content tree and runs confined";
assert lib.assertMsg (lib.all (f: lib.hasInfix f setup) [
  "--perm.admin=false"
  "--perm.share=false"
  "--signup"
  "--createUserDir"
]) "File Browser: sign-up with a home each, no admins, no sharing links";
assert lib.assertMsg (
  root.mode == "0755" && root.user == "root"
) "the view root is root's (File Browser can't drop files there)";
assert lib.assertMsg (
  !(view.serviceConfig ? ProtectSystem) && lib.elem "filebrowser.service" view.before
) "the spaces are mounted system-wide, before File Browser starts";
assert lib.assertMsg (
  lib.elem "${viewDir}/users" watched && lib.elem "/run/survival-kit/drives.json" watched
) "the spaces are rebuilt after a sign-up and after every drive change";
assert lib.assertMsg (
  cfg.systemd.services.survival-kit-drives.environment.FILES_GROUP == "filebrowser"
) "exFAT/NTFS drives are mounted writable for File Browser";
assert lib.assertMsg (lib.hasInfix "client_max_body_size 0"
  cfg.services.nginx.virtualHosts."files.deck".extraConfig
) "large uploads to Files are not cut off by nginx";
assert lib.assertMsg lite.survivalKit.services.files.enable "Files is on in lite too";
pkgs.runCommand "eval-files" { } "touch $out"
