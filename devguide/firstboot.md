# First boot

`modules/firstboot/` — option `survivalKit.firstBoot.enable` (on by default; tests turn it
off except the first-boot test).

## The account

The account is always **`deck`** (`hosts/survival-kit/default.nix`): in `wheel` (sudo), with
a **locked** password (`initialHashedPassword = "!"`) until first boot. Why a fixed name:
the desktop autologin needs the name at build time, and choosing a name at first boot would
need a rebuild of a changed configuration — impossible offline. Users stay mutable
(`users.mutableUsers`, the NixOS default), so the password set at runtime survives rebuilds.

## The prompt

`survival-kit-firstboot.service` (a one-shot) runs `firstboot.sh` on **tty1, before the
display manager**:

1. Asks for a display name — printable characters only, no `:` or `,` (they would break
   `/etc/passwd`), re-asks otherwise.
2. Asks for a password twice (`read -s` into `$REPLY`: exact, spaces kept, never shown)
   until both match.
3. Sets the password (`chpasswd`, via stdin only — never on a command line or in a log),
   writes the marker `/var/lib/survival-kit/firstboot-done`, saves the name to
   `/var/lib/survival-kit/display-name`, then sets it (`usermod -c`). A failing name never
   costs the password.

Ctrl+C / Ctrl+\\ / Ctrl+Z are ignored; Ctrl+D (end of input) counts as an empty answer, and
after three in a row the prompt gives up for now (no marker — it returns at the next start).

Unit details: `ConditionPathExists=!<marker>` (runs until it succeeded once);
`restartIfChanged = false` (a rebuild never starts it on a running desktop);
`StandardInput=tty-force` on `/dev/tty1`; the display manager only *wants* it, so a failed
or interrupted prompt never blocks the desktop (it simply comes back at the next boot).
Boot is quiet (`quiet`, `systemd.show_status=error`, console log level 3) so status lines
don't print into the prompt.

## Why the name is re-applied

NixOS rewrites `/etc/passwd` from the configuration at **every activation** (each boot and
rebuild), which would wipe the display name. An activation script
(`survival-kit-display-name`, after `users`) sets it again from the saved file.

Reset first boot (e.g. to hand the box to someone else):

    sudo rm /var/lib/survival-kit/firstboot-done /var/lib/survival-kit/display-name
    sudo passwd -l deck && sudo reboot
