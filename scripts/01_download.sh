#!/bin/bash
# ============================================================
# Step 1: YouTube 영상 다운로드 (비디오, 오디오, 썸네일)
# 필요 도구: yt-dlp (brew install yt-dlp)
# ============================================================

set -e

URL="${1:?사용법: $0 <YouTube_URL>}"
OUTPUT_DIR="${2:-.}"

cd "$OUTPUT_DIR"

echo "=== 비디오 + 썸네일 다운로드 ==="
yt-dlp --write-thumbnail \
  -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]" \
  -o "%(title)s.%(ext)s" \
  "$URL"

echo ""
echo "=== 오디오 전용 다운로드 ==="
yt-dlp \
  -f "bestaudio[ext=m4a]/bestaudio" \
  -o "%(title)s_audio.%(ext)s" \
  "$URL"

echo ""
echo "=== 다운로드 완료 ==="
ls -lh "$OUTPUT_DIR"
