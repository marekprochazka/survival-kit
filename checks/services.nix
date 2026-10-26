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
  # every https request trusts the box's own CA (as Firefox does via policy)
  curl = "curl --cacert /var/lib/survival-kit/tls/ca.crt";
in
pkgs.testers.runNixOSTest {
  name = "services";
  node.specialArgs = { inherit inputs self; };
  nodes.machine = {
    imports = [ (import ./host-node.nix { inherit inputs; }) ];
    environment.systemPackages = [ pkgs.openssl ]; # test-only: inspect certificates
  };
  testScript = ''
    STARTER_BOOKS = 7  # bundled ZIMs; raised as starter content lands
    ZIMS = "/var/lib/survival-kit/kiwix/zims"
    CATALOG = "${curl} -sf 'https://wiki.deck/catalog/v2/entries?count=-1' | grep -c '<entry>' || true"

    def books():
        return int(machine.succeed(CATALOG).strip())

    def wait_books(n):
        machine.wait_until_succeeds(f"test $({CATALOG}) -eq {n}", timeout=120)

    machine.wait_for_unit("kiwix-library.service")
    machine.wait_for_unit("kiwix-serve.service")
    machine.wait_for_unit("nginx.service")
    machine.wait_for_open_port(8080)

    with subtest("wiki.deck resolves and proxies to Kiwix"):
        machine.wait_until_succeeds("${curl} -sf -o /dev/null https://wiki.deck/")
        wait_books(STARTER_BOOKS)

    with subtest("starter books are served under clean names"):
        for book in ["archlinux_en_all_maxi", "devdocs_en_man", "devdocs_en_git",
                     "devdocs_en_bash", "devdocs_en_nix"]:
            machine.succeed(f"${curl} -sf -o /dev/null -w '%{{http_code}}' https://wiki.deck/content/{book} | grep -q 302")

    with subtest("survival-kit manual is served"):
        machine.wait_until_succeeds("${curl} -sfL https://wiki.deck/content/survival-kit | grep -q 'Welcome to survival-kit'")

    with subtest("developer guide is served and linked from the manual"):
        machine.wait_until_succeeds("${curl} -sfL https://wiki.deck/content/survival-kit-dev | grep -q 'survival-kit developer guide'")
        machine.succeed("${curl} -sfL https://wiki.deck/content/survival-kit | grep -q 'content/survival-kit-dev'")

    with subtest("the box's certificate authority"):
        T = "/var/lib/survival-kit/tls"
        machine.wait_for_unit("survival-kit-tls.service")
        assert machine.succeed(f"stat -c '%a %U' {T}/ca.key").strip() == "600 root"
        # nginx runs unprivileged: it may read the site key, nobody else may
        assert machine.succeed(f"stat -c '%a %U %G' {T}/deck.key").strip() == "640 root nginx"
        machine.succeed(f"openssl verify -CAfile {T}/ca.crt {T}/deck.crt")
        names = machine.succeed(f"openssl x509 -in {T}/deck.crt -noout -ext subjectAltName")
        for n in ["DNS:deck", "DNS:wiki.deck", "DNS:survival-kit.local"]:
            assert n in names, f"{n} missing from {names}"
        # name constraints: a certificate for another site, signed by this CA, is refused
        machine.succeed(
            "cd /tmp && openssl req -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes"
            " -keyout ex.key -out ex.csr -subj /CN=example.com"
            " && printf 'subjectAltName=DNS:example.com\\n' > ex.ext"
            f" && openssl x509 -req -in ex.csr -CA {T}/ca.crt -CAkey {T}/ca.key -out ex.crt -extfile ex.ext -days 30"
        )
        out = machine.fail(f"openssl verify -CAfile {T}/ca.crt /tmp/ex.crt 2>&1")
        assert "permitted subtree violation" in out, out

    with subtest("health endpoint is up"):
        machine.succeed("${curl} -sf -o /dev/null https://deck/health/kiwix")

    with subtest("drop-in ZIM appears after catalog rebuild"):
        machine.succeed("cp ${dropinZim} " + ZIMS + "/dropin-test.zim")
        machine.succeed("systemctl restart kiwix-library.service")
        wait_books(STARTER_BOOKS + 1)
        machine.wait_until_succeeds("${curl} -sfL https://wiki.deck/content/dropin-test | grep -q 'dropin-test test page'")

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
        machine.wait_until_succeeds("${curl} -sfL https://wiki.deck/content/private-test | grep -q 'private-test test page'")

    with subtest("dashboard lists services and links, in order"):
        page = machine.succeed("${curl} -sf https://deck/")
        assert 'data-health="/health/kiwix"' in page, "Wiki tile should carry its health URL"
        assert page.index("Wiki") < page.index("Manual"), "tiles must be sorted by order"
        assert 'href="https://wiki.deck/content/survival-kit"' in page, "Manual tile link"
        assert 'href="https://wiki.deck/content/survival-kit-dev"' in page, "Developer guide tile link"
        assert 'role="img"' in page, "status dots must be announced to screen readers"
        machine.succeed("${curl} -sf -o /dev/null https://deck/style.css")
        machine.succeed("${curl} -sf -o /dev/null https://deck/status.js")

    with subtest("plain http redirects to https"):
        for url in ["http://wiki.deck/", "http://deck/", "http://127.0.0.1/"]:
            res = machine.succeed(f"curl -s -o /dev/null -w '%{{http_code}} %{{redirect_url}}' {url}")
            assert res == "301 " + url.replace("http:", "https:"), f"{url}: {res}"

    with subtest("the box's IP and mDNS name land on the dashboard"):
        # bare IP: no certificate can name it (accepted, see devguide tls.md) → -k
        machine.succeed("curl -sfk https://127.0.0.1/ | grep -q 'data-health'")
        # mDNS: certificate is valid for <hostname>.local
        machine.succeed("${curl} -sf --resolve survival-kit.local:443:127.0.0.1 https://survival-kit.local/ | grep -q 'data-health'")

    with subtest("down detection: health returns 502 when Kiwix is stopped"):
        machine.succeed("systemctl stop kiwix-serve.service")
        code = machine.succeed("${curl} -s -o /dev/null -w '%{http_code}' https://deck/health/kiwix")
        assert code == "502", f"expected 502, got {code}"
  '';
}
