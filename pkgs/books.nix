# The survival-kit books for the offline wiki: Markdown → HTML (lowdown) → ZIM
# (zimwriterfs). Each book is a directory of *.md pages plus _header.html and
# _footer.html; style and icon are shared (from manual/).
# Build alone: nix build .#survival-kit-manual  /  nix build .#survival-kit-devguide
{
  runCommand,
  lowdown,
  zim-tools,
}:
let
  # Placeholders filled at build time — one source instead of a hand copy in the pages.
  # @MAPS_DATE@: the date of the built-in maps (reading .date doesn't fetch the map files)
  mapsDate =
    let
      d = (import ../modules/services/maps/builtins.nix { pkgs = null; }).date; # YYYYMMDD
    in
    "${builtins.substring 0 4 d}-${builtins.substring 4 2 d}-${builtins.substring 6 2 d}";
  mkBook =
    {
      name, # book name = URL: https://wiki.<domain>/content/<name>
      title,
      description,
      src,
    }:
    runCommand "${name}.zim"
      {
        nativeBuildInputs = [
          lowdown
          zim-tools
        ];
      }
      ''
        mkdir site
        cp ${../manual/style.css} site/style.css
        cp ${../manual/icon.png} site/icon.png
        for md in ${src}/*.md; do
          page=$(basename "$md" .md)
          { cat ${src}/_header.html; sed 's/@MAPS_DATE@/${mapsDate}/g' "$md" | lowdown -thtml; cat ${src}/_footer.html; } > "site/$page.html"
        done
        zimwriterfs --name ${name} --title "${title}" --description "${description}" \
          --creator survival-kit --publisher survival-kit --language eng \
          --welcome index.html --illustration icon.png site $out
      '';
in
{
  manual = mkBook {
    name = "survival-kit";
    title = "survival-kit manual";
    description = "How to use and maintain this survival-kit";
    src = ../manual;
  };
  devguide = mkBook {
    name = "survival-kit-dev";
    title = "survival-kit developer guide";
    description = "How survival-kit is built, and how to change it";
    src = ../devguide;
  };
}
