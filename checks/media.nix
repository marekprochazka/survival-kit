# Layer 3 — Media VM test (local only): Jellyfin behind nginx — the one-time setup with the
# owner's name and password, libraries and starting settings, imports through the Content
# page, an item already in place with extra files, watch progress across a library rebuild,
# a setting the owner changes surviving a restart (set once), deleting.
{
  pkgs,
  self,
  inputs,
  ...
}:
let
  curl = "curl --cacert /var/lib/survival-kit/tls/ca.crt";
  fixtures = import ./test-media.nix { inherit pkgs; };
in
pkgs.testers.runNixOSTest {
  name = "media";
  node.specialArgs = { inherit inputs self; };
  nodes.machine = {
    imports = [ (import ./host-node.nix { inherit inputs; }) ];
    virtualisation.memorySize = pkgs.lib.mkForce 3072; # + Jellyfin
    virtualisation.diskSize = 4096;
  };
  testScript = ''
    import json
    import re
    import shlex
    import urllib.parse

    JF = "https://media.deck"
    CT = "https://content.deck"
    FX = "${fixtures}"
    CLIENT = 'MediaBrowser Client="test", Device="vm", DeviceId="media-test", Version="1"'
    NAME, PASSWORD = "Anna Nováková", "secret pw"

    def jf(method, path, token=None, data=None, code=False):
        auth = CLIENT + (f', Token="{token}"' if token else "")
        body = f"-H 'Content-Type: application/json' --data-binary {shlex.quote(json.dumps(data))}" if data is not None else ""
        if code:
            return machine.succeed(f"${curl} -s -o /dev/null -w '%{{http_code}}' -X {method} -H {shlex.quote('Authorization: ' + auth)} {body} '{JF}{path}'").strip()
        out = machine.succeed(f"${curl} -sf -X {method} -H {shlex.quote('Authorization: ' + auth)} {body} '{JF}{path}'")
        return json.loads(out) if out.strip() else None

    def content(method, path, file=None):
        data = f"--data-binary @{file}" if file else "--data-binary @/dev/null"
        return json.loads(machine.succeed(f"${curl} -sf -X {method} {data} '{CT}{path}'"))

    def import_media(kind, fields, files):
        total = sum(int(machine.succeed(f"stat -c %s {f}")) for _, f in files)
        q = urllib.parse.urlencode({"type": kind, "size": total, **fields})
        b = content("POST", f"/api/media/begin?{q}")
        for name, f in files:
            content("PUT", f"/api/media/upload?batch={b['batch']}&file={urllib.parse.quote(name)}", f)
        return content("POST", f"/api/media/finish?batch={b['batch']}")

    def items(token, kind):
        r = jf("GET", f"/Items?Recursive=true&IncludeItemTypes={kind}&Fields=Path", token)
        return {i["Name"]: i for i in r["Items"]}

    def wait_items(token, kind, present=(), absent=()):
        for _ in range(60):
            got = items(token, kind)
            if all(n in got for n in present) and not any(n in got for n in absent):
                return got
            machine.sleep(2)
        raise AssertionError(f"{kind}: wanted {present}, not {absent}; have {list(got)}")

    machine.wait_for_unit("jellyfin.service")
    machine.wait_for_unit("nginx.service")

    with subtest("up, healthy, on the dashboard, nothing from other hosts"):
        machine.wait_until_succeeds(f"${curl} -sf {JF}/health | grep -q Healthy", timeout=180)
        machine.succeed("${curl} -sf -o /dev/null https://deck/health/media")
        assert 'href="https://media.deck/"' in machine.succeed("${curl} -sf https://deck/"), "Media tile"
        page = machine.succeed(f"${curl} -sfL {JF}/web/")
        refs = re.findall(r'(?:src|href)="([^"]+)"', page)
        external = [r for r in refs if re.match(r"(https?:)?//", r)]
        assert not external, f"Jellyfin's page references other hosts: {external}"
        machine.fail("ss -ltn | grep -E '0.0.0.0:8096|\\[::\\]:8096'")  # 127.0.0.1 only

    with subtest("one-time setup with the owner's name and password"):
        machine.succeed(f"printf '%s\\n%s\\n' {shlex.quote(NAME)} {shlex.quote(PASSWORD)} | survival-kit-media-setup")
        assert machine.succeed("stat -c '%a %U' /var/lib/survival-kit/media/api-key").strip() == "600 root"
        auth = jf("POST", "/Users/AuthenticateByName", data={"Username": NAME, "Pw": PASSWORD})
        token, uid = auth["AccessToken"], auth["User"]["Id"]
        assert jf("GET", "/System/Info/Public")["StartupWizardCompleted"] is True
        assert jf("GET", "/Startup/User", code=True) == "401", "the wizard is closed"
        code = machine.execute("printf 'x\\ny\\n' | survival-kit-media-setup")[0]
        assert code == 2, f"a second run changes nothing (exit 2), got {code}"

    with subtest("libraries and starting settings"):
        libs = {f["Name"]: f for f in jf("GET", "/Library/VirtualFolders", token)}
        assert {n: libs[n]["Locations"] for n in libs} == {
            "Movies": ["/var/lib/survival-kit/library/media/movies"],
            "Shows": ["/var/lib/survival-kit/library/media/shows"],
            "Music": ["/var/lib/survival-kit/library/media/music"],
        }, libs
        for f in libs.values():
            o = f["LibraryOptions"]
            assert not o["EnableRealtimeMonitor"] and not o["EnableTrickplayImageExtraction"], o
            assert all(t["MetadataFetchers"] == [] for t in o["TypeOptions"]), o["TypeOptions"]
        policy = jf("GET", f"/Users/{uid}", token)["Policy"]
        assert (policy["EnableVideoPlaybackTranscoding"], policy["EnableAudioPlaybackTranscoding"]) == (False, True)
        assert jf("GET", "/System/Configuration", token)["PluginRepositories"] == []

    with subtest("imports through the Content page show up in Jellyfin"):
        r = import_media("film", {"title": "The Kid", "year": "1921"}, [("The.Kid.mp4", f"{FX}/film.mp4")])
        assert r["result"] == "added", r
        import_media("film", {"title": "Loud", "year": ""}, [("loud.mkv", f"{FX}/ac3.mkv")])
        import_media("music", {"name": "Test Album"}, [("01 One.flac", f"{FX}/01.flac"), ("02 Two.mp3", f"{FX}/02.mp3")])
        films = wait_items(token, "Movie", present=["The Kid (1921)", "Loud"])
        assert films["The Kid (1921)"]["Path"].startswith("/var/lib/survival-kit/library/media/movies/"), films["The Kid (1921)"]
        wait_items(token, "Audio", present=["One", "Two"])

    with subtest("an item already in place: extra files and any name are fine"):
        d = "/var/lib/survival-kit/data/media/movies/Odd: Name (2020)"
        machine.succeed(f"mkdir -p {shlex.quote(d)}/Sample")
        machine.succeed(f"cp {FX}/film.mp4 {shlex.quote(d)}/odd.mp4")
        machine.succeed(f"cp {FX}/film.mp4 {shlex.quote(d)}/Sample/s.mp4")
        machine.succeed(f"echo '<movie/>' > {shlex.quote(d)}/odd.nfo")
        machine.succeed("systemctl restart survival-kit-library")
        wait_items(token, "Movie", present=["odd"])  # offline, the video file names the film
        status = content("GET", "/api/status")
        odd = [m for m in status["media"] if m["name"] == "movies/Odd: Name (2020)"]
        assert odd and odd[0]["status"] == "in_use", status["media"]
        assert content("POST", "/api/resolve?at=device")["moved"] == [], "nothing set aside"

    with subtest("watch progress survives a library rebuild"):
        kid = items(token, "Movie")["The Kid (1921)"]["Id"]
        jf("POST", f"/UserPlayedItems/{kid}?userId={uid}", token)
        machine.succeed("systemctl restart survival-kit-library")
        machine.sleep(10)
        again = jf("GET", f"/Items?Ids={kid}&userId={uid}&Recursive=true", token)["Items"]
        assert again and again[0]["UserData"]["Played"], f"lost after the rebuild: {again}"

    with subtest("set once: a setting the owner changes stays after a restart"):
        policy = jf("GET", f"/Users/{uid}", token)["Policy"]
        policy["EnableVideoPlaybackTranscoding"] = True
        jf("POST", f"/Users/{uid}/Policy", token, policy)
        machine.succeed("systemctl restart jellyfin")
        machine.wait_until_succeeds(f"${curl} -sf {JF}/health | grep -q Healthy", timeout=120)
        assert jf("GET", f"/Users/{uid}", token)["Policy"]["EnableVideoPlaybackTranscoding"] is True

    with subtest("deleting on the Content page removes it from Jellyfin"):
        quoted = urllib.parse.quote("movies/The Kid (1921)", safe="")
        assert content("DELETE", f"/api/media/{quoted}?at=device")["result"] == "deleted"
        wait_items(token, "Movie", present=["Loud"], absent=["The Kid (1921)"])

    with subtest("memory (for the docs)"):
        print("jellyfin MemoryCurrent:", machine.succeed("systemctl show -p MemoryCurrent --value jellyfin").strip())
  '';
}
