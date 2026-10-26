# Layer 3 — services VM test (local only): hosts → nginx → Kiwix end to end,
# catalog drop-ins, robustness against bad ZIMs, and down detection.
{
  pkgs,
  self,
  inputs,
  ...
}:
let
  # tiny ZIMs for drop-in tests (zimwriterfs requires a 48x48 illustration)
  mkTestZim =
    name:
    pkgs.runCommand "${name}.zim"
      {
        nativeBuildInputs = [
          pkgs.zim-tools
          pkgs.imagemagick
        ];
      }
      ''
        mkdir html
        echo '<html><head><title>${name}</title></head><body>${name} test page</body></html>' > html/index.html
        magick -size 48x48 xc:'#888888' html/icon.png
        zimwriterfs --name ${name} --title ${name} --description test --creator test \
          --publisher test --language eng --welcome index.html --illustration icon.png html $out
      '';
  dropinZim = mkTestZim "dropin-test";
  privateZim = mkTestZim "private-test";
in
pkgs.testers.runNixOSTest {
  name = "services";
  node.specialArgs = { inherit inputs self; };
  nodes.machine = import ./host-node.nix { inherit inputs; };
  testScript = ''
    STARTER_BOOKS = 7  # bundled ZIMs; raised as starter content lands
    ZIMS = "/var/lib/survival-kit/kiwix/zims"
    CATALOG = "curl -sf 'http://wiki.deck/catalog/v2/entries?count=-1' | grep -c '<entry>' || true"

    def books():
        return int(machine.succeed(CATALOG).strip())

    def wait_books(n):
        machine.wait_until_succeeds(f"test $({CATALOG}) -eq {n}", timeout=120)

    machine.wait_for_unit("kiwix-library.service")
    machine.wait_for_unit("kiwix-serve.service")
    machine.wait_for_unit("nginx.service")
    machine.wait_for_open_port(8080)

    with subtest("wiki.deck resolves and proxies to Kiwix"):
        machine.wait_until_succeeds("curl -sf -o /dev/null http://wiki.deck/")
        wait_books(STARTER_BOOKS)

    with subtest("starter books are served under clean names"):
        for book in ["archlinux_en_all_maxi", "devdocs_en_man", "devdocs_en_git",
                     "devdocs_en_bash", "devdocs_en_nix"]:
            machine.succeed(f"curl -sf -o /dev/null -w '%{{http_code}}' http://wiki.deck/content/{book} | grep -q 302")

    with subtest("survival-kit manual is served"):
        machine.wait_until_succeeds("curl -sfL http://wiki.deck/content/survival-kit | grep -q 'Welcome to survival-kit'")

    with subtest("developer guide is served and linked from the manual"):
        machine.wait_until_succeeds("curl -sfL http://wiki.deck/content/survival-kit-dev | grep -q 'survival-kit developer guide'")
        machine.succeed("curl -sfL http://wiki.deck/content/survival-kit | grep -q 'content/survival-kit-dev'")

    with subtest("health endpoint is up"):
        machine.succeed("curl -sf -o /dev/null http://deck/health/kiwix")

    with subtest("drop-in ZIM appears after catalog rebuild"):
        machine.succeed("cp ${dropinZim} " + ZIMS + "/dropin-test.zim")
        machine.succeed("systemctl restart kiwix-library.service")
        wait_books(STARTER_BOOKS + 1)
        machine.wait_until_succeeds("curl -sfL http://wiki.deck/content/dropin-test | grep -q 'dropin-test test page'")

    with subtest("a corrupt ZIM is skipped, the rest keeps serving"):
        machine.succeed("echo garbage > " + ZIMS + "/broken.zim")
        machine.succeed("systemctl restart kiwix-library.service")
        machine.wait_for_unit("kiwix-serve.service")
        wait_books(STARTER_BOOKS + 1)

    with subtest("a dangling symlink in zims/ does not take the wiki down"):
        machine.succeed("ln -s /nonexistent/gone.zim " + ZIMS + "/gone.zim")
        machine.succeed("systemctl restart kiwix-library.service")
        machine.wait_for_unit("kiwix-serve.service")
        wait_books(STARTER_BOOKS + 1)
        machine.succeed("rm " + ZIMS + "/gone.zim")

    with subtest("files that are not .zim are reported, not silently ignored"):
        machine.succeed("echo hello > " + ZIMS + "/notes.txt")
        machine.succeed("systemctl restart kiwix-library.service")
        machine.wait_until_succeeds("journalctl -b -u kiwix-library | grep -q 'ignoring.*notes.txt'", timeout=60)
        machine.succeed("rm " + ZIMS + "/notes.txt")

    with subtest("a root-only (0600) drop-in is still served"):
        machine.succeed("install -m 0600 ${privateZim} " + ZIMS + "/private-test.zim")
        machine.succeed("systemctl restart kiwix-library.service")
        wait_books(STARTER_BOOKS + 2)
        machine.wait_until_succeeds("curl -sfL http://wiki.deck/content/private-test | grep -q 'private-test test page'")

    with subtest("dashboard lists services and links, in order"):
        page = machine.succeed("curl -sf http://deck/")
        assert 'data-health="/health/kiwix"' in page, "Wiki tile should carry its health URL"
        assert page.index("Wiki") < page.index("Manual"), "tiles must be sorted by order"
        assert 'href="http://wiki.deck/content/survival-kit"' in page, "Manual tile link"
        assert 'href="http://wiki.deck/content/survival-kit-dev"' in page, "Developer guide tile link"
        assert 'role="img"' in page, "status dots must be announced to screen readers"
        machine.succeed("curl -sf -o /dev/null http://deck/style.css")
        machine.succeed("curl -sf -o /dev/null http://deck/status.js")

    with subtest("the box's IP and mDNS name land on the dashboard"):
        machine.succeed("curl -sf http://127.0.0.1/ | grep -q 'data-health'")
        machine.succeed("curl -sf -H 'Host: survival-kit.local' http://127.0.0.1/ | grep -q 'data-health'")

    with subtest("down detection: health returns 502 when Kiwix is stopped"):
        machine.succeed("systemctl stop kiwix-serve.service")
        code = machine.succeed("curl -s -o /dev/null -w '%{http_code}' http://deck/health/kiwix")
        assert code == "502", f"expected 502, got {code}"
  '';
}
