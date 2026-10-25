# Starter ZIMs bundled into the image (fetched once at build time, offline after).
# Attr name = book name = URL (/content/<name>).
# Link rot: download.kiwix.org keeps only recent releases — when a URL 404s on
# a fresh machine, bump the date + hash (`nix store prefetch-file <url>`). ADR-0004.
{ pkgs }:
let
  zim =
    path: hash:
    pkgs.fetchurl {
      url = "https://download.kiwix.org/zim/${path}.zim";
      inherit hash;
    };
in
{
  archlinux_en_all_maxi = zim "other/archlinux_en_all_maxi_2026-10" "sha256-4Mq7KZzinXpg4KZcq00+FNjmC1mV2utgspMrusBOUFs=";
  devdocs_en_man = zim "devdocs/devdocs_en_man_2026-10" "sha256-ifaZ1rd981iEfza9chKe6xt9n58qFsNeVQAF0EzaUaw=";
  devdocs_en_git = zim "devdocs/devdocs_en_git_2026-10" "sha256-n0WN8TWvcj1UJ5sKVc/+hCi09kU63u74MGNaAfY/Wmo=";
  devdocs_en_bash = zim "devdocs/devdocs_en_bash_2026-10" "sha256-6kr7BN35DzE2OCnvn6JIVAXcBb0fxitGJiRf5wwkc10=";
  devdocs_en_nix = zim "devdocs/devdocs_en_nix_2026-10" "sha256-lC2ypbsgMjmK+IttBKvQpm2kMtFHcVsMhI7tyRRtczM=";
}
