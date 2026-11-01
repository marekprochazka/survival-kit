# Tiny generated media for the Media VM test: 2-second films (H.264 + AAC, H.264 + AC3)
# and two tagged tracks (FLAC, MP3) of one album. Made with ffmpeg at build time.
{ pkgs }:
pkgs.runCommand "test-media" { nativeBuildInputs = [ pkgs.ffmpeg-headless ]; } ''
  mkdir $out
  video="-f lavfi -i testsrc=duration=2:size=160x120:rate=10"
  tone="-f lavfi -i sine=frequency=440:duration=2"
  ffmpeg -loglevel error $video $tone -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest $out/film.mp4
  ffmpeg -loglevel error $video $tone -c:v libx264 -pix_fmt yuv420p -c:a ac3 -shortest $out/ac3.mkv
  tags="-metadata artist=Tester -metadata album=Test_Album"
  ffmpeg -loglevel error $tone $tags -metadata title=One -metadata track=1 $out/01.flac
  ffmpeg -loglevel error $tone $tags -metadata title=Two -metadata track=2 -c:a libmp3lame $out/02.mp3
''
