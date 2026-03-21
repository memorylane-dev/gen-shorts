#!/usr/bin/env python3
"""
Step 6: 폰트 + 크기 미리보기
- 실제 폰트 family를 사용해 drawtext로 렌더링
- 폰트별 × 사이즈별 조합을 모두 생성하여 비교
- 긴 자막이 나오는 시점 자동 선택

사용법:
  python3 06_preview_fonts.py --input 영상.mp4 --clips clips.txt --srt 자막.srt
  python3 06_preview_fonts.py --input 영상.mp4 --clips clips.txt --srt 자막.srt --sizes 16,20,24,32

폰트 추가:
  FONT_CANDIDATES 리스트에 (이름, 폰트 패밀리명) 추가
"""

import subprocess
import re
import os
import argparse
import tempfile
import shutil

# 한글 지원 폰트 후보 (표시용 이름, 폰트 패밀리명)
FONT_CANDIDATES = [
    ("AppleSDGothicNeo", "Apple SD Gothic Neo"),
    ("NanumGothic", "Nanum Gothic"),
    ("NanumGothicBold", "NanumGothic ExtraBold"),
    ("NanumMyeongjo", "Nanum Myeongjo"),
    ("BM_Dohyeon", "BM Dohyeon"),
    ("BM_KirangHaerang", "BM Kirang Haerang"),
    ("BM_Yeonsung", "BM Yeonsung"),
    ("NanumBrush", "Nanum Brush Script"),
    ("NanumPen", "Nanum Pen Script"),
    ("BM_JUA", "BM JUA_OTF"),
    ("SUIT", "SUIT"),
    ("SUIT_Bold", "SUIT:style=Bold"),
]

# 기본 테스트 비율 (캔버스 높이 1920 대비)
DEFAULT_SIZE_RATIOS = [1/96, 1/64, 1/48, 1/40]  # ≈20, 30, 40, 48px
CANVAS_HEIGHT = 1920
DEFAULT_Y_RATIO = 3 / 4  # 자막 y 위치: 캔버스 높이의 3/4 지점
PREVIEW_LINE_SPACING = 8
PREVIEW_BOX_BORDER = 12

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


def resolve_font_file(font_family):
    """fontconfig로 폰트 패밀리명을 실제 파일 경로로 해석."""
    result = subprocess.run(
        ["fc-match", "-v", font_family],
        capture_output=True,
        text=True,
    )
    match = re.search(r'file:\s*"([^"]+)"', result.stdout)
    if not match:
        return None
    path = match.group(1)
    return path if os.path.exists(path) else None


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
        text = "\n".join(lines[2:])
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

    # 클립 범위에서 자막을 못 찾으면 클립 중간 시점 사용
    if best_len == 0 and clip_start_sec is not None and clip_dur_sec is not None:
        best_time = clip_start_sec + clip_dur_sec / 2
        best_text = "(자막 없음)"

    return best_time, best_len, best_text


def escape_filter_path(path):
    return path.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def escape_drawtext_text(text):
    return (
        text.replace("\\", r"\\")
        .replace(":", r"\:")
        .replace("'", r"\'")
        .replace("%", r"\%")
    )


def generate_preview(input_video, timestamp, subtitle_text, crop_params, font_label, font_family, size_ratio, y_ratio, output_path):
    """실제 폰트 family로 drawtext 프리뷰 생성 (비율 기반)"""
    cw, ch, cx, cy = crop_params
    scale_pad = build_scale_pad(cw, ch)

    font_size = round(size_ratio * CANVAS_HEIGHT)
    subtitle_y = round(y_ratio * CANVAS_HEIGHT)

    tmpdir = tempfile.mkdtemp(prefix="gshorts_font_")
    text_path = os.path.join(tmpdir, "sample.txt")
    with open(text_path, "w", encoding="utf-8") as f:
        f.write(subtitle_text)

    # 라벨: 폰트명 + 비율
    ratio_str = f"1/{round(1/size_ratio)}"
    label_text = escape_drawtext_text(f"{font_label}  {ratio_str} ({font_size}px)  y={y_ratio:.2f}")
    text_path_escaped = escape_filter_path(text_path)
    font_family_escaped = escape_drawtext_text(font_family)
    label_font_escaped = escape_drawtext_text("Apple SD Gothic Neo")

    vf = (
        f"crop={cw}:{ch}:{cx}:{cy},{scale_pad},"
        f"drawtext=font='{font_family_escaped}'"
        f":textfile='{text_path_escaped}'"
        f":fontsize={font_size}"
        f":fontcolor=white"
        f":borderw=1:bordercolor=black"
        f":line_spacing={PREVIEW_LINE_SPACING}"
        f":box=1:boxcolor=black@0.5:boxborderw={PREVIEW_BOX_BORDER}"
        f":x=(w-text_w)/2"
        f":y={subtitle_y},"
        f"drawtext=text='{label_text}'"
        f":font='{label_font_escaped}'"
        f":fontsize=28:fontcolor=yellow:borderw=2:bordercolor=black"
        f":x=20:y=20"
    )

    hours = int(timestamp // 3600)
    mins = int((timestamp % 3600) // 60)
    secs = timestamp % 60
    ss = f"{hours:02d}:{mins:02d}:{secs:06.3f}"

    # -ss before -i (입력 시킹, 빠름)
    cmd = [
        "ffmpeg", "-y", "-ss", ss, "-i", input_video,
        "-frames:v", "1", "-vf", vf,
        "-q:v", "2", output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    shutil.rmtree(tmpdir, ignore_errors=True)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="폰트 + 크기 미리보기 (fontfile 기반)")
    parser.add_argument("--input", "-i", required=True, help="원본 영상 파일")
    parser.add_argument("--clips", "-c", required=True, help="클립 목록 파일")
    parser.add_argument("--srt", "-s", required=True, help="SRT 자막 파일")
    parser.add_argument("--outdir", "-o", default="previews", help="출력 디렉토리")
    parser.add_argument("--sizes", help="테스트할 비율 (쉼표 구분, 예: 1/96,1/64,1/48,1/40)")
    parser.add_argument("--y-ratio", type=float, default=DEFAULT_Y_RATIO,
                        help=f"자막 y 위치 비율 (기본: {DEFAULT_Y_RATIO})")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    src_w, src_h = get_video_dimensions(args.input)
    clips = parse_clips_file(args.clips)
    subs = parse_srt(args.srt)
    if args.sizes:
        size_ratios = [eval(s.strip()) for s in args.sizes.split(",")]
    else:
        size_ratios = DEFAULT_SIZE_RATIOS

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
    size_labels = [f"1/{round(1/r)}({round(r*CANVAS_HEIGHT)}px)" for r in size_ratios]
    print(f"사이즈: {', '.join(size_labels)}")
    print(f"자막 위치: y={args.y_ratio} (캔버스 {round(args.y_ratio*100)}%)")

    cw, ch, _, _ = crop_params
    crop_ratio = cw / ch
    target_ratio = 9 / 16
    if crop_ratio > target_ratio + 0.05:
        print(f"크롭 비율: {crop_ratio:.2f} (9:16보다 넓음 → 위아래 여백)")
    print()

    # 폰트별 × 사이즈별 생성
    resolved_fonts = []
    for font_label, font_family in FONT_CANDIDATES:
        font_file = resolve_font_file(font_family)
        if not font_file:
            print(f"  Skip {font_label}: font file resolve 실패 ({font_family})")
            continue
        resolved_fonts.append((font_label, font_family, font_file))

    print(f"폰트: {', '.join(label for label, _, _ in resolved_fonts)}")
    print()

    total = len(resolved_fonts) * len(size_ratios)
    done = 0
    for font_label, font_family, _ in resolved_fonts:
        for sr in size_ratios:
            denom = round(1 / sr)
            px = round(sr * CANVAS_HEIGHT)
            out = os.path.join(args.outdir, f"font_{font_label}_r{denom}.jpg")
            ok = generate_preview(
                args.input, best_time, sub_text, crop_params,
                font_label, font_family, sr, args.y_ratio, out
            )
            done += 1
            status = "OK" if ok else "FAIL"
            print(f"  [{done}/{total}] {font_label} 1/{denom} ({px}px) — {status}")

    # 결과 안내
    print(f"\n{'='*60}")
    print(f"  폰트 미리보기 생성 완료 ({total}개)")
    print(f"{'='*60}")
    print(f"\n  프리뷰 파일:")
    for font_label, _, _ in resolved_fonts:
        files = [f"font_{font_label}_r{round(1/sr)}.jpg" for sr in size_ratios]
        print(f"    {font_label}: {', '.join(files)}")

    print(f"\n  ─── 선택 방법 ───")
    print(f"  프리뷰를 비교한 뒤 폰트와 비율을 알려주세요.")
    print(f"  예: 'NanumPen 1/48로 해줘'")
    print(f"  08_make_shorts.py의 SUBTITLE_SIZE_RATIO에 반영하면 됩니다.")
    print()


if __name__ == "__main__":
    main()
