# survival-kit end-user manual: manual/*.md → HTML (lowdown) → survival-kit.zim.
# Build/inspect alone: nix build .#survival-kit-manual
{
  runCommand,
  lowdown,
  zim-tools,
}:
let
  src = ../manual;
in
runCommand "survival-kit-manual.zim"
  {
    nativeBuildInputs = [
      lowdown
      zim-tools
    ];
  }
  ''
    mkdir site
    cp ${src}/style.css ${src}/icon.png site/
    for md in ${src}/*.md; do
      page=$(basename "$md" .md)
      { cat ${src}/_header.html; lowdown -thtml "$md"; cat ${src}/_footer.html; } > "site/$page.html"
    done
    zimwriterfs --name survival-kit --title "survival-kit manual" \
      --description "How to use and maintain this survival-kit" \
      --creator survival-kit --publisher survival-kit --language eng \
      --welcome index.html --illustration icon.png site $out
  ''
