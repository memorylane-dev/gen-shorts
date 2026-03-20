#!/usr/bin/env python3
"""
Step 3a: 크롭 미리보기 시트 생성
- 각 클립마다 한 장의 비교 시트를 생성:
  상단: 원본 와이드 프레임 + 왼쪽/중앙/오른쪽 크롭 영역 표시
  하단: 세 가지 크롭 결과를 나란히 비교
- 한눈에 어떤 크롭 위치가 적절한지 판단 가능

사용법:
  python3 03_preview_crop.py --input 영상.mp4 --clips clips.txt [--outdir previews]

clips.txt 형식:
  시작시간,길이,출력파일명[,crop_x오프셋]
"""

import subprocess
import os
import argparse
import tempfile
import shutil


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


def calc_crop(src_w, src_h, offset_x=0):
    """9:16 크롭 계산. offset_x로 좌우 위치 조정 가능."""
    target_w = int(src_h * 9 / 16)
    center_x = (src_w - target_w) // 2
    crop_x = max(0, min(src_w - target_w, center_x + offset_x))
    return target_w, src_h, crop_x, 0


def parse_clips_file(path):
    clips = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            offset = 0
            if len(parts) >= 4:
                try:
                    offset = int(parts[3].strip())
                except ValueError:
                    offset = 0
            if len(parts) >= 3:
                clips.append((parts[0].strip(), parts[1].strip(), parts[2].strip(), offset))
    return clips


def generate_comparison_sheet(input_video, clip_ss, clip_duration, output_name, src_w, src_h, outdir):
    """
    각 클립에 대해 한 장의 비교 시트 생성:
    - 상단: 원본 프레임 + 3개 크롭 영역(왼/중/우) 표시
    - 하단: 3개 크롭 결과 나란히 + 라벨
    - 클립 중간 지점 프레임도 추가 캡처
    """
    base = os.path.splitext(output_name)[0]
    tmpdir = tempfile.mkdtemp(prefix="crop_preview_")
    target_w = int(src_h * 9 / 16)
    center_x = (src_w - target_w) // 2

    # 크롭 위치 3가지: 왼쪽, 중앙, 오른쪽
    offsets = [
        ("LEFT", -center_x, "green"),          # 가장 왼쪽
        ("CENTER", 0, "red"),                   # 중앙
        ("RIGHT", src_w - target_w - center_x, "blue"),  # 가장 오른쪽
    ]

    # 실제 유효한 crop_x 값 계산
    positions = []
    for label, off, color in offsets:
        cx = max(0, min(src_w - target_w, center_x + off))
        positions.append((label, cx, color))

    # 시작 지점 + 중간 지점 프레임 캡처
    clip_start_sec = ts_to_sec(clip_ss)
    clip_dur_sec = ts_to_sec(clip_duration)
    mid_sec = clip_start_sec + clip_dur_sec / 2
    mid_mm = int(mid_sec // 60)
    mid_ss = mid_sec % 60
    mid_ts = f"00:{mid_mm:02d}:{mid_ss:06.3f}"

    timestamps = [
        (clip_ss, "start"),
        (mid_ts, "mid"),
    ]

    for ts, ts_label in timestamps:
        # --- 상단: 원본 + 3개 영역 표시 ---
        drawboxes = []
        for label, cx, color in positions:
            drawboxes.append(
                f"drawbox=x={cx}:y=0:w={target_w}:h={src_h}:color={color}@0.5:t=8"
            )
        # 라벨 추가
        for i, (label, cx, color) in enumerate(positions):
            label_x = cx + target_w // 2 - 80
            drawboxes.append(
                f"drawtext=text='{label}'"
                f":fontsize=60"
                f":fontcolor={color}"
                f":borderw=3:bordercolor=black"
                f":x={label_x}:y=80"
                f":fontfile=/System/Library/Fonts/AppleSDGothicNeo.ttc"
            )

        full_filter = ",".join(drawboxes) + ",scale=1920:-1"
        full_path = os.path.join(tmpdir, f"full_{ts_label}.jpg")
        subprocess.run([
            "ffmpeg", "-y", "-ss", ts, "-i", input_video,
            "-frames:v", "1", "-vf", full_filter,
            "-q:v", "2", full_path
        ], capture_output=True, text=True)

        # --- 하단: 3개 크롭 결과 나란히 ---
        crop_paths = []
        for label, cx, color in positions:
            crop_path = os.path.join(tmpdir, f"crop_{ts_label}_{label}.jpg")
            # 크롭 + 라벨
            crop_filter = (
                f"crop={target_w}:{src_h}:{cx}:0,"
                f"scale=360:640,"
                f"drawtext=text='{label} (x={cx})'"
                f":fontsize=24"
                f":fontcolor={color}"
                f":borderw=2:bordercolor=black"
                f":x=(w-text_w)/2:y=10"
                f":fontfile=/System/Library/Fonts/AppleSDGothicNeo.ttc"
            )
            subprocess.run([
                "ffmpeg", "-y", "-ss", ts, "-i", input_video,
                "-frames:v", "1", "-vf", crop_filter,
                "-q:v", "2", crop_path
            ], capture_output=True, text=True)
            crop_paths.append(crop_path)

        # --- 합치기: 상단(원본) + 하단(크롭3개 나란히) ---
        # 하단: 3개를 가로로 합침
        crops_row = os.path.join(tmpdir, f"crops_row_{ts_label}.jpg")
        subprocess.run([
            "ffmpeg", "-y",
            "-i", crop_paths[0], "-i", crop_paths[1], "-i", crop_paths[2],
            "-filter_complex", "[0][1][2]hstack=inputs=3",
            "-q:v", "2", crops_row
        ], capture_output=True, text=True)

        # 상단 + 하단 세로 합침
        sheet_path = os.path.join(outdir, f"{base}_{ts_label}.jpg")
        subprocess.run([
            "ffmpeg", "-y",
            "-i", full_path, "-i", crops_row,
            "-filter_complex",
            "[0]scale=1080:-1[top];"
            "[1]scale=1080:-1[bot];"
            "[top][bot]vstack=inputs=2",
            "-q:v", "2", sheet_path
        ], capture_output=True, text=True)

        if os.path.exists(sheet_path):
            print(f"    {ts_label}: {sheet_path}")

    # 정리
    shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="쇼츠 크롭 미리보기 비교 시트 생성")
    parser.add_argument("--input", "-i", required=True, help="원본 영상 파일")
    parser.add_argument("--clips", "-c", required=True, help="클립 목록 파일")
    parser.add_argument("--outdir", "-o", default="previews", help="미리보기 출력 디렉토리 (기본: previews)")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    src_w, src_h = get_video_dimensions(args.input)
    print(f"원본 해상도: {src_w}x{src_h}")
    target_w = int(src_h * 9 / 16)
    print(f"크롭 너비: {target_w}px (9:16)")
    print(f"조정 가능 범위: 0 ~ {src_w - target_w}px\n")

    clips = parse_clips_file(args.clips)

    for ss, t, name, offset in clips:
        print(f"  [{name}]")
        generate_comparison_sheet(args.input, ss, t, name, src_w, src_h, args.outdir)

    print(f"\n=== 비교 시트 {len(clips)}개 생성 완료 ===")
    print(f"'{args.outdir}/' 폴더에서 각 클립의 시트를 확인하세요.")
    print(f"  *_start.jpg : 클립 시작 지점")
    print(f"  *_mid.jpg   : 클립 중간 지점")
    print(f"\n크롭 위치 결정 후 clips.txt의 4번째 컬럼에 원하는 오프셋을 입력하세요.")
    print(f"  예: LEFT 선택 → 오프셋 -{src_w // 2 - target_w // 2}")
    print(f"  예: RIGHT 선택 → 오프셋 +{src_w // 2 - target_w // 2}")


if __name__ == "__main__":
    main()
