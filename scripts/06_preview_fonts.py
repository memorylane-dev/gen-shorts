#!/usr/bin/env python3
"""
Step 6: 폰트 + 크기 미리보기
- 실제 폰트 family를 사용해 drawtext 또는 image renderer로 렌더링
- 폰트별 × 사이즈별 조합을 모두 생성하여 비교
- 긴 자막이 나오는 시점 자동 선택

사용법:
  python3 06_preview_fonts.py --input 영상.mp4 --clips clips.txt --srt 자막.srt
  python3 06_preview_fonts.py --input 영상.mp4 --clips clips.txt --srt 자막.srt --renderer image
  python3 06_preview_fonts.py --input 영상.mp4 --clips clips.txt --srt 자막.srt --font-profile cute_multilingual --target-suffix jp

폰트 추가:
  FONT_CANDIDATES 리스트에 (이름, 폰트 패밀리명) 추가
"""

import subprocess
import re
import os
import argparse
import tempfile
import shutil
from font_profiles import FONT_PROFILES, apply_font_profile_defaults

# 한글 지원 폰트 후보 (표시용 이름, 폰트 패밀리명)
FONT_CANDIDATES = [
    ("Jua", "Jua"),
    ("BM_JUA", "BM JUA_OTF"),
    ("AppleSDGothicNeo", "Apple SD Gothic Neo"),
    ("Hiragino_Maru", "Hiragino Maru Gothic ProN"),
    ("Hiragino_Sans", "Hiragino Sans"),
    ("NanumGothic", "Nanum Gothic"),
    ("NanumGothicBold", "NanumGothic ExtraBold"),
    ("NanumMyeongjo", "Nanum Myeongjo"),
    ("BM_Dohyeon", "BM Dohyeon"),
    ("BM_KirangHaerang", "BM Kirang Haerang"),
    ("BM_Yeonsung", "BM Yeonsung"),
    ("NanumBrush", "Nanum Brush Script"),
    ("NanumPen", "Nanum Pen Script"),
    ("SUIT", "SUIT"),
    ("SUIT_Bold", "SUIT:style=Bold"),
]

# 기본 테스트 비율 (캔버스 높이 1920 대비)
DEFAULT_SIZE_RATIOS = [1/96, 1/64, 1/48, 1/40]  # ≈20, 30, 40, 48px
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_SUBTITLE_RENDERER_PATH = os.path.join(SCRIPT_DIR, "render_subtitle_card.swift")
OUTPUT_WIDTH = 1080
CANVAS_HEIGHT = 1920
DEFAULT_Y_RATIO = 3 / 4  # 자막 y 위치: 캔버스 높이의 3/4 지점
DEFAULT_SUBTITLE_MAX_WIDTH_RATIO = 0.84
PREVIEW_LINE_SPACING = 8
PREVIEW_BOX_BORDER = 12
PREVIEW_BOX_PADDING_X = 28
PREVIEW_BOX_PADDING_Y = 18
PREVIEW_CORNER_RADIUS = 22

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


def build_profile_options(profile_name, target_suffix):
    if not profile_name:
        return {}
    try:
        options = apply_font_profile_defaults({}, profile_name)
    except ValueError as exc:
        raise SystemExit(str(exc))
    for key in (
        "subtitle_font",
        "subtitle_fontfile",
        "subtitle_renderer",
        "subtitle_size_delta",
        "subtitle_max_width_ratio",
    ):
        map_key = f"{key}_by_suffix"
        overrides = options.get(map_key)
        if isinstance(overrides, dict) and target_suffix in overrides:
            options[key] = overrides[target_suffix]
    return options


def parse_font_candidates(fonts_arg):
    if not fonts_arg:
        return list(FONT_CANDIDATES)
    result = []
    for raw in fonts_arg.split(","):
        font_name = raw.strip()
        if not font_name:
            continue
        label = re.sub(r"[^\w]+", "_", font_name).strip("_") or "font"
        result.append((label, font_name))
    return result


def escape_filter_path(path):
    return path.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def escape_drawtext_text(text):
    return (
        text.replace("\\", r"\\")
        .replace(":", r"\:")
        .replace("'", r"\'")
        .replace("%", r"\%")
    )


def render_image_subtitle_card(text, font_name, font_file, font_size, max_width_ratio, output_path, min_side_margin_px=0):
    if not os.path.exists(IMAGE_SUBTITLE_RENDERER_PATH):
        raise SystemExit(f"subtitle image renderer 스크립트가 없습니다: {IMAGE_SUBTITLE_RENDERER_PATH}")

    text_path = f"{output_path}.txt"
    with open(text_path, "w", encoding="utf-8") as f:
        f.write(text)

    max_width = max(200, int(OUTPUT_WIDTH * max_width_ratio))
    if min_side_margin_px > 0:
        max_width = min(max_width, max(200, OUTPUT_WIDTH - min_side_margin_px * 2))
    cmd = [
        "swift",
        IMAGE_SUBTITLE_RENDERER_PATH,
        "--text-file", text_path,
        "--output", output_path,
        "--max-width", str(max_width),
        "--font-name", font_name,
        "--font-size", str(font_size),
        "--line-spacing", str(PREVIEW_LINE_SPACING),
        "--padding-x", str(PREVIEW_BOX_PADDING_X),
        "--padding-y", str(PREVIEW_BOX_PADDING_Y),
        "--box-color", "black@0.5",
        "--text-color", "white",
        "--corner-radius", str(PREVIEW_CORNER_RADIUS),
        "--align", "center",
    ]
    if font_file:
        cmd += ["--font-file", font_file]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise SystemExit(f"image 자막 카드 생성 실패: {stderr}")


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


def generate_drawtext_preview(input_video, timestamp, subtitle_text, crop_params, font_label, font_family, size_ratio, y_ratio, output_path):
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


def generate_image_preview(input_video, timestamp, subtitle_text, crop_params, font_label, font_family, font_file, size_ratio, y_ratio, max_width_ratio, output_path):
    """실제 image subtitle renderer로 프리뷰 생성"""
    cw, ch, cx, cy = crop_params
    scale_pad = build_scale_pad(cw, ch)
    font_size = round(size_ratio * CANVAS_HEIGHT)
    margin_v = round(CANVAS_HEIGHT * (1 - y_ratio))
    ratio_str = f"1/{round(1/size_ratio)}"
    label_text = escape_drawtext_text(f"{font_label}  {ratio_str} ({font_size}px)  image")
    label_font_escaped = escape_drawtext_text("Apple SD Gothic Neo")

    tmpdir = tempfile.mkdtemp(prefix="gshorts_font_")
    card_path = os.path.join(tmpdir, "subtitle_card.png")
    try:
        render_image_subtitle_card(
            subtitle_text,
            font_family,
            font_file,
            font_size,
            max_width_ratio,
            card_path,
        )
        cmd = [
            "ffmpeg", "-y", "-ss", f"{int(timestamp // 3600):02d}:{int((timestamp % 3600) // 60):02d}:{timestamp % 60:06.3f}",
            "-i", input_video,
            "-loop", "1", "-i", card_path,
            "-frames:v", "1",
            "-filter_complex",
            (
                f"[0:v]crop={cw}:{ch}:{cx}:{cy},{scale_pad}[base];"
                f"[base][1:v]overlay=x=(main_w-overlay_w)/2:y=main_h-overlay_h-{margin_v}[tmp];"
                f"[tmp]drawtext=text='{label_text}':font='{label_font_escaped}':"
                "fontsize=28:fontcolor=yellow:borderw=2:bordercolor=black:x=20:y=20[out]"
            ),
            "-map", "[out]",
            "-q:v", "2",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode == 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="폰트 + 크기 미리보기")
    parser.add_argument("--input", "-i", required=True, help="원본 영상 파일")
    parser.add_argument("--clips", "-c", required=True, help="클립 목록 파일")
    parser.add_argument("--srt", "-s", required=True, help="SRT 자막 파일")
    parser.add_argument("--outdir", "-o", default="previews", help="출력 디렉토리")
    parser.add_argument("--sizes", help="테스트할 비율 (쉼표 구분, 예: 1/96,1/64,1/48,1/40)")
    parser.add_argument("--y-ratio", type=float, default=DEFAULT_Y_RATIO,
                        help=f"자막 y 위치 비율 (기본: {DEFAULT_Y_RATIO})")
    parser.add_argument("--renderer", choices=["image", "drawtext"], default="image",
                        help="프리뷰 렌더러 (기본: image)")
    parser.add_argument("--font-profile", choices=sorted(FONT_PROFILES), help="공유 font_profile 이름")
    parser.add_argument("--target-suffix", default="kr", help="font_profile 적용용 target suffix (기본: kr)")
    parser.add_argument("--fonts", help="비교할 폰트 이름 직접 지정 (쉼표 구분)")
    parser.add_argument("--max-width-ratio", type=float, help="image renderer 카드 최대 폭 비율")
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
    profile_options = build_profile_options(args.font_profile, args.target_suffix)
    preview_renderer = profile_options.get("subtitle_renderer", args.renderer)
    max_width_ratio = args.max_width_ratio or float(
        profile_options.get("subtitle_max_width_ratio", DEFAULT_SUBTITLE_MAX_WIDTH_RATIO)
    )

    print(f"원본: {src_w}x{src_h}")
    print(f"클립: {name}")
    print(f"자막 시점: {int(best_time//60):02d}:{int(best_time%60):02d}")
    print(f"자막: \"{sub_text}\" ({best_len}자)")
    size_labels = [f"1/{round(1/r)}({round(r*CANVAS_HEIGHT)}px)" for r in size_ratios]
    print(f"사이즈: {', '.join(size_labels)}")
    print(f"자막 위치: y={args.y_ratio} (캔버스 {round(args.y_ratio*100)}%)")
    print(f"렌더러: {preview_renderer}")
    if args.font_profile:
        print(f"폰트 프로필: {args.font_profile} (suffix={args.target_suffix})")
    if preview_renderer == "image":
        print(f"카드 최대 폭 비율: {max_width_ratio:.2f}")

    cw, ch, _, _ = crop_params
    crop_ratio = cw / ch
    target_ratio = 9 / 16
    if crop_ratio > target_ratio + 0.05:
        print(f"크롭 비율: {crop_ratio:.2f} (9:16보다 넓음 → 위아래 여백)")
    print()

    # 폰트별 × 사이즈별 생성
    font_candidates = parse_font_candidates(args.fonts)
    if args.font_profile and not args.fonts and profile_options.get("subtitle_font"):
        font_name = profile_options["subtitle_font"]
        font_candidates = [(re.sub(r"[^\w]+", "_", font_name).strip("_") or "profile_font", font_name)]

    resolved_fonts = []
    for font_label, font_family in font_candidates:
        font_file = resolve_font_file(font_family)
        if preview_renderer == "drawtext" and not font_file:
            print(f"  Skip {font_label}: font file resolve 실패 ({font_family})")
            continue
        resolved_fonts.append((font_label, font_family, font_file))

    if not resolved_fonts:
        raise SystemExit("미리보기 가능한 폰트를 찾지 못했습니다.")

    print(f"폰트: {', '.join(label for label, _, _ in resolved_fonts)}")
    print()

    total = len(resolved_fonts) * len(size_ratios)
    done = 0
    for font_label, font_family, font_file in resolved_fonts:
        for sr in size_ratios:
            denom = round(1 / sr)
            px = round(sr * CANVAS_HEIGHT)
            out = os.path.join(args.outdir, f"font_{font_label}_{preview_renderer}_r{denom}.jpg")
            if preview_renderer == "image":
                ok = generate_image_preview(
                    args.input, best_time, sub_text, crop_params,
                    font_label, font_family, font_file, sr, args.y_ratio,
                    max_width_ratio, out
                )
            else:
                ok = generate_drawtext_preview(
                    args.input, best_time, sub_text, crop_params,
                    font_label, font_family, sr, args.y_ratio, out
                )
            done += 1
            status = "OK" if ok else "FAIL"
            print(f"  [{done}/{total}] {font_label} 1/{denom} ({px}px) [{preview_renderer}] — {status}")

    # 결과 안내
    print(f"\n{'='*60}")
    print(f"  폰트 미리보기 생성 완료 ({total}개)")
    print(f"{'='*60}")
    print(f"\n  프리뷰 파일:")
    for font_label, _, _ in resolved_fonts:
        files = [f"font_{font_label}_{preview_renderer}_r{round(1/sr)}.jpg" for sr in size_ratios]
        print(f"    {font_label}: {', '.join(files)}")

    print(f"\n  ─── 선택 방법 ───")
    print(f"  프리뷰를 비교한 뒤 폰트와 비율을 알려주세요.")
    print(f"  예: 'Jua 1/48로 해줘' 또는 'cute_multilingual profile로 갈게'")
    print(f"  short spec의 font_profile / subtitle_font / subtitle_size_delta에 반영하면 됩니다.")
    print()


if __name__ == "__main__":
    main()
