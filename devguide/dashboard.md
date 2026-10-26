# Dashboard

`modules/dashboard/` — the page at `https://deck`.

- **Generated at build time** by Nix (`default.nix`): one tile per registry entry plus one
  per `survivalKit.dashboard.links.<name>` (tiles that aren't services, like the Manual and
  this guide). Sorted by `order`, then name. All text is HTML-escaped (`lib.escapeXML`).
  The header shows the hostname.
- The result is a plain directory (`index.html`, `style.css`, `status.js`) set as
  `survivalKit.web.dashboardRoot`; nginx serves it on the `deck` vhost.
- **Works without JavaScript** — tiles are plain links.
- `status.js` adds the dots (`role="img"` with an `aria-label`, so screen readers announce
  the state; `aria-busy` while re-checking): every 15 s it fetches `/health/<name>` for each service tile
  (same origin, so no CORS issues), 3 s timeout. 2xx/3xx → green, anything else → red;
  grey only until the first result (re-checks keep the colour, no flicker).
- `style.css`: system fonts, responsive grid, light/dark following the OS setting, no
  external files (offline).

To change the look, edit `style.css`. To add a non-service tile, set
`survivalKit.dashboard.links.<name> = { title; description; url; order; }` in any module.

Preview without a VM:

    nix build .#nixosConfigurations.survival-kit.config.survivalKit.web.dashboardRoot
    # open result/index.html (dots stay grey/red outside the box)
