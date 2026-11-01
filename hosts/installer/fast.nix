# The installer ISO for quick VirtualBox tests: the same system, light compression — builds
# much faster, the file is bigger. Never a release (the name ends in -fast).
# Build: utils/build-iso --fast
{
  isoImage.squashfsCompression = "zstd -Xcompression-level 3";
  survivalKit.isoSuffix = "-fast";
}
