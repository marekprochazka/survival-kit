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
  # own books for the content manager (Kiwix lists a book once per internal ID)
  cmZim = mkTestZim "cm-test";
  replaceZim = mkTestZim "cm-replace";
  # every https request trusts the box's own CA (as Firefox does via policy)
  curl = "curl --cacert /var/lib/survival-kit/tls/ca.crt";
in
pkgs.testers.runNixOSTest {
  name = "services";
  node.specialArgs = { inherit inputs self; };
  nodes.machine = {
    imports = [ (import ./host-node.nix { inherit inputs; }) ];
    environment.systemPackages = [ pkgs.openssl ]; # test-only: inspect certificates
    # the content manager always keeps ≥ 2 GiB free; the default 1 GB test disk can't
    virtualisation.diskSize = 4096;
    # no real model can run in the test VM: the chat and lookup talk to a stand-in
    survivalKit.services.chat.ollamaUrl = "http://127.0.0.1:11500";
    systemd.services.fake-ollama = {
      wantedBy = [ "multi-user.target" ];
      before = [ "survival-kit-chat.service" ];
      serviceConfig.ExecStart = "${pkgs.python3}/bin/python3 ${./fake-ollama.py}";
    };
  };
  testScript = ''
    import json

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

    with subtest("Vaultwarden (passwords)"):
        machine.wait_for_unit("vaultwarden.service")
        machine.wait_until_succeeds("${curl} -sf -o /dev/null https://vault.deck/alive", timeout=60)
        machine.succeed("${curl} -sf https://vault.deck/ | grep -q '<title page-title>Vaultwarden Web</title>'")  # the web vault
        machine.succeed("${curl} -sf -o /dev/null https://deck/health/vault")
        names = machine.succeed("openssl x509 -in /var/lib/survival-kit/tls/deck.crt -noout -ext subjectAltName")
        assert "DNS:vault.deck" in names, names
        page = machine.succeed("${curl} -sf https://deck/")
        assert page.index("Wiki") < page.index("Passwords") < page.index("Manual"), "tile order"
        assert 'href="https://vault.deck/"' in page, "Passwords tile link"
        # backup: one copy in latest/, a dated copy per day (running twice keeps one)
        machine.succeed("systemctl start backup-vaultwarden.service")
        machine.succeed("systemctl start backup-vaultwarden.service")
        machine.succeed("test -s /var/backup/vaultwarden/latest/db.sqlite3")
        machine.succeed("test -s /var/backup/vaultwarden/daily/$(date +%F)/db.sqlite3")
        assert machine.succeed("ls /var/backup/vaultwarden/daily | wc -l").strip() == "1"

    with subtest("Ollama (local AI)"):
        machine.wait_for_unit("ollama.service")
        machine.wait_for_open_port(11434)
        machine.succeed("curl -sf http://127.0.0.1:11434/api/version | grep -q version")
        # the CLI as the owner, against the system service; no model yet → empty list
        machine.succeed("su - deck -c 'ollama list'")

    with subtest("Content manager: import, replace a built-in, delete"):
        CM = "${curl} -sf https://content.deck"
        machine.wait_until_succeeds(CM + "/health")

        def upload(name, src):
            # -s without -f: on a refusal the service's message ends up in the test log
            r = machine.succeed("${curl} -s https://content.deck/api/upload?kind=wiki\\&file=" + name + " -T " + src)
            assert '"result"' in r, r

        n = books()
        # a Kiwix-style dated name is stored under its clean name
        upload("cm-test_2026-01.zim", "${cmZim}")
        wait_books(n + 1)
        machine.succeed("test -f " + ZIMS + "/cm-test.zim")
        machine.succeed(CM + "/api/wiki/cm-test.zim -X DELETE")
        wait_books(n)
        # an import named like a built-in book replaces it; deleting brings it back
        upload("devdocs_en_git.zim", "${replaceZim}")
        machine.wait_until_succeeds("${curl} -sfL https://wiki.deck/content/devdocs_en_git | grep -q 'cm-replace test page'")
        assert books() == n, "a replaced built-in must not count twice"
        machine.succeed(CM + "/api/wiki/devdocs_en_git.zim -X DELETE")
        machine.wait_until_succeeds("! ${curl} -sfL https://wiki.deck/content/devdocs_en_git | grep -q 'cm-replace test page'")
        wait_books(n)
        # refusals and the models section (full)
        machine.fail(CM + "/api/upload?kind=wiki\\&file=survival-kit.zim -T ${dropinZim}")
        status = machine.succeed(CM + "/api/status")
        assert '"models": []' in status, status
        # the real `ollama create` path inside the sandboxed service: a junk .gguf must be
        # rejected by Ollama itself ("Error: …"), not crash the CLI (it needs a $HOME)
        r = machine.succeed("${curl} -s https://content.deck/api/upload?kind=model\\&file=junk.gguf -T /etc/hostname")
        assert "could not be added" in r and "panic" not in r and "main.go" not in r, r
        machine.succeed("test -z \"$(ls -A " + ZIMS + "/.incoming)\"")

    with subtest("Wiki lookup, MCP and the wiki-first chat"):
        machine.wait_for_unit("survival-kit-lookup.service")
        machine.wait_for_unit("survival-kit-chat.service")
        machine.wait_for_open_port(8310)
        machine.succeed("curl -sf http://127.0.0.1:8310/invalidate -X POST -H 'Content-Type: application/json' -d '{}'")
        assert "dropin-test" in machine.succeed("curl -sf http://127.0.0.1:8310/books")
        found = json.loads(machine.succeed(
            "curl -sf http://127.0.0.1:8310/lookup -H 'Content-Type: application/json'"
            " -d '{\"question\": \"dropin-test test page\", \"model\": \"test-model\", \"history\": []}'"))
        assert found["error"] is None, found
        assert any("/content/dropin-test/" in a["url"] for a in found["articles"]), found
        # MCP over stdio, as oterm/mcphost would call it
        out = machine.succeed(
            "printf '%s\\n' '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-06-18\"}}'"
            " '{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"wiki_search\",\"arguments\":{\"words\":\"dropin-test\"}}}'"
            " | survival-kit-wiki-mcp")
        assert "https://wiki.deck/content/dropin-test/" in out, out
        # the chat: ask → the answer is stored with its sources
        CH = "${curl} -sf https://chat.deck/api"
        J = " -H 'Content-Type: application/json' -d "
        chat = json.loads(machine.succeed(CH + "/chats" + J + "'{\"model\": \"test-model\"}'"))["id"]
        job = json.loads(machine.succeed(CH + f"/chats/{chat}/ask" + J
            + "'{\"question\": \"dropin-test test page\", \"model\": \"test-model\"}'"))["job"]
        # a second question while the first is written waits in the queue
        other = json.loads(machine.succeed(CH + "/chats" + J + "'{\"model\": \"test-model\"}'"))["id"]
        job2 = json.loads(machine.succeed(CH + f"/chats/{other}/ask" + J
            + "'{\"question\": \"dropin-test\", \"model\": \"test-model\"}'"))["job"]
        replay = machine.succeed("${curl} -s --max-time 3 https://chat.deck/api/jobs/" + str(job2) + "/events || true")
        assert '"state": "queued"' in replay, replay
        machine.wait_until_succeeds(CH + f"/chats/{chat} | grep -q 'this is a test page'", timeout=120)
        msgs = json.loads(machine.succeed(CH + f"/chats/{chat}"))["messages"]
        assert msgs[-1]["role"] == "assistant" and not msgs[-1]["notice"], msgs
        assert any("/content/dropin-test/" in s["url"] for s in msgs[-1]["sources"]), msgs
        machine.wait_until_succeeds(CH + f"/chats/{other} | grep -q 'this is a test page'", timeout=120)
        assert "https://chat.deck/" in machine.succeed("${curl} -sf https://deck/")  # the tile

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
