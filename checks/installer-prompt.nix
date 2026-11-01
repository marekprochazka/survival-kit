# Layer 3 — installer prompt VM test (local only). Runs survival-kit-install INSIDE a bare
# VM with a blank test disk: a typo at the profile prompt is asked again (never a silent
# default), the profile text is current, and a wrong name at the confirm step aborts with
# the disk untouched. The installer is never run outside a VM.
{
  pkgs,
  self,
  inputs,
  ...
}:
let
  installer = pkgs.callPackage ../pkgs/survival-kit-install.nix {
    flakeSrc = self;
    inherit (inputs.disko.packages.${pkgs.stdenv.hostPlatform.system}) disko;
  };
in
pkgs.testers.runNixOSTest {
  name = "installer-prompt";
  nodes.machine = {
    virtualisation.emptyDiskImages = [ 64 ]; # /dev/vdb — the only disk offered
    environment.systemPackages = [ installer ];
  };
  testScript = ''
    machine.wait_for_unit("multi-user.target")
    # disk, encryption, three bad profile answers, lite, then a wrong confirm name → abort
    answers = r"vdb\nn\nFull\nful\n\nlite\nwrong\n"
    out = machine.fail(f"printf '{answers}' | survival-kit-install 2>&1")
    print(out)
    assert out.count("Please type exactly: lite or full") == 3, "each bad answer is asked again"
    assert "lite — wiki, maps, language, passwords, files, inventory" in out, "current lite text"
    assert "Profile: lite, encrypted: false" in out
    assert "Aborted — nothing was changed." in out
    # the disk is untouched: no partition table, no filesystem signature
    assert machine.succeed("wipefs --no-act /dev/vdb").strip() == "", "the disk was written to"
  '';
}
