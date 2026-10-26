# Layer 2 — our XFCE panel default (modules/desktop/xfconf/xfce4-panel.xml) is XFCE's
# stock layout + the system-load plugin (id 19). Fails when a nixpkgs update changes
# the stock layout — then re-copy it and re-add plugin 19.
{ pkgs, ... }:
pkgs.runCommand "panel-drift" { nativeBuildInputs = [ pkgs.python3 ]; } ''
  python3 - ${../modules/desktop/xfconf/xfce4-panel.xml} \
    ${pkgs.xfce4-panel}/etc/xdg/xfce4/panel/default.xml <<'EOF'
  import sys, xml.etree.ElementTree as ET

  def canon(el):
      """element as nested tuples, ignoring whitespace/comments, without plugin 19"""
      kids = [canon(c) for c in el
              if c.get("name") != "plugin-19" and c.get("value") != "19"]
      return (el.tag, tuple(sorted(el.attrib.items())), tuple(kids))

  ours, stock = (canon(ET.parse(f).getroot()) for f in sys.argv[1:3])
  if ours != stock:
      sys.exit("panel layout drifted from XFCE's stock default — re-copy it (see devguide/desktop.md)")
  EOF
  touch $out
''
