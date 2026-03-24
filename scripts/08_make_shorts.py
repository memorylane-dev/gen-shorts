#!/usr/bin/env python3
"""
Step 8: YouTube Shorts 생성 (다국어 + 자유 크롭)
- 각 클립별 4개 버전: 자막없음 / 한국어 / 영어 / 스페인어
- 기준선 범위로 자유 크롭 (9:16에 안 맞으면 위아래 검은 여백 자동 추가)
- SRT 자막 하드코딩 (subtitles/libass 필터)
- 선택적 format preset 지원 (제목/브랜드/로고 오버레이)

clips.txt 형식:
  시작시간,길이,파일명,크롭범위
  00:01:50,00:00:35,1_clip.mp4,2~8     ← 기준선 2~8 사이 크롭
  00:03:00,00:00:50,2_clip.mp4,3~7
  00:08:07,00:00:38,3_clip.mp4          ← 범위 생략 시 9:16 중앙 크롭
  00:08:07,00:00:38,4_clip.mp4,+300     ← 기존 오프셋 방식도 호환
"""

import subprocess
import os
import re
import json
import argparse
import tempfile
import shutil
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
from font_profiles import apply_font_profile_defaults

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_SUBTITLE_RENDERER_PATH = os.path.join(SCRIPT_DIR, "render_subtitle_card.swift")
SUBTITLE_FONT = "BM JUA_OTF"
DISPLAY_FONT = "BM JUA_OTF"
SUBTITLE_SIZE_RATIO = 1 / 36       # 폰트 크기: 캔버스 높이 대비 비율
SUBTITLE_Y_RATIO = 3 / 4           # 자막 위치: 캔버스 상단에서 3/4 지점
_SUBTITLE_BASE = (
    "PrimaryColour=&H00FFFFFF,BackColour=&H80000000,BorderStyle=4,"
    "Outline=1,OutlineColour=&H00000000,Shadow=0,Alignment=2"
)
GRID_DIVISIONS = 10  # 기준선 분할 수
OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920
AUDIO_SAMPLE_RATE = 48000
AUDIO_CHANNEL_LAYOUT = "stereo"
DEFAULT_SUBTITLE_MAX_WIDTH_RATIO = 0.84

# 기본 페이드 효과 설정 (초)
DEFAULT_FADE_IN_SEC = 0.3
DEFAULT_FADE_OUT_SEC = 1.0

DEFAULT_FORMAT_PRESET = "clean_fullbleed"
FORMAT_PRESETS = {
    "clean_fullbleed": {
        "layout_mode": "single",
        "subtitle_y_ratio": SUBTITLE_Y_RATIO,
        "title_box_height": 0,
        "title_font_size": 72,
        "title_x_margin": 64,
        "title_y": 72,
        "title_align": "left",
        "title_box_color": "black@0.0",
        "brand_mode": "none",
        "brand_box_width": 320,
        "brand_box_height": 92,
        "brand_font_size": 34,
        "brand_x_margin": 48,
        "brand_y_margin": 220,
        "brand_box_color": "black@0.68",
        "logo_max_width": 220,
    },
    "headline_fullbleed": {
        "layout_mode": "single",
        "subtitle_y_ratio": 0.74,
        "title_box_height": 220,
        "title_font_size": 72,
        "title_x_margin": 64,
        "title_y": 68,
        "title_align": "left",
        "title_box_color": "black@0.45",
        "brand_mode": "none",
        "brand_box_width": 320,
        "brand_box_height": 92,
        "brand_font_size": 34,
        "brand_x_margin": 48,
        "brand_y_margin": 220,
        "brand_box_color": "black@0.68",
        "logo_max_width": 220,
    },
    "branded_header_logo": {
        "layout_mode": "single",
        "subtitle_y_ratio": 0.69,
        "title_box_height": 236,
        "title_font_size": 72,
        "title_x_margin": 64,
        "title_y": 74,
        "title_align": "left",
        "title_box_color": "0x111111@0.62",
        "brand_mode": "logo_or_text",
        "brand_box_width": 320,
        "brand_box_height": 92,
        "brand_font_size": 34,
        "brand_x_margin": 48,
        "brand_y_margin": 220,
        "brand_box_color": "0x111111@0.74",
        "logo_max_width": 220,
    },
    "quote_focus": {
        "layout_mode": "single",
        "subtitle_y_ratio": 0.8,
        "title_box_height": 300,
        "title_font_size": 84,
        "title_x_margin": 64,
        "title_y": 96,
        "title_align": "center",
        "title_box_color": "0x111111@0.72",
        "brand_mode": "none",
        "brand_box_width": 320,
        "brand_box_height": 92,
        "brand_font_size": 34,
        "brand_x_margin": 48,
        "brand_y_margin": 220,
        "brand_box_color": "black@0.68",
        "logo_max_width": 220,
    },
    "reaction_duet": {
        "layout_mode": "split",
        "split_play_mode": "parallel",
        "subtitle_y_ratio": 0.82,
        "title_box_height": 180,
        "title_font_size": 68,
        "title_x_margin": 56,
        "title_y": 52,
        "title_align": "left",
        "title_box_color": "0x111111@0.52",
        "brand_mode": "none",
        "brand_box_width": 320,
        "brand_box_height": 92,
        "brand_font_size": 34,
        "brand_x_margin": 48,
        "brand_y_margin": 220,
        "brand_box_color": "black@0.68",
        "logo_max_width": 220,
        "split_direction": "left_right",
        "split_gap": 20,
        "primary_panel": "left",
        "panel_label_box_width": 180,
        "panel_label_box_height": 64,
        "panel_label_font_size": 28,
        "panel_label_margin": 24,
        "panel_label_box_color": "black@0.55",
    },
    "comparison_split": {
        "layout_mode": "split",
        "split_play_mode": "parallel",
        "subtitle_y_ratio": 0.84,
        "title_box_height": 180,
        "title_font_size": 68,
        "title_x_margin": 56,
        "title_y": 52,
        "title_align": "left",
        "title_box_color": "0x111111@0.58",
        "brand_mode": "none",
        "brand_box_width": 320,
        "brand_box_height": 92,
        "brand_font_size": 34,
        "brand_x_margin": 48,
        "brand_y_margin": 220,
        "brand_box_color": "black@0.68",
        "logo_max_width": 220,
        "split_direction": "top_bottom",
        "split_gap": 20,
        "primary_panel": "top",
        "primary_label": "A",
        "secondary_label": "B",
        "panel_label_box_width": 180,
        "panel_label_box_height": 64,
        "panel_label_font_size": 28,
        "panel_label_margin": 24,
        "panel_label_box_color": "black@0.55",
    },
    "stitch_then_punchline": {
        "layout_mode": "stitch",
        "subtitle_y_ratio": 0.74,
        "title_box_height": 180,
        "title_font_size": 68,
        "title_x_margin": 56,
        "title_y": 52,
        "title_align": "left",
        "title_box_color": "0x111111@0.52",
        "brand_mode": "none",
        "brand_box_width": 320,
        "brand_box_height": 92,
        "brand_font_size": 34,
        "brand_x_margin": 48,
        "brand_y_margin": 220,
        "brand_box_color": "black@0.68",
        "logo_max_width": 220,
    },
    "alternating_spotlight": {
        "layout_mode": "split",
        "split_play_mode": "sequential_freeze",
        "split_direction": "top_bottom",
        "primary_panel": "top",
        "subtitle_y_ratio": 0.76,
        "title_box_height": 180,
        "title_font_size": 68,
        "title_x_margin": 56,
        "title_y": 52,
        "title_align": "left",
        "title_box_color": "0x111111@0.58",
        "brand_mode": "none",
        "brand_box_width": 320,
        "brand_box_height": 92,
        "brand_font_size": 34,
        "brand_x_margin": 48,
        "brand_y_margin": 220,
        "brand_box_color": "black@0.68",
        "logo_max_width": 220,
        "split_gap": 20,
        "primary_label": "SETUP",
        "secondary_label": "PAYOFF",
        "panel_label_box_width": 220,
        "panel_label_box_height": 64,
        "panel_label_font_size": 28,
        "panel_label_margin": 24,
        "panel_label_box_color": "black@0.55",
    },
}

DEFAULT_SUBTITLE_TRACKS = [
    ("nosub", None, "자막 없음"),
    ("ko", "subtitle.srt", "한국어"),
    ("en", "subtitle_en.srt", "English"),
    ("es", "subtitle_es.srt", "Español"),
]


def ts_to_sec(ts):
    parts = ts.replace(",", ".").split(":")
    return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])


@lru_cache(maxsize=None)
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


@lru_cache(maxsize=None)
def has_audio_stream(input_video):
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=index",
        "-of", "csv=p=0",
        input_video,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return bool(result.stdout.strip())


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
    return build_scale_pad_to_size(crop_w, crop_h, OUTPUT_WIDTH, OUTPUT_HEIGHT)


def build_scale_pad_to_size(crop_w, crop_h, target_w, target_h):
    """
    크롭된 영상을 target size에 맞추는 필터.
    비율이 더 넓으면 위아래 검은 여백, 더 좁으면 좌우 여백을 추가한다.
    """
    crop_ratio = crop_w / crop_h
    target_ratio = target_w / target_h

    if abs(crop_ratio - target_ratio) < 0.01:
        return f"scale={target_w}:{target_h},setsar=1"
    elif crop_ratio > target_ratio:
        scaled_h = int(target_w / crop_ratio)
        return f"scale={target_w}:{scaled_h},pad={target_w}:{target_h}:0:({target_h}-{scaled_h})/2:black,setsar=1"
    else:
        scaled_w = int(target_h * crop_ratio)
        return f"scale={scaled_w}:{target_h},pad={target_w}:{target_h}:({target_w}-{scaled_w})/2:0:black,setsar=1"


def escape_filter_path(path):
    return path.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def escape_drawtext_text(text):
    return (
        text.replace("\\", r"\\")
        .replace(":", r"\:")
        .replace("'", r"\'")
        .replace('"', r'\"')
        .replace("%", r"\%")
        .replace(",", r"\,")
        .replace("\n", r"\n")
    )


def normalize_font_name(value):
    text = str(value or "").strip().lower()
    return "".join(ch for ch in text if ch.isalnum())


@lru_cache(maxsize=1)
def get_font_catalog():
    try:
        result = subprocess.run(
            ["fc-list", "-f", "%{family}\t%{style}\t%{file}\n"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []

    entries = []
    for raw_line in result.stdout.splitlines():
        parts = raw_line.strip().split("\t")
        if len(parts) != 3:
            continue
        family_part, style_part, file_path = parts
        file_path = file_path.strip()
        if not file_path or not os.path.exists(file_path):
            continue
        aliases = []
        for family in family_part.split(","):
            family = family.strip()
            if family:
                aliases.append(family)
        style = style_part.strip()
        if style:
            aliases.append(style)
        stem = os.path.splitext(os.path.basename(file_path))[0]
        if stem:
            aliases.append(stem)
        entries.append({
            "aliases": aliases,
            "file": file_path,
        })
    return entries


def resolve_font_file_for_name(font_name):
    query = normalize_font_name(font_name)
    if not query:
        return None

    best_score = None
    best_entry = None
    best_alias = None

    for entry in get_font_catalog():
        for alias in entry["aliases"]:
            alias_norm = normalize_font_name(alias)
            if not alias_norm:
                continue
            score = None
            if alias_norm == query:
                score = 1000
            elif alias_norm.startswith(query):
                score = 800 - max(0, len(alias_norm) - len(query))
            elif query in alias_norm:
                score = 700 - max(0, len(alias_norm) - len(query))
            elif alias_norm in query:
                score = 500 - max(0, len(query) - len(alias_norm))

            if score is None:
                continue
            if best_score is None or score > best_score:
                best_score = score
                best_entry = entry
                best_alias = alias

    if best_entry is None:
        return None

    return {
        "file": best_entry["file"],
        "alias": best_alias,
    }


def contains_probable_emoji(text):
    for ch in text:
        code = ord(ch)
        if (
            0x1F300 <= code <= 0x1FAFF or
            0x2600 <= code <= 0x27BF or
            0xFE00 <= code <= 0xFE0F
        ):
            return True
    return False


def parse_non_negative_float(value, field_name):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise SystemExit(f"{field_name}는 숫자여야 합니다: {value}")
    if parsed < 0:
        raise SystemExit(f"{field_name}는 0 이상이어야 합니다: {value}")
    return parsed


def resolve_fade_param(format_options, specific_key, shared_key, default_value):
    value = format_options.get(specific_key)
    source_key = specific_key
    if value is None:
        value = format_options.get(shared_key)
        source_key = shared_key
    if value is None:
        return float(default_value)
    return parse_non_negative_float(value, source_key)


def resolve_fade_start(format_options, specific_key, shared_key, duration, default_start):
    value = format_options.get(specific_key)
    source_key = specific_key
    if value is None:
        value = format_options.get(shared_key)
        source_key = shared_key
    if value is None:
        resolved = float(default_start)
    else:
        resolved = parse_non_negative_float(value, source_key)
    return max(0.0, min(float(duration), resolved))


def build_final_video_fade_filter(format_options, render_duration):
    filters = []

    fade_in_sec = resolve_fade_param(format_options, "video_fade_in_sec", "fade_in_sec", DEFAULT_FADE_IN_SEC)
    if fade_in_sec > 0:
        fade_in_start = resolve_fade_start(
            format_options,
            "video_fade_in_start_sec",
            "fade_in_start_sec",
            render_duration,
            0.0,
        )
        filters.append(f"fade=t=in:st={fade_in_start:.3f}:d={fade_in_sec:.3f}")

    fade_out_sec = resolve_fade_param(format_options, "video_fade_out_sec", "fade_out_sec", DEFAULT_FADE_OUT_SEC)
    if fade_out_sec > 0:
        fade_out_start = resolve_fade_start(
            format_options,
            "video_fade_out_start_sec",
            "fade_out_start_sec",
            render_duration,
            max(0.0, render_duration - fade_out_sec),
        )
        filters.append(f"fade=t=out:st={fade_out_start:.3f}:d={fade_out_sec:.3f}")

    return ",".join(filters)


def build_final_audio_fade_filter(format_options, render_duration):
    filters = []

    fade_in_sec = resolve_fade_param(format_options, "audio_fade_in_sec", "fade_in_sec", DEFAULT_FADE_IN_SEC)
    if fade_in_sec > 0:
        fade_in_start = resolve_fade_start(
            format_options,
            "audio_fade_in_start_sec",
            "fade_in_start_sec",
            render_duration,
            0.0,
        )
        filters.append(f"afade=t=in:st={fade_in_start:.3f}:d={fade_in_sec:.3f}")

    fade_out_sec = resolve_fade_param(format_options, "audio_fade_out_sec", "fade_out_sec", DEFAULT_FADE_OUT_SEC)
    if fade_out_sec > 0:
        fade_out_start = resolve_fade_start(
            format_options,
            "audio_fade_out_start_sec",
            "fade_out_start_sec",
            render_duration,
            max(0.0, render_duration - fade_out_sec),
        )
        filters.append(f"afade=t=out:st={fade_out_start:.3f}:d={fade_out_sec:.3f}")

    return ",".join(filters)


def build_subtitle_style(subtitle_y_ratio=SUBTITLE_Y_RATIO, subtitle_font=SUBTITLE_FONT, subtitle_size_delta=0):
    """캔버스 비율 기반 자막 스타일 생성.
    libass FontSize는 PlayResY(기본 288) 기준이므로 변환 필요."""
    PLAY_RES_Y = 288  # libass SRT 기본값
    fontsize = max(1, round(SUBTITLE_SIZE_RATIO * PLAY_RES_Y) + int(subtitle_size_delta))
    margin_v = round(PLAY_RES_Y * (1 - subtitle_y_ratio))
    return (
        f"FontName={subtitle_font},FontSize={fontsize},"
        f"{_SUBTITLE_BASE},MarginV={margin_v}"
    )


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


def load_subtitle_tracks(srtdir, subtitle_config_path=None):
    if not subtitle_config_path:
        tracks = [
            {"suffix": suffix, "srt": srt_name, "label": label}
            for suffix, srt_name, label in DEFAULT_SUBTITLE_TRACKS
        ]
    else:
        with open(subtitle_config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        tracks = raw.get("tracks", raw)
        if not isinstance(tracks, list):
            raise SystemExit("subtitle config는 tracks 배열 또는 배열 자체여야 합니다.")

    available = []
    for track in tracks:
        if not isinstance(track, dict):
            raise SystemExit("subtitle config의 각 track 항목은 객체여야 합니다.")
        suffix = str(track.get("suffix", "")).strip()
        label = str(track.get("label", suffix)).strip() or suffix
        if not suffix:
            raise SystemExit("subtitle config의 각 track 항목에는 suffix가 필요합니다.")

        srt_name = track.get("srt")
        if not srt_name:
            available.append((suffix, None, label))
            continue

        if os.path.isabs(str(srt_name)):
            srt_path = str(srt_name)
        else:
            srt_path = os.path.join(srtdir, str(srt_name))

        if os.path.exists(srt_path):
            available.append((suffix, srt_path, label))
        else:
            print(f"  Skip [{suffix}]: {srt_name} 없음")

    return available


def sec_to_srt_ts(sec):
    """초 → SRT 타임스탬프 (HH:MM:SS,mmm)"""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def sec_to_ffmpeg_ts(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def collect_shifted_srt_entries(srt_path, clip_start, clip_end, output_offset=0.0):
    """클립 구간 자막을 추출해 output_offset 기준으로 재배치한다."""
    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()

    blocks = re.split(r"\n\n+", content.strip())
    entries = []

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        m = re.match(r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})", lines[1])
        if not m:
            continue
        start = ts_to_sec(m.group(1))
        end = ts_to_sec(m.group(2))

        # 클립 범위와 겹치는 자막만 포함 (앞뒤 1초 여유)
        if end < clip_start - 1 or start > clip_end + 1:
            continue

        # 타임스탬프 시프트 (clip_start를 0으로) 후 output_offset 적용
        new_start = max(0, start - clip_start) + output_offset
        new_end = max(0, end - clip_start) + output_offset
        text = "\n".join(lines[2:])
        entries.append((new_start, new_end, text))

    return entries


def write_srt_entries(entries, tmpdir):
    shifted = []
    for idx, (start, end, text) in enumerate(entries, start=1):
        shifted.append(f"{idx}\n{sec_to_srt_ts(start)} --> {sec_to_srt_ts(end)}\n{text}")
    tmp_srt = os.path.join(tmpdir, "subs.srt")
    with open(tmp_srt, "w", encoding="utf-8") as f:
        f.write("\n\n".join(shifted) + "\n")
    return tmp_srt


def parse_srt_entries(srt_path):
    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()

    blocks = re.split(r"\n\n+", content.strip())
    entries = []
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        m = re.match(
            r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})",
            lines[1],
        )
        if not m:
            continue
        entries.append({
            "start": ts_to_sec(m.group(1)),
            "end": ts_to_sec(m.group(2)),
            "text": "\n".join(lines[2:]).strip(),
        })
    return entries


def make_shifted_srt(srt_path, clip_start, clip_end, tmpdir):
    """단일 구간 자막만 추출하고 타임스탬프를 0 기준으로 시프트한 임시 SRT 생성"""
    entries = collect_shifted_srt_entries(srt_path, clip_start, clip_end, output_offset=0.0)
    return write_srt_entries(entries, tmpdir)


def make_composite_srt(segments, tmpdir):
    """여러 구간 자막을 하나의 타임라인으로 합친 임시 SRT 생성"""
    entries = []
    for segment in segments:
        entries.extend(
            collect_shifted_srt_entries(
                segment["srt_path"],
                segment["clip_start"],
                segment["clip_end"],
                output_offset=segment.get("output_offset", 0.0),
            )
        )
    entries.sort(key=lambda item: (item[0], item[1]))
    return write_srt_entries(entries, tmpdir)


def normalize_format_entry(entry, base_dir, fallback_preset):
    data = dict(entry or {})
    preset = data.get("preset") or fallback_preset or DEFAULT_FORMAT_PRESET
    if preset not in FORMAT_PRESETS:
        raise SystemExit(f"알 수 없는 format preset: {preset}")
    data["preset"] = preset

    for key in (
        "title",
        "brand_text",
        "primary_label",
        "secondary_label",
        "secondary_ss",
        "secondary_t",
        "secondary_crop",
        "secondary_srt",
        "split_play_mode",
        "subtitle_renderer",
        "subtitle_font",
        "font_profile",
    ):
        if data.get(key) is not None:
            data[key] = str(data[key]).strip()

    if data.get("subtitle_size_delta") is not None:
        data["subtitle_size_delta"] = int(data["subtitle_size_delta"])

    if data.get("subtitle_max_width_ratio") is not None:
        data["subtitle_max_width_ratio"] = float(data["subtitle_max_width_ratio"])

    for key in (
        "fade_in_sec",
        "fade_out_sec",
        "fade_in_start_sec",
        "fade_out_start_sec",
        "video_fade_in_sec",
        "video_fade_out_sec",
        "video_fade_in_start_sec",
        "video_fade_out_start_sec",
        "audio_fade_in_sec",
        "audio_fade_out_sec",
        "audio_fade_in_start_sec",
        "audio_fade_out_start_sec",
    ):
        if data.get(key) is not None:
            data[key] = parse_non_negative_float(data[key], key)

    secondary_input = data.get("secondary_input")
    if secondary_input:
        if not os.path.isabs(secondary_input):
            secondary_input = os.path.join(base_dir, secondary_input)
        secondary_input = os.path.abspath(secondary_input)
        if not os.path.exists(secondary_input):
            raise SystemExit(f"secondary_input 파일이 없습니다: {secondary_input}")
        data["secondary_input"] = secondary_input

    secondary_srt = data.get("secondary_srt")
    if secondary_srt:
        if not os.path.isabs(secondary_srt):
            secondary_srt = os.path.join(base_dir, secondary_srt)
        secondary_srt = os.path.abspath(secondary_srt)
        if not os.path.exists(secondary_srt):
            raise SystemExit(f"secondary_srt 파일이 없습니다: {secondary_srt}")
        data["secondary_srt"] = secondary_srt

    logo_path = data.get("logo_path")
    if logo_path:
        if not os.path.isabs(logo_path):
            logo_path = os.path.join(base_dir, logo_path)
        logo_path = os.path.abspath(logo_path)
        if not os.path.exists(logo_path):
            raise SystemExit(f"logo_path 파일이 없습니다: {logo_path}")
        data["logo_path"] = logo_path

    subtitle_fontfile = data.get("subtitle_fontfile")
    if subtitle_fontfile:
        if not os.path.isabs(subtitle_fontfile):
            subtitle_fontfile = os.path.join(base_dir, subtitle_fontfile)
        subtitle_fontfile = os.path.abspath(subtitle_fontfile)
        if not os.path.exists(subtitle_fontfile):
            raise SystemExit(f"subtitle_fontfile 파일이 없습니다: {subtitle_fontfile}")
        data["subtitle_fontfile"] = subtitle_fontfile

    subtitle_font_by_suffix = data.get("subtitle_font_by_suffix")
    if subtitle_font_by_suffix is not None:
        if not isinstance(subtitle_font_by_suffix, dict):
            raise SystemExit("subtitle_font_by_suffix는 객체여야 합니다.")
        data["subtitle_font_by_suffix"] = {
            str(key).strip(): str(value).strip()
            for key, value in subtitle_font_by_suffix.items()
            if str(key).strip() and str(value).strip()
        }

    font_profile_by_suffix = data.get("font_profile_by_suffix")
    if font_profile_by_suffix is not None:
        if not isinstance(font_profile_by_suffix, dict):
            raise SystemExit("font_profile_by_suffix는 객체여야 합니다.")
        data["font_profile_by_suffix"] = {
            str(key).strip(): str(value).strip()
            for key, value in font_profile_by_suffix.items()
            if str(key).strip() and str(value).strip()
        }

    subtitle_renderer_by_suffix = data.get("subtitle_renderer_by_suffix")
    if subtitle_renderer_by_suffix is not None:
        if not isinstance(subtitle_renderer_by_suffix, dict):
            raise SystemExit("subtitle_renderer_by_suffix는 객체여야 합니다.")
        data["subtitle_renderer_by_suffix"] = {
            str(key).strip(): str(value).strip()
            for key, value in subtitle_renderer_by_suffix.items()
            if str(key).strip() and str(value).strip()
        }

    subtitle_fontfile_by_suffix = data.get("subtitle_fontfile_by_suffix")
    if subtitle_fontfile_by_suffix is not None:
        if not isinstance(subtitle_fontfile_by_suffix, dict):
            raise SystemExit("subtitle_fontfile_by_suffix는 객체여야 합니다.")
        normalized = {}
        for key, value in subtitle_fontfile_by_suffix.items():
            suffix = str(key).strip()
            font_path = str(value).strip()
            if not suffix or not font_path:
                continue
            if not os.path.isabs(font_path):
                font_path = os.path.join(base_dir, font_path)
            font_path = os.path.abspath(font_path)
            if not os.path.exists(font_path):
                raise SystemExit(f"subtitle_fontfile_by_suffix 파일이 없습니다: {font_path}")
            normalized[suffix] = font_path
        data["subtitle_fontfile_by_suffix"] = normalized

    return data


def load_format_config(path):
    if not path:
        return {"path": None, "defaults": {"preset": DEFAULT_FORMAT_PRESET}, "clips": {}}

    config_path = os.path.abspath(path)
    with open(config_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    base_dir = os.path.dirname(config_path)
    defaults = normalize_format_entry(raw.get("defaults", {}), base_dir, DEFAULT_FORMAT_PRESET)

    raw_clips = raw.get("clips", [])
    if isinstance(raw_clips, dict):
        raw_clips = [
            {**(value or {}), "name": key}
            for key, value in raw_clips.items()
        ]
    elif not isinstance(raw_clips, list):
        raise SystemExit("format config의 clips는 배열 또는 객체여야 합니다.")

    clips = {}
    for entry in raw_clips:
        if not isinstance(entry, dict):
            raise SystemExit("format config의 각 clip 항목은 객체여야 합니다.")
        name = str(entry.get("name", "")).strip()
        if not name:
            raise SystemExit("format config의 각 clip 항목에는 name이 필요합니다.")
        clips[name] = normalize_format_entry(entry, base_dir, defaults["preset"])

    return {"path": config_path, "defaults": defaults, "clips": clips}


def get_clip_format_options(clip_name, format_config):
    defaults = dict(format_config["defaults"])
    clip_overrides = dict(format_config["clips"].get(clip_name, {}))
    preset_name = clip_overrides.get("preset") or defaults.get("preset") or DEFAULT_FORMAT_PRESET

    merged = dict(FORMAT_PRESETS[preset_name])
    merged["preset"] = preset_name
    merged["layout_mode"] = merged.get("layout_mode", "single")

    for source in (defaults, clip_overrides):
        for key, value in source.items():
            if key == "name" or value is None:
                continue
            merged[key] = value

    if merged.get("font_profile"):
        try:
            merged = apply_font_profile_defaults(merged, merged["font_profile"])
        except ValueError as exc:
            raise SystemExit(str(exc))

    return merged


def apply_track_format_overrides(format_options, suffix):
    merged = dict(format_options)

    font_profile_by_suffix = merged.get("font_profile_by_suffix")
    if isinstance(font_profile_by_suffix, dict) and suffix in font_profile_by_suffix:
        try:
            merged = apply_font_profile_defaults(merged, font_profile_by_suffix[suffix])
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
        overrides = merged.get(map_key)
        if isinstance(overrides, dict) and suffix in overrides:
            merged[key] = overrides[suffix]

    subtitle_font = merged.get("subtitle_font")
    if subtitle_font and not merged.get("subtitle_fontfile"):
        resolved = resolve_font_file_for_name(subtitle_font)
        if resolved:
            merged["subtitle_fontfile"] = resolved["file"]
            merged.setdefault("subtitle_font_resolved_alias", resolved["alias"])
        else:
            merged.setdefault("subtitle_font_resolution_note", "font file unresolved; renderer fallback may differ")
    return merged


def describe_subtitle_style(format_options):
    renderer = (format_options.get("subtitle_renderer") or "libass").strip().lower()
    font_name = format_options.get("subtitle_font", SUBTITLE_FONT)
    font_file = format_options.get("subtitle_fontfile")
    resolved_alias = format_options.get("subtitle_font_resolved_alias")
    if renderer == "libass":
        return f"{renderer}, font='{font_name}'"
    if font_file and resolved_alias:
        return f"{renderer}, font='{font_name}' -> '{resolved_alias}' ({os.path.basename(font_file)})"
    if font_file:
        return f"{renderer}, font='{font_name}' ({os.path.basename(font_file)})"
    note = format_options.get("subtitle_font_resolution_note")
    if note:
        return f"{renderer}, font='{font_name}' ({note})"
    return f"{renderer}, font='{font_name}'"


def get_secondary_media_info(primary_input, clip_ss, clip_t, format_options):
    layout_mode = format_options.get("layout_mode", "single")
    if layout_mode not in {"split", "stitch"}:
        return None

    secondary_input = format_options.get("secondary_input") or primary_input
    if not os.path.exists(secondary_input):
        raise SystemExit(f"secondary input 파일이 없습니다: {secondary_input}")

    secondary_ss = format_options.get("secondary_ss") or clip_ss
    secondary_t = format_options.get("secondary_t") or clip_t
    secondary_duration = ts_to_sec(secondary_t)
    sec_w, sec_h = get_video_dimensions(secondary_input)
    secondary_crop_spec = format_options.get("secondary_crop") or ""
    secondary_crop_params = parse_crop_spec(secondary_crop_spec, sec_w, sec_h)

    return {
        "path": secondary_input,
        "ss": secondary_ss,
        "t": secondary_t,
        "duration": secondary_duration,
        "has_audio": has_audio_stream(secondary_input),
        "crop_params": secondary_crop_params,
    }


def get_secondary_srt_path(primary_input, primary_srt_path, format_options):
    if format_options.get("secondary_srt"):
        return format_options["secondary_srt"]
    secondary_input = format_options.get("secondary_input") or primary_input
    if primary_srt_path and os.path.abspath(secondary_input) == os.path.abspath(primary_input):
        return primary_srt_path
    return None


def get_split_layout(format_options):
    direction = format_options.get("split_direction", "left_right")
    gap = int(format_options.get("split_gap", 20))
    primary_panel = format_options.get("primary_panel", "left")

    if direction == "left_right":
        panel_w = (OUTPUT_WIDTH - gap) // 2
        left_rect = (0, 0, panel_w, OUTPUT_HEIGHT)
        right_rect = (OUTPUT_WIDTH - panel_w, 0, panel_w, OUTPUT_HEIGHT)
        primary_rect, secondary_rect = (right_rect, left_rect) if primary_panel == "right" else (left_rect, right_rect)
    elif direction == "top_bottom":
        panel_h = (OUTPUT_HEIGHT - gap) // 2
        top_rect = (0, 0, OUTPUT_WIDTH, panel_h)
        bottom_rect = (0, OUTPUT_HEIGHT - panel_h, OUTPUT_WIDTH, panel_h)
        primary_rect, secondary_rect = (bottom_rect, top_rect) if primary_panel == "bottom" else (top_rect, bottom_rect)
    else:
        raise SystemExit(f"알 수 없는 split_direction: {direction}")

    return {
        "direction": direction,
        "gap": gap,
        "primary_rect": primary_rect,
        "secondary_rect": secondary_rect,
    }


def build_panel_label_filters(format_options, layout_meta):
    if not layout_meta:
        return []

    filters = []
    box_w = int(format_options.get("panel_label_box_width", 180))
    box_h = int(format_options.get("panel_label_box_height", 64))
    margin = int(format_options.get("panel_label_margin", 24))
    font_size = int(format_options.get("panel_label_font_size", 28))
    box_color = format_options.get("panel_label_box_color", "black@0.55")
    label_font = escape_drawtext_text(DISPLAY_FONT)
    title_offset = int(format_options.get("title_box_height", 0) or 0)

    for label_key, rect_key in (("primary_label", "primary_rect"), ("secondary_label", "secondary_rect")):
        label = (format_options.get(label_key) or "").strip()
        if not label:
            continue
        x, y, w, _ = layout_meta[rect_key]
        box_x = x + margin
        box_y = max(y + margin, title_offset + margin)
        label_text = escape_drawtext_text(label)

        filters.append(
            f"drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_h}:color={box_color}:t=fill"
        )
        filters.append(
            f"drawtext=font='{label_font}'"
            f":text='{label_text}'"
            f":fontsize={font_size}"
            f":fontcolor=white:borderw=2:bordercolor=black"
            f":x={box_x}+({box_w}-text_w)/2"
            f":y={box_y}+({box_h}-text_h)/2"
        )

    return filters


def build_format_draw_filters(format_options, layout_meta=None):
    filters = []
    title = (format_options.get("title") or "").strip()
    title_box_height = int(format_options.get("title_box_height", 0) or 0)

    if title and title_box_height > 0:
        title_text = escape_drawtext_text(title)
        title_font = escape_drawtext_text(DISPLAY_FONT)
        title_box_color = format_options.get("title_box_color", "black@0.45")
        title_font_size = int(format_options.get("title_font_size", 72))
        title_y = int(format_options.get("title_y", 72))
        title_align = format_options.get("title_align", "left")

        filters.append(
            f"drawbox=x=0:y=0:w=iw:h={title_box_height}:color={title_box_color}:t=fill"
        )
        title_x = "(w-text_w)/2" if title_align == "center" else str(int(format_options.get("title_x_margin", 64)))
        filters.append(
            f"drawtext=font='{title_font}'"
            f":text='{title_text}'"
            f":fontsize={title_font_size}"
            f":fontcolor=white:borderw=2:bordercolor=black"
            f":line_spacing=10"
            f":x={title_x}:y={title_y}"
        )

    filters.extend(build_panel_label_filters(format_options, layout_meta))

    brand_mode = format_options.get("brand_mode", "none")
    brand_text = (format_options.get("brand_text") or "").strip()
    should_draw_brand_text = brand_mode in {"text", "logo_or_text"} and brand_text and not format_options.get("logo_path")

    if should_draw_brand_text:
        box_w = int(format_options.get("brand_box_width", 320))
        box_h = int(format_options.get("brand_box_height", 92))
        x_margin = int(format_options.get("brand_x_margin", 48))
        y_margin = int(format_options.get("brand_y_margin", 220))
        x = OUTPUT_WIDTH - box_w - x_margin
        y = OUTPUT_HEIGHT - box_h - y_margin
        brand_font = escape_drawtext_text(DISPLAY_FONT)
        brand_label = escape_drawtext_text(brand_text)
        box_color = format_options.get("brand_box_color", "black@0.68")
        font_size = int(format_options.get("brand_font_size", 34))

        filters.append(
            f"drawbox=x={x}:y={y}:w={box_w}:h={box_h}:color={box_color}:t=fill"
        )
        filters.append(
            f"drawtext=font='{brand_font}'"
            f":text='{brand_label}'"
            f":fontsize={font_size}"
            f":fontcolor=white:borderw=2:bordercolor=black"
            f":x={x}+({box_w}-text_w)/2"
            f":y={y}+({box_h}-text_h)/2"
        )

    return filters


def build_drawtext_subtitle_filters(srt_path, format_options):
    entries = parse_srt_entries(srt_path)
    if not entries:
        return []

    if any(contains_probable_emoji(entry["text"]) for entry in entries):
        print("  Warn: drawtext renderer는 emoji를 안정적으로 렌더하지 못할 수 있습니다. subtitle_renderer='image' 사용을 권장합니다.")
    if any("\n" not in entry["text"] and len(entry["text"]) >= 28 for entry in entries):
        print("  Warn: drawtext renderer는 자동 줄바꿈을 하지 않습니다. 긴 문장은 수동 줄바꿈 또는 subtitle_renderer='image'를 권장합니다.")

    subtitle_fontfile = format_options.get("subtitle_fontfile")
    subtitle_font = format_options.get("subtitle_font", SUBTITLE_FONT)
    font_size = max(1, round(SUBTITLE_SIZE_RATIO * OUTPUT_HEIGHT) + int(format_options.get("subtitle_size_delta", 0)))
    margin_v = round(OUTPUT_HEIGHT * (1 - format_options.get("subtitle_y_ratio", SUBTITLE_Y_RATIO)))
    line_spacing = int(format_options.get("subtitle_line_spacing", 6))
    box_border = int(format_options.get("subtitle_box_border", 18))
    box_color = format_options.get("subtitle_box_color", "black@0.55")
    border_w = int(format_options.get("subtitle_border_w", 2))
    border_color = format_options.get("subtitle_border_color", "black")

    font_expr = f"fontfile='{escape_filter_path(subtitle_fontfile)}'" if subtitle_fontfile else f"font='{escape_drawtext_text(subtitle_font)}'"
    filters = []
    for entry in entries:
        text = escape_drawtext_text(entry["text"])
        start = f"{entry['start']:.3f}"
        end = f"{entry['end']:.3f}"
        enable_expr = f"between(t\\,{start}\\,{end})"
        filters.append(
            "drawtext="
            f"{font_expr}:"
            f"text='{text}':"
            f"fontsize={font_size}:"
            "fontcolor=white:"
            f"borderw={border_w}:"
            f"bordercolor={border_color}:"
            f"line_spacing={line_spacing}:"
            "x=(w-text_w)/2:"
            f"y=h-{margin_v}-text_h:"
            "box=1:"
            f"boxcolor={box_color}:"
            f"boxborderw={box_border}:"
            f"enable='{enable_expr}'"
        )
    return filters


def render_image_subtitle_card(text, output_path, format_options):
    if not os.path.exists(IMAGE_SUBTITLE_RENDERER_PATH):
        raise SystemExit(f"subtitle image renderer 스크립트가 없습니다: {IMAGE_SUBTITLE_RENDERER_PATH}")

    font_name = format_options.get("subtitle_font", SUBTITLE_FONT)
    font_file = format_options.get("subtitle_fontfile")
    base_font_size = max(1, round(SUBTITLE_SIZE_RATIO * OUTPUT_HEIGHT) + int(format_options.get("subtitle_size_delta", 0)))
    max_width_ratio = float(format_options.get("subtitle_max_width_ratio", DEFAULT_SUBTITLE_MAX_WIDTH_RATIO))
    min_side_margin_px = int(format_options.get("subtitle_min_side_margin_px", 0) or 0)
    target_max_width = max(200, int(OUTPUT_WIDTH * max_width_ratio))
    if min_side_margin_px > 0:
        target_max_width = min(target_max_width, max(200, OUTPUT_WIDTH - min_side_margin_px * 2))
    line_spacing = int(format_options.get("subtitle_line_spacing", 6))
    box_color = str(format_options.get("subtitle_box_color", "black@0.55"))
    text_color = str(format_options.get("subtitle_text_color", "white"))
    padding_x = int(format_options.get("subtitle_box_padding_x", 28))
    padding_y = int(format_options.get("subtitle_box_padding_y", 18))
    corner_radius = int(format_options.get("subtitle_corner_radius", 22))
    align = str(format_options.get("subtitle_align", "center")).strip().lower() or "center"
    autofit_step = max(1, int(format_options.get("subtitle_autofit_step", 2) or 2))
    autofit_min_font_size = max(1, int(format_options.get("subtitle_autofit_min_font_size", 22) or 22))
    autofit_max_attempts = max(1, int(format_options.get("subtitle_autofit_max_attempts", 12) or 12))

    text_path = f"{output_path}.txt"
    with open(text_path, "w", encoding="utf-8") as f:
        f.write(text)

    cache_dir = os.path.join(tempfile.gettempdir(), "gshorts-swift-cache")
    os.makedirs(cache_dir, exist_ok=True)
    env = dict(os.environ)
    env["SWIFT_MODULECACHE_PATH"] = cache_dir
    env["CLANG_MODULE_CACHE_PATH"] = cache_dir

    metrics_path = f"{output_path}.metrics.json"
    font_size = base_font_size
    last_metrics = None
    attempts = 0

    while True:
        attempts += 1
        cmd = [
            "swift",
            IMAGE_SUBTITLE_RENDERER_PATH,
            "--text-file", text_path,
            "--output", output_path,
            "--metrics-out", metrics_path,
            "--max-width", str(target_max_width),
            "--font-name", font_name,
            "--font-size", str(font_size),
            "--line-spacing", str(line_spacing),
            "--padding-x", str(padding_x),
            "--padding-y", str(padding_y),
            "--box-color", box_color,
            "--text-color", text_color,
            "--corner-radius", str(corner_radius),
            "--align", align,
        ]
        if font_file:
            cmd += ["--font-file", font_file]
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if result.returncode != 0:
            stderr = (result.stderr or result.stdout or "").strip()
            raise SystemExit(f"subtitle image 생성 실패: {stderr}")

        try:
            with open(metrics_path, "r", encoding="utf-8") as f:
                last_metrics = json.load(f)
        except Exception:
            last_metrics = None

        image_width = int(last_metrics.get("image_width", 0)) if isinstance(last_metrics, dict) else 0
        side_margin = (OUTPUT_WIDTH - image_width) / 2 if image_width else OUTPUT_WIDTH / 2
        fits_side_margin = (min_side_margin_px <= 0) or (side_margin >= min_side_margin_px)
        fits_width = (image_width <= target_max_width + 1) if image_width else True

        if fits_side_margin and fits_width:
            if font_size != base_font_size:
                print(
                    f"  subtitle autofit: '{text[:24].replace(chr(10), ' / ')}' "
                    f"font {base_font_size}->{font_size}, image_width={image_width}, side_margin={side_margin:.0f}px"
                )
            break

        if font_size <= autofit_min_font_size or attempts >= autofit_max_attempts:
            print(
                f"  Warn: subtitle autofit reached limit for '{text[:24].replace(chr(10), ' / ')}' "
                f"(font={font_size}, image_width={image_width}, side_margin={side_margin:.0f}px)"
            )
            break

        font_size = max(autofit_min_font_size, font_size - autofit_step)


def build_image_subtitle_assets(srt_path, format_options, tmpdir):
    entries = parse_srt_entries(srt_path)
    assets = []
    for idx, entry in enumerate(entries, start=1):
        if not entry["text"].strip():
            continue
        image_path = os.path.join(tmpdir, f"subtitle_card_{idx:03d}.png")
        render_image_subtitle_card(entry["text"], image_path, format_options)
        assets.append({
            "path": image_path,
            "start": entry["start"],
            "end": entry["end"],
        })
    return assets


def append_audio_segment(parts, input_index, duration, output_label, has_audio=True):
    if has_audio:
        parts.append(
            f"[{input_index}:a]atrim=duration={duration:.3f},asetpts=PTS-STARTPTS,"
            f"aresample={AUDIO_SAMPLE_RATE},"
            f"aformat=sample_rates={AUDIO_SAMPLE_RATE}:channel_layouts={AUDIO_CHANNEL_LAYOUT}"
            f"[{output_label}]"
        )
        return

    parts.append(
        f"anullsrc=r={AUDIO_SAMPLE_RATE}:cl={AUDIO_CHANNEL_LAYOUT},"
        f"atrim=duration={duration:.3f},asetpts=PTS-STARTPTS[{output_label}]"
    )


def append_faded_audio(parts, input_label, duration, format_options, output_label="aout"):
    audio_fade_filter = build_final_audio_fade_filter(format_options, duration)
    if audio_fade_filter:
        parts.append(f"[{input_label}]{audio_fade_filter}[{output_label}]")
    elif input_label != output_label:
        parts.append(f"[{input_label}]anull[{output_label}]")


def append_output_overlay(
    parts,
    body_label,
    final_video_fade_filter,
    srt_path,
    subtitle_style,
    format_options,
    layout_meta=None,
    logo_input_index=None,
    subtitle_image_inputs=None,
):
    subtitle_image_inputs = subtitle_image_inputs or []
    subtitle_renderer = (format_options.get("subtitle_renderer") or "libass").strip().lower()
    if subtitle_renderer not in {"libass", "drawtext", "image"}:
        raise SystemExit(f"알 수 없는 subtitle_renderer: {subtitle_renderer}")

    filter_chain = []
    if srt_path and subtitle_renderer == "drawtext":
        filter_chain.extend(build_drawtext_subtitle_filters(srt_path, format_options))
    elif srt_path and subtitle_renderer == "libass":
        srt_escaped = escape_filter_path(srt_path)
        filter_chain.append(f"subtitles={srt_escaped}:force_style='{subtitle_style}'")

    draw_filters = build_format_draw_filters(format_options, layout_meta)
    needs_intermediate = bool(subtitle_image_inputs or draw_filters or logo_input_index is not None)

    if filter_chain:
        current_label = "vprep" if needs_intermediate else "vbase"
        parts.append(f"{body_label}{','.join(filter_chain)}[{current_label}]")
    elif needs_intermediate:
        current_label = "vprep"
        parts.append(f"{body_label}null[{current_label}]")
    else:
        current_label = body_label.strip("[]")

    if subtitle_image_inputs:
        margin_v = round(OUTPUT_HEIGHT * (1 - format_options.get("subtitle_y_ratio", SUBTITLE_Y_RATIO)))
        for idx, asset in enumerate(subtitle_image_inputs, start=1):
            next_label = f"vsub{idx}"
            start = f"{asset['start']:.3f}"
            end = f"{asset['end']:.3f}"
            enable_expr = f"between(t\\,{start}\\,{end})"
            parts.append(
                f"[{current_label}][{asset['input_index']}:v]overlay="
                "x=(main_w-overlay_w)/2:"
                f"y=main_h-{margin_v}-overlay_h:"
                f"enable='{enable_expr}'"
                f"[{next_label}]"
            )
            current_label = next_label

    if draw_filters:
        next_label = "base" if logo_input_index is not None else "vbase"
        parts.append(f"[{current_label}]{','.join(draw_filters)}[{next_label}]")
        current_label = next_label
    elif logo_input_index is not None:
        parts.append(f"[{current_label}]null[base]")
        current_label = "base"

    if logo_input_index is None:
        if final_video_fade_filter:
            parts.append(f"[{current_label}]{final_video_fade_filter}[vout]")
        elif current_label != "vout":
            parts.append(f"[{current_label}]null[vout]")
        return

    logo_width = int(format_options.get("logo_max_width", 220))
    logo_x_margin = int(format_options.get("brand_x_margin", 48))
    logo_y_margin = int(format_options.get("brand_y_margin", 220))
    parts.append(f"[{logo_input_index}:v]scale={logo_width}:-1[logo]")
    parts.append(
        f"[{current_label}][logo]overlay="
        f"x=main_w-overlay_w-{logo_x_margin}:"
        f"y=main_h-overlay_h-{logo_y_margin}:format=auto[vlogo]"
    )
    if final_video_fade_filter:
        parts.append(f"[vlogo]{final_video_fade_filter}[vout]")
    else:
        parts.append("[vlogo]null[vout]")


def build_render_plan(input_video, clip_ss, clip_t, crop_params, srt_path, subtitle_style, format_options, subtitle_image_assets=None):
    layout_mode = format_options.get("layout_mode", "single")
    primary_duration = ts_to_sec(clip_t)
    primary_has_audio = has_audio_stream(input_video)
    secondary = get_secondary_media_info(input_video, clip_ss, clip_t, format_options)
    split_play_mode = format_options.get("split_play_mode", "parallel")
    subtitle_image_assets = subtitle_image_assets or []

    if layout_mode == "stitch":
        render_duration = primary_duration + secondary["duration"]
    elif layout_mode == "split" and split_play_mode == "sequential_freeze":
        render_duration = primary_duration + secondary["duration"]
    else:
        render_duration = primary_duration

    final_video_fade_filter = build_final_video_fade_filter(format_options, render_duration)

    brand_mode = format_options.get("brand_mode", "none")
    logo_path = format_options.get("logo_path")
    use_logo = brand_mode in {"logo", "logo_or_text"} and logo_path and os.path.exists(logo_path)

    extra_inputs = []
    next_input_index = 1
    secondary_index = None
    if secondary:
        secondary_index = next_input_index
        extra_inputs += ["-ss", secondary["ss"], "-i", secondary["path"]]
        next_input_index += 1

    subtitle_image_inputs = []
    for asset in subtitle_image_assets:
        subtitle_image_inputs.append({**asset, "input_index": next_input_index})
        extra_inputs += ["-loop", "1", "-i", asset["path"]]
        next_input_index += 1

    logo_input_index = next_input_index if use_logo else None
    if use_logo:
        extra_inputs += ["-loop", "1", "-i", logo_path]

    parts = []
    audio_map = "[aout]"
    layout_meta = None
    cw, ch, cx, cy = crop_params

    if layout_mode == "single":
        scale_pad = build_scale_pad_filter(cw, ch)
        parts.append(f"[0:v]crop={cw}:{ch}:{cx}:{cy},{scale_pad}[body]")
        append_audio_segment(parts, 0, render_duration, "apre", has_audio=primary_has_audio)
        append_faded_audio(parts, "apre", render_duration, format_options)
    elif layout_mode == "split":
        if secondary is None or secondary_index is None:
            raise SystemExit(f"{format_options['preset']} preset은 secondary input이 필요합니다.")
        layout_meta = get_split_layout(format_options)
        p_x, p_y, p_w, p_h = layout_meta["primary_rect"]
        s_x, s_y, s_w, s_h = layout_meta["secondary_rect"]
        sec_cw, sec_ch, sec_cx, sec_cy = secondary["crop_params"]
        primary_scale = build_scale_pad_to_size(cw, ch, p_w, p_h)
        secondary_scale = build_scale_pad_to_size(sec_cw, sec_ch, s_w, s_h)
        if split_play_mode == "parallel":
            secondary_trim = min(primary_duration, secondary["duration"])

            parts.append(
                f"[0:v]crop={cw}:{ch}:{cx}:{cy},{primary_scale},trim=duration={primary_duration:.3f},setpts=PTS-STARTPTS[p0]"
            )
            parts.append(
                f"[{secondary_index}:v]crop={sec_cw}:{sec_ch}:{sec_cx}:{sec_cy},{secondary_scale},"
                f"trim=duration={secondary_trim:.3f},setpts=PTS-STARTPTS[p1]"
            )
            parts.append(f"color=c=black:s={OUTPUT_WIDTH}x{OUTPUT_HEIGHT}:d={render_duration:.3f}[canvas]")
            parts.append(f"[canvas][p0]overlay=x={p_x}:y={p_y}[tmp0]")
            parts.append(f"[tmp0][p1]overlay=x={s_x}:y={s_y}[body]")
            if primary_has_audio:
                append_audio_segment(parts, 0, render_duration, "apre", has_audio=True)
            elif secondary["has_audio"]:
                append_audio_segment(parts, secondary_index, render_duration, "apre", has_audio=True)
            else:
                append_audio_segment(parts, 0, render_duration, "apre", has_audio=False)
            append_faded_audio(parts, "apre", render_duration, format_options)
        elif split_play_mode == "sequential_freeze":
            parts.append(
                f"[0:v]crop={cw}:{ch}:{cx}:{cy},{primary_scale},trim=duration={primary_duration:.3f},setpts=PTS-STARTPTS[p0play]"
            )
            parts.append(
                f"[p0play]tpad=stop_mode=clone:stop_duration={secondary['duration']:.3f}[p0]"
            )
            parts.append(
                f"[{secondary_index}:v]crop={sec_cw}:{sec_ch}:{sec_cx}:{sec_cy},{secondary_scale},"
                f"trim=duration={secondary['duration']:.3f},setpts=PTS-STARTPTS[p1play]"
            )
            parts.append(
                f"[p1play]tpad=start_mode=clone:start_duration={primary_duration:.3f}[p1]"
            )
            parts.append(f"color=c=black:s={OUTPUT_WIDTH}x{OUTPUT_HEIGHT}:d={render_duration:.3f}[canvas]")
            parts.append(f"[canvas][p0]overlay=x={p_x}:y={p_y}[tmp0]")
            parts.append(f"[tmp0][p1]overlay=x={s_x}:y={s_y}[body]")
            append_audio_segment(parts, 0, primary_duration, "a0", has_audio=primary_has_audio)
            append_audio_segment(parts, secondary_index, secondary["duration"], "a1", has_audio=secondary["has_audio"])
            parts.append("[a0][a1]concat=n=2:v=0:a=1[acat]")
            append_faded_audio(parts, "acat", render_duration, format_options)
        else:
            raise SystemExit(f"알 수 없는 split_play_mode: {split_play_mode}")
    elif layout_mode == "stitch":
        if secondary is None or secondary_index is None:
            raise SystemExit(f"{format_options['preset']} preset은 secondary input이 필요합니다.")
        sec_cw, sec_ch, sec_cx, sec_cy = secondary["crop_params"]
        primary_scale = build_scale_pad_filter(cw, ch)
        secondary_scale = build_scale_pad_filter(sec_cw, sec_ch)

        parts.append(
            f"[0:v]crop={cw}:{ch}:{cx}:{cy},{primary_scale},trim=duration={primary_duration:.3f},setpts=PTS-STARTPTS[p0]"
        )
        parts.append(
            f"[{secondary_index}:v]crop={sec_cw}:{sec_ch}:{sec_cx}:{sec_cy},{secondary_scale},"
            f"trim=duration={secondary['duration']:.3f},setpts=PTS-STARTPTS[p1]"
        )
        parts.append("[p0][p1]concat=n=2:v=1:a=0[body]")
        append_audio_segment(parts, 0, primary_duration, "a0", has_audio=primary_has_audio)
        append_audio_segment(parts, secondary_index, secondary["duration"], "a1", has_audio=secondary["has_audio"])
        parts.append("[a0][a1]concat=n=2:v=0:a=1[acat]")
        append_faded_audio(parts, "acat", render_duration, format_options)
    else:
        raise SystemExit(f"알 수 없는 layout_mode: {layout_mode}")

    append_output_overlay(
        parts,
        "[body]",
        final_video_fade_filter,
        srt_path,
        subtitle_style,
        format_options,
        layout_meta=layout_meta,
        logo_input_index=logo_input_index,
        subtitle_image_inputs=subtitle_image_inputs,
    )

    return {
        "extra_inputs": extra_inputs,
        "filter_complex": ";".join(parts),
        "audio_map": audio_map,
        "render_duration_ts": sec_to_ffmpeg_ts(render_duration),
        "render_duration": render_duration,
    }


def encode_clip(input_video, clip_ss, clip_t, output_path, srt_path, crop_params, format_options):
    """단일 클립 인코딩 (fade in/out 포함, -ss를 -i 앞에 배치하여 빠른 탐색)"""
    subtitle_style = build_subtitle_style(
        format_options.get("subtitle_y_ratio", SUBTITLE_Y_RATIO),
        format_options.get("subtitle_font", SUBTITLE_FONT),
        format_options.get("subtitle_size_delta", 0),
    )
    duration = ts_to_sec(clip_t)
    clip_start = ts_to_sec(clip_ss)
    secondary = get_secondary_media_info(input_video, clip_ss, clip_t, format_options)
    split_play_mode = format_options.get("split_play_mode", "parallel")

    tmpdir = None
    shifted_srt_path = None
    subtitle_image_assets = []
    if srt_path:
        # 클립 구간 자막을 0 기준으로 시프트한 임시 SRT 생성
        tmpdir = tempfile.mkdtemp(prefix="gshorts_")
        subtitle_segments = [{
            "srt_path": srt_path,
            "clip_start": clip_start,
            "clip_end": clip_start + duration,
            "output_offset": 0.0,
        }]

        needs_secondary_subtitles = (
            secondary is not None and
            (
                format_options.get("layout_mode") == "stitch" or
                (format_options.get("layout_mode") == "split" and split_play_mode == "sequential_freeze")
            )
        )
        if needs_secondary_subtitles:
            secondary_srt_path = get_secondary_srt_path(input_video, srt_path, format_options)
            if secondary_srt_path:
                secondary_start = ts_to_sec(secondary["ss"])
                subtitle_segments.append({
                    "srt_path": secondary_srt_path,
                    "clip_start": secondary_start,
                    "clip_end": secondary_start + secondary["duration"],
                    "output_offset": duration,
                })

        shifted_srt_path = make_composite_srt(subtitle_segments, tmpdir)
        subtitle_renderer = (format_options.get("subtitle_renderer") or "libass").strip().lower()
        if subtitle_renderer == "image":
            subtitle_image_assets = build_image_subtitle_assets(shifted_srt_path, format_options, tmpdir)

    render_plan = build_render_plan(
        input_video,
        clip_ss,
        clip_t,
        crop_params,
        shifted_srt_path,
        subtitle_style,
        format_options,
        subtitle_image_assets=subtitle_image_assets,
    )

    # 항상 -ss를 -i 앞에 배치 → 빠른 탐색
    cmd = [
        "ffmpeg", "-y",
        "-ss", clip_ss,
        "-i", input_video,
    ]
    cmd += [
        *render_plan["extra_inputs"],
        "-t", render_plan["render_duration_ts"],
        "-filter_complex", render_plan["filter_complex"],
        "-map", "[vout]",
        "-map", render_plan["audio_map"],
    ]

    cmd += [
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if tmpdir:
        shutil.rmtree(tmpdir, ignore_errors=True)

    if result.returncode != 0:
        print(f"\nFFmpeg failed for {output_path}", flush=True)
        stderr = (result.stderr or "").strip()
        if stderr:
            tail = "\n".join(stderr.splitlines()[-40:])
            print(tail, flush=True)

    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="YouTube Shorts 생성기 (다국어 + 자유 크롭)")
    parser.add_argument("--input", "-i", required=True, help="원본 영상 파일")
    parser.add_argument("--clips", "-c", required=True, help="클립 목록 파일")
    parser.add_argument("--srtdir", "-s", required=True, help="자막 파일 디렉토리")
    parser.add_argument("--outdir", "-o", default="output", help="출력 디렉토리")
    parser.add_argument("--format-config", help="format preset 설정 JSON (선택)")
    parser.add_argument("--subtitle-config", help="subtitle track 설정 JSON (선택)")
    parser.add_argument("--workers", "-w", type=int, default=4, help="병렬 인코딩 수")
    args = parser.parse_args()

    src_w, src_h = get_video_dimensions(args.input)
    print(f"Source: {src_w}x{src_h}")
    format_config = load_format_config(args.format_config)
    if format_config["path"]:
        print(f"Format config: {format_config['path']}")
    else:
        print(f"Format config: 기본값 ({DEFAULT_FORMAT_PRESET})")

    clips = parse_clips_file(args.clips)
    print(f"Clips: {len(clips)}")

    # 크롭 정보 표시
    for ss, t, name, crop_spec in clips:
        cw, ch, cx, cy = parse_crop_spec(crop_spec, src_w, src_h)
        ratio = f"{cw/ch:.2f}"
        format_options = get_clip_format_options(name, format_config)
        title = format_options.get("title")
        layout_mode = format_options.get("layout_mode", "single")
        secondary = get_secondary_media_info(args.input, ss, t, format_options)
        title_suffix = f", title='{title}'" if title else ""
        secondary_suffix = ""
        if secondary:
            secondary_name = os.path.basename(secondary["path"])
            secondary_suffix = f", secondary={secondary_name}@{secondary['ss']}"
        print(
            f"  {name}: crop {cw}x{ch} at ({cx},{cy}) ratio={ratio}"
            f", preset={format_options['preset']}, layout={layout_mode}{title_suffix}{secondary_suffix}"
        )

    # 사용 가능한 언어 확인
    available_langs = load_subtitle_tracks(args.srtdir, args.subtitle_config)

    print(f"Languages: {', '.join(f'{l[2]}' for l in available_langs)}")
    print("Subtitle styles:")
    for ss, t, name, _ in clips:
        base_format_options = get_clip_format_options(name, format_config)
        print(f"  {name}:")
        for suffix, _, label in available_langs:
            format_options = apply_track_format_overrides(base_format_options, suffix)
            print(f"    [{suffix}] {label}: {describe_subtitle_style(format_options)}")
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
                format_options = apply_track_format_overrides(
                    get_clip_format_options(name, format_config),
                    suffix,
                )
                out_path = os.path.join(args.outdir, suffix, name)
                futures.append((
                    pool.submit(
                        encode_clip,
                        args.input,
                        ss,
                        t,
                        out_path,
                        srt_path,
                        crop_params,
                        format_options,
                    ),
                    suffix,
                    name,
                    format_options["preset"],
                ))

        for future, suffix, name, preset in futures:
            ok = future.result()
            done += 1
            status = "OK" if ok else "FAIL"
            print(f"  [{done}/{total}] [{suffix}] {name} ({preset}) — {status}")

    print(f"\n=== 완료: {total}개 영상 생성 ===")
    for suffix, _, label in available_langs:
        lang_dir = os.path.join(args.outdir, suffix)
        count = len([f for f in os.listdir(lang_dir) if f.endswith(".mp4")])
        print(f"  {lang_dir}/ — {label} ({count}개)")


if __name__ == "__main__":
    main()
