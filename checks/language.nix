# Layer 3 — Language VM test (local only): the real built-in models translate English ↔ Czech
# over HTTPS, WordNet and Moby answer, a dictionary and a translation model imported in the
# content manager reach the page, the service is confined and keeps working after a reboot.
{
  pkgs,
  self,
  inputs,
  ...
}:
let
  curl = "curl --cacert /var/lib/survival-kit/tls/ca.crt";
  # a small FreeDict-shaped dictionary, made with the unit tests' fixture builder
  testDict = pkgs.runCommand "freedict-tst-eng" { nativeBuildInputs = [ pkgs.python3 ]; } ''
    cp ${../modules/services/content/app}/{content.py,langfiles.py,test_langfiles.py} .
    python3 -c "import test_langfiles as t; t.make_dict('dict.tar.xz', {'zelvicka': 'a little turtle'}, title='Test-English')"
    cp dict.tar.xz $out
  '';
in
pkgs.testers.runNixOSTest {
  name = "language";
  node.specialArgs = { inherit inputs self; };
  nodes.machine = {
    imports = [ (import ./host-node.nix { inherit inputs; }) ];
    virtualisation = {
      diskSize = 4096;
      memorySize = pkgs.lib.mkForce 3072; # two loaded translation models next to the desktop
    };
  };
  testScript =
    { nodes, ... }:
    let
      builtinDir = nodes.machine.survivalKit.services.language.builtinDir;
    in
    ''
      import json
      import shlex
      import time

      LANG = "https://language.deck/api"

      def translate(text, src, dst):
          body = shlex.quote(json.dumps({"text": text, "from": src, "to": dst}))
          out = machine.succeed(f"${curl} -sf -H 'Content-Type: application/json' --data-binary {body} {LANG}/translate")
          return json.loads(out)["text"]

      def get(path):
          return json.loads(machine.succeed(f"${curl} -sf '{LANG}/{path}'"))

      def ready():
          machine.wait_for_unit("survival-kit-language.service")
          machine.wait_for_unit("survival-kit-content.service")
          machine.wait_until_succeeds("${curl} -sf https://language.deck/health")
          machine.wait_until_succeeds("${curl} -sf https://content.deck/health")

      machine.wait_for_unit("multi-user.target")
      ready()

      with subtest("the built-in models translate English and Czech"):
          start = time.time()
          cs = translate("The house is big.", "en", "cs")
          print(f"en→cs: {cs!r} in {time.time() - start:.1f} s")
          assert "dům" in cs.lower(), cs
          start = time.time()
          en = translate("Dům je velký. Voda je život.\n\nStudna je u vesnice.", "cs", "en")
          print(f"cs→en: {en!r} in {time.time() - start:.1f} s")
          assert "house" in en.lower(), en
          assert "\n\n" in en, en  # paragraphs kept
          langs = get("languages")
          assert [lang["code"] for lang in langs["languages"]] == ["cs", "en"], langs
          machine.succeed("${curl} -sf -o /dev/null https://deck/health/language")

      with subtest("dictionary and thesaurus"):
          r = get("define?dict=wordnet&word=House")
          assert any("dwelling" in e or "building" in e for e in r["entries"]), r
          r = get("synonyms?word=big")
          assert "large" in r["words"], r["words"][:20]

      with subtest("imports reach the page"):
          up = "${curl} -sf -X PUT --data-binary @{} 'https://content.deck/api/upload?kind={}&file={}'"
          machine.succeed(up.format("${testDict}", "dict", "freedict-tst-eng-0.1.dictd.tar.xz"))
          machine.wait_until_succeeds(f"${curl} -sf {LANG}/languages | grep -q tst-eng", timeout=30)
          r = get("define?dict=tst-eng&word=zelvicka")
          assert "a little turtle" in r["entries"][0], r
          machine.succeed(up.format("${builtinDir}/translate/cs_en.argosmodel", "translate", "translate-cs_en-1_9_6.argosmodel"))
          status = json.loads(machine.succeed("${curl} -sf https://content.deck/api/status"))
          assert [m["name"] for m in status["translate"]] == ["cs_en.argosmodel"], status["translate"]
          assert {b["name"]: b["replaced"] for b in status["translate_builtins"]}["cs_en.argosmodel"]
          machine.wait_until_succeeds(f"${curl} -sf {LANG}/languages | grep -q tst-eng", timeout=30)
          assert "house" in translate("Dům je velký.", "cs", "en").lower()  # now the imported copy
          # a model that isn't what its name says is refused
          machine.fail(up.format("${builtinDir}/translate/cs_en.argosmodel", "translate", "de_en.argosmodel"))

      with subtest("confined, cache in /var/cache"):
          dyn = machine.succeed("systemctl show -p DynamicUser --value survival-kit-language").strip()
          assert dyn == "yes", dyn
          pid = machine.succeed("systemctl show -p MainPID --value survival-kit-language").strip()
          machine.fail(f"nsenter -t {pid} -m -- touch /var/lib/survival-kit/data/x")
          machine.succeed("ls /var/cache/survival-kit-language/*/.done")

      with subtest("a reboot keeps it"):
          machine.shutdown()
          machine.start()
          ready()
          assert "dům" in translate("The house is big.", "en", "cs").lower()
          assert get("define?dict=tst-eng&word=zelvicka")["entries"]
    '';
}
