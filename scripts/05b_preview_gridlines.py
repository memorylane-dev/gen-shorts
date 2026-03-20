#!/usr/bin/env python3
"""
Step 5b: 크롭 기준선 미리보기
- 원본 프레임에 번호 매긴 세로 기준선을 균등 분할로 표시
- 사용자가 "2번~5번 사이로 잘라줘" 식으로 크롭 범위 지정 가능
- 9:16 비율에 딱 맞추지 않아도 됨 (위아래 검은 여백 허용)

사용법:
  python3 05b_preview_gridlines.py --input 영상.mp4 --clips clips.txt [--divisions 10]
"""

import subprocess
import os
import argparse


def ts_to_sec(ts):
    parts = ts.replace(",", ".").split(":")
    return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])


def get_video_dimensions(input_video):
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0",
        input_video
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    w, h = result.stdout.strip().split(",")
    return int(w), int(h)


def parse_clips_file(path):
    clips = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            if len(parts) >= 3:
                clips.append((parts[0].strip(), parts[1].strip(), parts[2].strip()))
    return clips


def generate_gridline_preview(input_video, clip_ss, clip_duration, output_name, src_w, src_h, divisions, outdir):
    """기준선이 그려진 프레임 캡처 (시작 + 중간)"""
    base = os.path.splitext(output_name)[0]
    interval = src_w / divisions

    clip_start_sec = ts_to_sec(clip_ss)
    clip_dur_sec = ts_to_sec(clip_duration)
    mid_sec = clip_start_sec + clip_dur_sec / 2

    timestamps = [
        (clip_ss, "start"),
        (f"00:{int(mid_sec//60):02d}:{mid_sec%60:06.3f}", "mid"),
    ]

    for ts, label in timestamps:
        # drawbox로 세로선 + drawtext로 번호
        filters = []
        for i in range(divisions + 1):
            x = int(i * interval)
            if x >= src_w:
                x = src_w - 1

            # 세로선 (짝수=노란색, 홀수=하얀색)
            color = "yellow" if i % 2 == 0 else "white"
            filters.append(
                f"drawbox=x={x}:y=0:w=2:h={src_h}:color={color}@0.8:t=fill"
            )

            # 번호 라벨
            label_x = x + 5 if x < src_w - 50 else x - 40
            filters.append(
                f"drawtext=text='{i}'"
                f":fontsize=36"
                f":fontcolor={color}"
                f":borderw=2:bordercolor=black"
                f":x={label_x}:y=20"
                f":fontfile=/System/Library/Fonts/AppleSDGothicNeo.ttc"
            )
            # 하단에도 번호
            filters.append(
                f"drawtext=text='{i}'"
                f":fontsize=36"
                f":fontcolor={color}"
                f":borderw=2:bordercolor=black"
                f":x={label_x}:y={src_h - 50}"
                f":fontfile=/System/Library/Fonts/AppleSDGothicNeo.ttc"
            )

        # 픽셀 좌표 안내 (상단 중앙)
        info_text = f"width={src_w}  divisions={divisions}  interval={interval:.0f}px"
        filters.append(
            f"drawtext=text='{info_text}'"
            f":fontsize=24"
            f":fontcolor=white"
            f":borderw=2:bordercolor=black"
            f":x=(w-text_w)/2:y={src_h//2}"
            f":fontfile=/System/Library/Fonts/AppleSDGothicNeo.ttc"
        )

        vf = ",".join(filters)
        output_path = os.path.join(outdir, f"{base}_grid_{label}.jpg")

        subprocess.run([
            "ffmpeg", "-y", "-ss", ts, "-i", input_video,
            "-frames:v", "1", "-vf", vf,
            "-q:v", "2", output_path
        ], capture_output=True, text=True)

        if os.path.exists(output_path):
            print(f"    {label}: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="크롭 기준선 미리보기")
    parser.add_argument("--input", "-i", required=True, help="원본 영상 파일")
    parser.add_argument("--clips", "-c", required=True, help="클립 목록 파일")
    parser.add_argument("--outdir", "-o", default="previews", help="출력 디렉토리")
    parser.add_argument("--divisions", "-d", type=int, default=10, help="분할 수 (기본: 10)")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    src_w, src_h = get_video_dimensions(args.input)
    clips = parse_clips_file(args.clips)

    print(f"원본: {src_w}x{src_h}")
    print(f"분할: {args.divisions}등분 ({src_w // args.divisions}px 간격)")
    print(f"사용법: '2번~5번 사이로 잘라줘' → 크롭 x={int(2 * src_w / args.divisions)}~{int(5 * src_w / args.divisions)}\n")

    for ss, t, name in clips:
        print(f"  [{name}]")
        generate_gridline_preview(args.input, ss, t, name, src_w, src_h, args.divisions, args.outdir)

    print(f"\n=== 기준선 미리보기 완료 ===")
    print(f"'{args.outdir}/' 폴더에서 확인하세요.")
    print(f"원하는 범위를 알려주세요 (예: '1번 클립은 2~6, 나머지는 3~7')")


if __name__ == "__main__":
    main()
