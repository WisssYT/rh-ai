#!/usr/bin/env bash
# Assemble the 5-minute cut from rendered pieces:
#   talent-detective-pitch.mp4  motion film (110 s)        s2.mp4 / s8.mp4  re-rendered motion scenes 9-17 s and 82-93 s
#   live.mp4  = liveA+liveB+liveC (64.5 s)                 live2.mp4 = live2A+live2B (125 s)
set -euo pipefail
cd "$(dirname "$0")"
FF="${FFMPEG:-ffmpeg}"
printf "file 'liveA.mp4'\nfile 'liveB.mp4'\nfile 'liveC.mp4'\n" > live_list.txt
"$FF" -y -loglevel error -f concat -safe 0 -i live_list.txt -c copy live.mp4
printf "file 'live2A.mp4'\nfile 'live2B.mp4'\n" > live2_list.txt
"$FF" -y -loglevel error -f concat -safe 0 -i live2_list.txt -c copy live2.mp4
# inputs: 0 film, 1 s2, 2 s8, 3 live, 4 live2, 5 followups_fix (re-render of live2 97-113 s)
"$FF" -y -loglevel error -i talent-detective-pitch.mp4 -i s2.mp4 -i s8.mp4 -i live.mp4 -i live2.mp4 -i followups_fix.mp4 -filter_complex "
[0:v]trim=0:9,setpts=PTS-STARTPTS[p1];
[1:v]trim=0:8,setpts=PTS-STARTPTS[p2];
[0:v]trim=17:26,setpts=PTS-STARTPTS[p3];
[4:v]trim=0:34,setpts=PTS-STARTPTS[p4];
[0:v]trim=26:41,setpts=PTS-STARTPTS[p5];
[4:v]trim=34:46,setpts=PTS-STARTPTS[p6];
[3:v]trim=0:15.5,setpts=PTS-STARTPTS[p7];
[0:v]trim=41:55,setpts=PTS-STARTPTS[p8];
[3:v]trim=15.5:32.5,setpts=PTS-STARTPTS[p9];
[0:v]trim=55:71,setpts=PTS-STARTPTS[p10];
[3:v]trim=32.5:64.5,setpts=PTS-STARTPTS[p11];
[4:v]trim=46:97,setpts=PTS-STARTPTS[p12a];
[5:v]trim=0:16,setpts=PTS-STARTPTS[p12b];
[4:v]trim=113:125,setpts=PTS-STARTPTS[p12c];
[0:v]trim=71:82,setpts=PTS-STARTPTS[p13];
[2:v]trim=0:11,setpts=PTS-STARTPTS[p14];
[0:v]trim=93:110,setpts=PTS-STARTPTS[p15];
[p1][p2][p3][p4][p5][p6][p7][p8][p9][p10][p11][p12a][p12b][p12c][p13][p14][p15]concat=n=17:v=1:a=0,fps=30[out]" \
  -map "[out]" -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p -movflags +faststart talent-detective-pitch-5min.mp4
echo done
