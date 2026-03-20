#!/usr/bin/env python3
"""
Step 6: 폰트 + 크기 미리보기
- subtitles 필터(libass)로 실제 출력과 동일하게 렌더링
- 폰트별 × 사이즈별 조합을 모두 생성하여 비교
- 긴 자막이 나오는 시점 자동 선택

사용법:
  python3 06_preview_fonts.py --input 영상.mp4 --clips clips.txt --srt 자막.srt
  python3 06_preview_fonts.py --input 영상.mp4 --clips clips.txt --srt 자막.srt --sizes 10,12,14

폰트 추가:
  FONT_CANDIDATES 리스트에 (이름, FontName) 추가
"""

import subprocess
import re
import os
import argparse
import tempfile
import shutil

# 한글 지원 폰트 후보 (이름, ASS FontName)
FONT_CANDIDATES = [
    ("AppleSDGothicNeo", "AppleSDGothicNeo"),
    ("AppleMyungjo", "AppleMyungjo"),
    ("AppleGothic", "AppleGothic"),
]

# 기본 테스트 사이즈
DEFAULT_SIZES = [10, 12, 14, 16]

GRID_DIVISIONS = 10


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
    spec = spec.strip()
    if "~" in spec:
        left, right = spec.split("~")
        interval = src_w / GRID_DIVISIONS
        crop_x = int(int(left) * interval)
        crop_w = int((int(right) - int(left)) * interval)
        return crop_w, src_h, crop_x, 0
    offset = int(spec) if spec else 0
    target_w = int(src_h * 9 / 16)
    center_x = (src_w - target_w) // 2
    crop_x = max(0, min(src_w - target_w, center_x + offset))
    return target_w, src_h, crop_x, 0


def build_scale_pad(crop_w, crop_h):
    target_ratio = 1080 / 1920
    crop_ratio = crop_w / crop_h
    if abs(crop_ratio - target_ratio) < 0.01:
        return "scale=1080:1920"
    elif crop_ratio > target_ratio:
        sh = int(1080 / crop_ratio)
        return f"scale=1080:{sh},pad=1080:1920:0:(1920-{sh})/2:black"
    else:
        sw = int(1920 * crop_ratio)
        return f"scale={sw}:1920,pad=1080:1920:(1080-{sw})/2:0:black"


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


def parse_srt(path):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    blocks = re.split(r"\n\n+", content.strip())
    subs = []
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        m = re.match(r"(\S+)\s+-->\s+(\S+)", lines[1])
        if not m:
            continue
        start = ts_to_sec(m.group(1))
        end = ts_to_sec(m.group(2))
        text = " ".join(lines[2:])
        subs.append((start, end, text))
    return subs


def find_long_subtitle_time(subs, clip_start_sec=None, clip_dur_sec=None):
    """가장 긴 자막이 나오는 시점 반환. 클립 범위 내 → 전체 fallback."""
    best_time = 0
    best_len = 0
    best_text = ""

    # 클립 범위 내에서 먼저 시도
    if clip_start_sec is not None and clip_dur_sec is not None:
        clip_end = clip_start_sec + clip_dur_sec
        for start, end, text in subs:
            if end < clip_start_sec or start > clip_end:
                continue
            if len(text) > best_len:
                best_len = len(text)
                best_time = (start + end) / 2  # 자막 중간 시점
                best_text = text

    # 클립 범위에서 15자 이상 못 찾으면 전체에서 검색
    if best_len < 15:
        for start, end, text in subs:
            if len(text) > best_len:
                best_len = len(text)
                best_time = (start + end) / 2
                best_text = text

    return best_time, best_len, best_text


def generate_preview(input_video, timestamp, srt_path, crop_params, font_name, font_size, output_path):
    """subtitles 필터로 실제 출력과 동일한 프리뷰 생성"""
    cw, ch, cx, cy = crop_params
    scale_pad = build_scale_pad(cw, ch)

    # SRT 임시 링크
    tmpdir = tempfile.mkdtemp(prefix="gshorts_font_")
    tmp_srt = os.path.join(tmpdir, "subs.srt")
    os.symlink(os.path.abspath(srt_path), tmp_srt)
    srt_escaped = tmp_srt.replace("\\", "/").replace(":", "\\:")

    style = f"FontName={font_name},FontSize={font_size},PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,Alignment=2,MarginV=40"

    # 라벨: 폰트명 + 사이즈
    label_text = f"{font_name}  size={font_size}"

    vf = (
        f"crop={cw}:{ch}:{cx}:{cy},"
        f"{scale_pad},"
        f"subtitles={srt_escaped}:force_style='{style}',"
        f"drawtext=text='{label_text}'"
        f":fontfile=/System/Library/Fonts/AppleSDGothicNeo.ttc"
        f":fontsize=28:fontcolor=yellow:borderw=2:bordercolor=black"
        f":x=20:y=20"
    )

    ss = f"00:{int(timestamp//60):02d}:{timestamp%60:06.3f}"

    cmd = [
        "ffmpeg", "-y", "-ss", ss, "-i", input_video,
        "-frames:v", "1", "-vf", vf,
        "-q:v", "2", output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    shutil.rmtree(tmpdir, ignore_errors=True)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="폰트 + 크기 미리보기 (subtitles 필터 기반)")
    parser.add_argument("--input", "-i", required=True, help="원본 영상 파일")
    parser.add_argument("--clips", "-c", required=True, help="클립 목록 파일")
    parser.add_argument("--srt", "-s", required=True, help="SRT 자막 파일")
    parser.add_argument("--outdir", "-o", default="previews", help="출력 디렉토리")
    parser.add_argument("--sizes", help="테스트할 FontSize (쉼표 구분, 기본: 10,12,14,16)")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    src_w, src_h = get_video_dimensions(args.input)
    clips = parse_clips_file(args.clips)
    subs = parse_srt(args.srt)
    sizes = [int(s) for s in args.sizes.split(",")] if args.sizes else DEFAULT_SIZES

    if not clips:
        print("clips.txt에 클립이 없습니다.")
        return

    # 첫 번째 클립에서 가장 긴 자막 시점 찾기
    ss, t, name, crop_spec = clips[0]
    crop_params = parse_crop_spec(crop_spec, src_w, src_h)
    clip_start = ts_to_sec(ss)
    clip_dur = ts_to_sec(t)

    best_time, best_len, sub_text = find_long_subtitle_time(subs, clip_start, clip_dur)

    print(f"원본: {src_w}x{src_h}")
    print(f"클립: {name}")
    print(f"자막 시점: {int(best_time//60):02d}:{int(best_time%60):02d}")
    print(f"자막: \"{sub_text}\" ({best_len}자)")
    print(f"폰트: {', '.join(n for n, _ in FONT_CANDIDATES)}")
    print(f"사이즈: {sizes}")

    cw, ch, _, _ = crop_params
    crop_ratio = cw / ch
    target_ratio = 9 / 16
    if crop_ratio > target_ratio + 0.05:
        print(f"크롭 비율: {crop_ratio:.2f} (9:16보다 넓음 → 위아래 여백)")
    print()

    # 폰트별 × 사이즈별 생성
    total = len(FONT_CANDIDATES) * len(sizes)
    done = 0
    for font_name, font_ass_name in FONT_CANDIDATES:
        for size in sizes:
            out = os.path.join(args.outdir, f"font_{font_name}_size{size}.jpg")
            ok = generate_preview(
                args.input, best_time, args.srt, crop_params,
                font_ass_name, size, out
            )
            done += 1
            status = "OK" if ok else "FAIL"
            print(f"  [{done}/{total}] {font_name} size={size} — {status}")

    # 결과 안내
    print(f"\n{'='*60}")
    print(f"  폰트 미리보기 생성 완료 ({total}개)")
    print(f"{'='*60}")
    print(f"\n  프리뷰 파일:")
    for font_name, _ in FONT_CANDIDATES:
        files = [f"font_{font_name}_size{s}.jpg" for s in sizes]
        print(f"    {font_name}: {', '.join(files)}")

    print(f"\n  ─── 선택 방법 ───")
    print(f"  프리뷰를 비교한 뒤 폰트와 사이즈를 알려주세요.")
    print(f"  예: 'AppleMyungjo size 12로 해줘'")
    print(f"  → 08_make_shorts.py의 SUBTITLE_STYLE에 자동 반영됩니다.")

    print(f"\n  ─── 외부 폰트 추가 ───")
    print(f"  1. .ttf/.otf 파일 준비")
    print(f"  2. 이 스크립트의 FONT_CANDIDATES에 추가:")
    print(f'     ("NanumGothicBold", "NanumGothicBold"),')
    print(f"  3. 프리뷰 재생성하여 비교")
    print()


if __name__ == "__main__":
    main()
