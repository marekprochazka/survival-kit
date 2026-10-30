# Tiny ZIMs for VM tests: one page "<name> test page" (zimwriterfs requires a 48x48
# illustration). Kiwix lists a book once per internal ID, so each test book is built anew.
{ pkgs }:
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
  ''
