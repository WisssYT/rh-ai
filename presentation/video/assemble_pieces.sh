#!/usr/bin/env bash
# Resumable assembly: encode each piece on its own (skipped if already done), then join losslessly
# and add the soundtrack. Same cut list as assemble.sh.
set -euo pipefail
cd "$(dirname "$0")"
FF="${FFMPEG:-ffmpeg}"
MIX="${MIX:-../edit/final_mix.wav}"
mkdir -p pieces
[ -s live.mp4 ]  || { printf "file 'liveA.mp4'\nfile 'liveB.mp4'\nfile 'liveC.mp4'\n" > live_list.txt; "$FF" -y -loglevel error -f concat -safe 0 -i live_list.txt -c copy live.mp4; }
[ -s live2.mp4 ] || { printf "file 'live2A.mp4'\nfile 'live2B.mp4'\n" > live2_list.txt; "$FF" -y -loglevel error -f concat -safe 0 -i live2_list.txt -c copy live2.mp4; }
# n  source               from   to
PIECES="
01 s1new.mp4               0     4.5
02 s2.mp4                  0     8
03 talent-detective-pitch.mp4 17 26
04 live2.mp4               0     34
05 talent-detective-pitch.mp4 26 41
06 live2.mp4               34    46
07 live.mp4                0     15.5
08 talent-detective-pitch.mp4 41 55
09 live.mp4                15.5  32.5
10 talent-detective-pitch.mp4 55 71
11 live.mp4                32.5  64.5
12 live2.mp4               46    97
13 followups_fix.mp4       0     16
14 live2.mp4               113   125
15 talent-detective-pitch.mp4 71 82
16 s8.mp4                  0     11
17 talent-detective-pitch.mp4 93 110
"
: > pieces/list.txt
while read -r n src a b; do
  [ -z "$n" ] && continue
  out="pieces/p$n.mp4"
  if [ ! -s "$out.ok" ]; then
    "$FF" -nostdin -y -loglevel error -i "$src" -vf "trim=$a:$b,setpts=PTS-STARTPTS,fps=30,format=yuv420p" -an \
      -c:v libx264 -preset veryfast -crf 19 -g 60 -video_track_timescale 15360 "$out.tmp.mp4"
    mv "$out.tmp.mp4" "$out"; echo ok > "$out.ok"; echo "piece $n done"
  fi
  echo "file 'p$n.mp4'" >> pieces/list.txt
done <<< "$PIECES"
"$FF" -y -loglevel error -f concat -safe 0 -i pieces/list.txt -i "$MIX" -map 0:v -map 1:a -c:v copy \
  -c:a aac -b:a 192k -ar 48000 -shortest -movflags +faststart talent-detective-pitch-5min.mp4
echo done
