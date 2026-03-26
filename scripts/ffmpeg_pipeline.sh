#!/bin/bash
# SportsCaster Pro v2 - FFmpeg Overlay + Stream Pipeline
# Usage: ./ffmpeg_pipeline.sh [CAM_SOURCE] [STREAM_KEY] [PLATFORM]
# Example: ./ffmpeg_pipeline.sh 0 my-key youtube

CAM="${1:-0}"
KEY="${2:-}"
PLATFORM="${3:-youtube}"
BITRATE="2500k"
FPS=30
RES="1280x720"
OVERLAY="../overlay/overlay_static.png"

[ "$PLATFORM" = "youtube" ]  && RTMP="rtmp://a.rtmp.youtube.com/live2/${KEY}"
[ "$PLATFORM" = "facebook" ] && RTMP="rtmps://live-api-s.facebook.com:443/rtmp/${KEY}"
[ "$PLATFORM" = "custom" ]   && RTMP="${KEY}"

echo "Platform: ${PLATFORM}  Camera: ${CAM}"

# Encoder
ENC="libx264 -preset ultrafast -tune zerolatency"
ffmpeg -encoders 2>/dev/null | grep -q h264_v4l2m2m && ENC="h264_v4l2m2m"

# Camera input
if [[ "$CAM" == http* ]]; then
  CAM_FLAGS="-i ${CAM}"
elif [[ "$(uname)" == "Linux" ]]; then
  CAM_FLAGS="-f v4l2 -framerate ${FPS} -video_size ${RES} -i /dev/video${CAM}"
else
  CAM_FLAGS="-f dshow -i video=${CAM}"
fi

# Overlay
if [ -f "$OVERLAY" ]; then
  OV_FLAGS="-loop 1 -i ${OVERLAY}"
  FILTER="-filter_complex [0:v][1:v]overlay=0:0[out] -map [out]"
else
  OV_FLAGS=""; FILTER="-map 0:v"
fi

ffmpeg -re ${CAM_FLAGS} ${OV_FLAGS} ${FILTER} \
  -map 0:a? -vcodec ${ENC} \
  -b:v ${BITRATE} -maxrate ${BITRATE} -bufsize 5000k \
  -g $((FPS*2)) -acodec aac -b:a 128k -ar 44100 \
  -f flv "${RTMP}"
