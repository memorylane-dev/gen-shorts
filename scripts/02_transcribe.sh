#!/bin/bash
# ============================================================
# Step 2: Whisper로 음성 → 자막(SRT/TXT) 추출
# 필요 도구: python3, mlx-whisper (pip install mlx-whisper)
# Apple Silicon Mac 최적화 버전 사용
# ============================================================

set -e

AUDIO_FILE="${1:?사용법: $0 <오디오파일.m4a> [출력이름]}"
OUTPUT_NAME="${2:-subtitle}"

# 가상환경이 있으면 활성화
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

python3 << 'PYEOF'
import mlx_whisper
import sys, os

audio_file = sys.argv[1]
output_name = sys.argv[2]

print(f"Transcribing: {audio_file}")
print(f"Model: whisper-large-v3-turbo (mlx)")

result = mlx_whisper.transcribe(
    audio_file,
    path_or_hf_repo="mlx-community/whisper-large-v3-turbo",
    language="ko",
    word_timestamps=True,
    verbose=False
)

# SRT 포맷 저장
def to_srt(segments):
    lines = []
    for i, seg in enumerate(segments, 1):
        start = seg["start"]
        end = seg["end"]
        text = seg["text"].strip()
        sh, sm, ss = int(start//3600), int((start%3600)//60), start%60
        eh, em, es = int(end//3600), int((end%3600)//60), end%60
        lines.append(f"{i}")
        lines.append(
            f"{sh:02d}:{sm:02d}:{ss:06.3f}".replace(".",",")
            + " --> "
            + f"{eh:02d}:{em:02d}:{es:06.3f}".replace(".",",")
        )
        lines.append(text)
        lines.append("")
    return "\n".join(lines)

srt = to_srt(result["segments"])
srt_path = f"{output_name}.srt"
with open(srt_path, "w", encoding="utf-8") as f:
    f.write(srt)

# 타임스탬프 포함 텍스트 저장
txt_path = f"{output_name}.txt"
with open(txt_path, "w", encoding="utf-8") as f:
    for seg in result["segments"]:
        m, s = int(seg["start"]//60), int(seg["start"]%60)
        f.write(f'[{m:02d}:{s:02d}] {seg["text"].strip()}\n')

print(f"SRT 저장: {srt_path}")
print(f"TXT 저장: {txt_path}")
print(f"총 {len(result['segments'])}개 세그먼트 추출 완료")
PYEOF
"$AUDIO_FILE" "$OUTPUT_NAME"
