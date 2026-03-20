#!/usr/bin/env python3
"""
Step 8: YouTube Shorts 생성 (다국어 + 자유 크롭)
- 각 클립별 4개 버전: 자막없음 / 한국어 / 영어 / 스페인어
- 기준선 범위로 자유 크롭 (9:16에 안 맞으면 위아래 검은 여백 자동 추가)
- SRT 자막 하드코딩 (subtitles/libass 필터)

clips.txt 형식:
  시작시간,길이,파일명,크롭범위
  00:01:50,00:00:35,1_clip.mp4,2~8     ← 기준선 2~8 사이 크롭
  00:03:00,00:00:50,2_clip.mp4,3~7
  00:08:07,00:00:38,3_clip.mp4          ← 범위 생략 시 9:16 중앙 크롭
  00:08:07,00:00:38,4_clip.mp4,+300     ← 기존 오프셋 방식도 호환
"""

import subprocess
import os
import argparse
import tempfile
import shutil
from concurrent.futures import ThreadPoolExecutor

SUBTITLE_STYLE = "FontName=BM Dohyeon,FontSize=12,PrimaryColour=&H00FFFFFF,BackColour=&H80000000,BorderStyle=4,Outline=1,OutlineColour=&H00000000,Shadow=0,Alignment=2,MarginV=40"
GRID_DIVISIONS = 10  # 기준선 분할 수
OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920

# 페이드 효과 설정 (초)
FADE_IN_VIDEO = 0.3   # 영상 페이드인
FADE_OUT_VIDEO = 0.5   # 영상 페이드아웃
FADE_IN_AUDIO = 0.2   # 오디오 페이드인
FADE_OUT_AUDIO = 0.4   # 오디오 페이드아웃

LANGUAGES = [
    ("nosub", None, "자막 없음"),
    ("ko", "subtitle.srt", "한국어"),
    ("en", "subtitle_en.srt", "English"),
    ("es", "subtitle_es.srt", "Español"),
]


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


def parse_crop_spec(spec, src_w, src_h):
    """
    크롭 스펙 파싱 → (crop_w, crop_h, crop_x, crop_y)
    - '2~8'      → 기준선 2~8 사이 크롭
    - '+300'     → 9:16 중앙에서 오프셋
    - ''(빈값)   → 9:16 중앙 크롭
    """
    spec = spec.strip()

    if "~" in spec:
        # 기준선 범위: '2~8'
        left, right = spec.split("~")
        left, right = int(left), int(right)
        interval = src_w / GRID_DIVISIONS
        crop_x = int(left * interval)
        crop_w = int((right - left) * interval)
        crop_h = src_h
        crop_y = 0
        return crop_w, crop_h, crop_x, crop_y

    # 기존 오프셋 방식 또는 기본 9:16
    offset = int(spec) if spec else 0
    target_w = int(src_h * 9 / 16)
    center_x = (src_w - target_w) // 2
    crop_x = max(0, min(src_w - target_w, center_x + offset))
    return target_w, src_h, crop_x, 0


def build_scale_pad_filter(crop_w, crop_h):
    """
    크롭된 영상을 1080x1920에 맞추는 필터.
    비율이 9:16보다 넓으면 위아래 검은 여백 추가.
    비율이 9:16보다 좁으면 좌우 검은 여백 추가.
    """
    crop_ratio = crop_w / crop_h
    target_ratio = OUTPUT_WIDTH / OUTPUT_HEIGHT  # 9/16 = 0.5625

    if abs(crop_ratio - target_ratio) < 0.01:
        # 거의 9:16 → 그냥 스케일
        return f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}"
    elif crop_ratio > target_ratio:
        # 원본이 더 넓음 → 가로 맞추고 위아래 여백
        scaled_h = int(OUTPUT_WIDTH / crop_ratio)
        return f"scale={OUTPUT_WIDTH}:{scaled_h},pad={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:0:({OUTPUT_HEIGHT}-{scaled_h})/2:black"
    else:
        # 원본이 더 좁음 → 세로 맞추고 좌우 여백
        scaled_w = int(OUTPUT_HEIGHT * crop_ratio)
        return f"scale={scaled_w}:{OUTPUT_HEIGHT},pad={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:({OUTPUT_WIDTH}-{scaled_w})/2:0:black"


def parse_clips_file(path):
    clips = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            crop_spec = parts[3].strip() if len(parts) >= 4 else ""
            if len(parts) >= 3:
                clips.append((parts[0].strip(), parts[1].strip(), parts[2].strip(), crop_spec))
    return clips


def encode_clip(input_video, clip_ss, clip_t, output_path, srt_path, crop_params):
    """단일 클립 인코딩 (fade in/out 포함)"""
    cw, ch, cx, cy = crop_params
    scale_pad = build_scale_pad_filter(cw, ch)
    duration = ts_to_sec(clip_t)
    clip_start = ts_to_sec(clip_ss)

    if srt_path:
        # 자막 있을 때: -ss를 -i 뒤에 배치 (타임스탬프 보존 → 자막 매칭)
        # 필터 체인이 파일 시작부터 처리되므로 fade/afade에 절대 타임스탬프 사용
        fade_out_start = clip_start + duration - FADE_OUT_VIDEO
        fade_filter = (
            f"fade=t=in:st={clip_start}:d={FADE_IN_VIDEO},"
            f"fade=t=out:st={fade_out_start}:d={FADE_OUT_VIDEO}"
        )

        tmpdir = tempfile.mkdtemp(prefix="gshorts_")
        tmp_srt = os.path.join(tmpdir, "subs.srt")
        os.symlink(os.path.abspath(srt_path), tmp_srt)
        srt_escaped = tmp_srt.replace("\\", "/").replace(":", "\\:")

        vf = (
            f"crop={cw}:{ch}:{cx}:{cy},"
            f"{scale_pad},"
            f"{fade_filter},"
            f"subtitles={srt_escaped}:force_style='{SUBTITLE_STYLE}'"
        )

        afade_out_start = clip_start + duration - FADE_OUT_AUDIO
        af = (
            f"afade=t=in:st={clip_start}:d={FADE_IN_AUDIO},"
            f"afade=t=out:st={afade_out_start}:d={FADE_OUT_AUDIO}"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", input_video,
            "-ss", clip_ss,
            "-t", clip_t,
            "-vf", vf,
            "-af", af,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            output_path
        ]
    else:
        # 자막 없을 때: -ss를 -i 앞에 배치 (빠른 탐색, 타임스탬프 0부터)
        tmpdir = None
        fade_out_start = max(0, duration - FADE_OUT_VIDEO)
        fade_filter = (
            f"fade=t=in:st=0:d={FADE_IN_VIDEO},"
            f"fade=t=out:st={fade_out_start}:d={FADE_OUT_VIDEO}"
        )
        vf = f"crop={cw}:{ch}:{cx}:{cy},{scale_pad},{fade_filter}"

        afade_out_start = max(0, duration - FADE_OUT_AUDIO)
        af = (
            f"afade=t=in:st=0:d={FADE_IN_AUDIO},"
            f"afade=t=out:st={afade_out_start}:d={FADE_OUT_AUDIO}"
        )

        cmd = [
            "ffmpeg", "-y",
            "-ss", clip_ss,
            "-i", input_video,
            "-t", clip_t,
            "-vf", vf,
            "-af", af,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            output_path
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if tmpdir:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="YouTube Shorts 생성기 (다국어 + 자유 크롭)")
    parser.add_argument("--input", "-i", required=True, help="원본 영상 파일")
    parser.add_argument("--clips", "-c", required=True, help="클립 목록 파일")
    parser.add_argument("--srtdir", "-s", required=True, help="자막 파일 디렉토리")
    parser.add_argument("--outdir", "-o", default="output", help="출력 디렉토리")
    parser.add_argument("--workers", "-w", type=int, default=4, help="병렬 인코딩 수")
    args = parser.parse_args()

    src_w, src_h = get_video_dimensions(args.input)
    print(f"Source: {src_w}x{src_h}")

    clips = parse_clips_file(args.clips)
    print(f"Clips: {len(clips)}")

    # 크롭 정보 표시
    for ss, t, name, crop_spec in clips:
        cw, ch, cx, cy = parse_crop_spec(crop_spec, src_w, src_h)
        ratio = f"{cw/ch:.2f}"
        print(f"  {name}: crop {cw}x{ch} at ({cx},{cy}) ratio={ratio}")

    # 사용 가능한 언어 확인
    available_langs = []
    for suffix, srt_name, label in LANGUAGES:
        if srt_name is None:
            available_langs.append((suffix, None, label))
        else:
            srt_path = os.path.join(args.srtdir, srt_name)
            if os.path.exists(srt_path):
                available_langs.append((suffix, srt_path, label))
            else:
                print(f"  Skip [{suffix}]: {srt_name} 없음")

    print(f"Languages: {', '.join(f'{l[2]}' for l in available_langs)}")
    total = len(clips) * len(available_langs)
    print(f"Total: {total} videos\n")

    for suffix, _, _ in available_langs:
        os.makedirs(os.path.join(args.outdir, suffix), exist_ok=True)

    # 인코딩
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = []
        for ss, t, name, crop_spec in clips:
            crop_params = parse_crop_spec(crop_spec, src_w, src_h)
            for suffix, srt_path, label in available_langs:
                out_path = os.path.join(args.outdir, suffix, name)
                futures.append((
                    pool.submit(encode_clip, args.input, ss, t, out_path, srt_path, crop_params),
                    suffix, name
                ))

        for future, suffix, name in futures:
            ok = future.result()
            done += 1
            status = "OK" if ok else "FAIL"
            print(f"  [{done}/{total}] [{suffix}] {name} — {status}")

    print(f"\n=== 완료: {total}개 영상 생성 ===")
    for suffix, _, label in available_langs:
        lang_dir = os.path.join(args.outdir, suffix)
        count = len([f for f in os.listdir(lang_dir) if f.endswith(".mp4")])
        print(f"  {lang_dir}/ — {label} ({count}개)")


if __name__ == "__main__":
    main()
