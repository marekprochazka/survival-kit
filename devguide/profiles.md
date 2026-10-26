# Profiles

`modules/profiles/` — which services a box gets, **chosen once at install**:

| Profile | Services | For |
|---|---|---|
| `lite` | wiki (Kiwix), passwords (Vaultwarden) | low RAM, slow CPU |
| `full` | lite + local AI ([Ollama](ollama.html)) | ≥ 8 GB RAM, i5-class CPU |

Always on, whatever the profile: dashboard, desktop, first boot, HTTPS.

- The option `survivalKit.profile` (`"lite"` or `"full"`) has no default. The installer
  writes it into `hosts/survival-kit/selection.nix`; the dev repo (no `selection.nix`) sets
  `lib.mkDefault "full"` in `hosts/survival-kit/default.nix`, so VM tests cover everything.
- The profile sets each `survivalKit.services.<name>.enable` with **`lib.mkDefault`** — a
  default, not a decision: a single service can still be switched by hand
  (`survivalKit.services.ollama.enable = true;` on a lite box wins).
- A `lite` system doesn't contain the `full`-only services at all — not even on disk (the
  `lite-closure` check proves it).

**Adding a service to a profile:** one line in `modules/profiles/default.nix`, e.g.
`notes.enable = lib.mkDefault true;` (both profiles) or
`lib.mkDefault (profile == "full")` (full only).

**Installer:** the ISO prebuilds every profile × encryption combination (4 systems) so an
offline install of either profile copies instead of builds — see [Installer](installer.html).

**Switching later is not supported.** The owner reinstalls from the ISO (after a backup).
Technically you *can* change the line in `selection.nix` and rebuild — but that needs a
network connection: the box carries its own profile's system, not the other one's.
