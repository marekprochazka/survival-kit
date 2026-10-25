# Desktop

`modules/desktop/` — enabled with `survivalKit.desktop.enable`, user set by
`survivalKit.desktop.autoLoginUser` (`deck`).

- **Session:** X11 + XFCE, LightDM with **autologin** (no login screen), no screen locker
  (`enableScreensaver = false` — a deliberate choice; disk encryption protects data at
  rest). Text consoles (Ctrl+Alt+F2…) still have a normal login prompt.
- **Apps:** Firefox, Papers (PDF), btop, the panel's system-load plugin, wmctrl.

## XFCE defaults

XFCE reads system-wide defaults from `/etc/xdg` (first in `XDG_CONFIG_DIRS` on NixOS). Every
file in `modules/desktop/xfconf/` is installed to
`/etc/xdg/xfce4/xfconf/xfce-perchannel-xml/`:

- `xfce4-panel.xml` — XFCE's stock panel + the system-load plugin. Its presence also skips
  the "default or empty panel?" question at first login.
- `xfwm4.xml` — compositing off (cheaper on old GPUs).
- `xfce4-power-manager.xml` — blank after 10 min, display off after 15, never lock.

These are **defaults only**: a user's own changes are saved in `~/.config` and win.
Nothing in this module writes to anyone's home directory.

## Firefox

`programs.firefox.policies` (enterprise policies): homepage `http://deck` (not locked),
telemetry/studies/Pocket/sponsored content off, no first-run pages, no default-browser
prompt, no onboarding popups. Preferences:

- `browser.fixup.domainsuffixwhitelist.deck = true` — so typing `wiki.deck` opens the site
  instead of a web search.
- `browser.sessionstore.resume_from_crash = false` — after a power cut, start on the
  dashboard, not the old pages.

## Dashboard autostart

`/etc/xdg/autostart/survival-kit-dashboard.desktop` runs `open-dashboard.sh`: wait up to
120 s for `http://deck` to answer (autologin can be faster than nginx), start Firefox, then
wait up to 60 s for its window and maximize it with `wmctrl` (Firefox has no "start
maximized" flag). Users can disable it in XFCE's "Session and Startup".
