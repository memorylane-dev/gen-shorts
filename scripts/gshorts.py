#!/usr/bin/env python3
"""Single-short manifest CLI for gshorts."""

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from shorts_targets import (
    TARGET_PROFILES,
    build_subtitle_tracks,
    get_required_translation_langs,
    get_target_profiles,
    parse_target_codes,
)


SCRIPT_DIR = Path(__file__).resolve().parent
MAKE_SHORTS_PATH = SCRIPT_DIR / "08_make_shorts.py"
TRANSLATE_PATH = SCRIPT_DIR / "07_translate.py"

PRESET_DESCRIPTIONS = {
    "clean_fullbleed": "기본형. 영상 중심, 자막만 표시",
    "headline_fullbleed": "상단 제목 바 + 전체 클립",
    "branded_header_logo": "상단 제목 + 하단 브랜드/로고",
    "quote_focus": "명대사/한 줄 강조 카드형",
    "reaction_duet": "좌우 분할 동시 재생",
    "comparison_split": "상하 분할 비교형",
    "stitch_then_punchline": "앞 setup 후 뒤 punchline 연결",
    "alternating_spotlight": "상하 분할 순차형. 한쪽 재생 중 다른 쪽 freeze",
}

REVIEW_SECTION_RE = re.compile(r"^--- \[(.+?)\]\s+(\d{2}:\d{2}:\d{2})")
REVIEW_TEXT_RE = re.compile(r"^\s+\[\d{2}:\d{2}\]\s+(.+)$")
SEARCH_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")
HASHTAG_RE = re.compile(r"#([0-9A-Za-z가-힣_\-]+)")

COMMON_BRIEF_STOPWORDS = {
    "그리고",
    "그다음",
    "다음",
    "그냥",
    "정도",
    "느낌",
    "같이",
    "영상",
    "클립",
    "쇼츠",
    "shorts",
    "short",
    "포맷",
    "편집",
    "형태",
    "방식",
    "자막",
    "제목",
    "로고",
    "브랜드",
    "화면",
    "재생",
    "구간",
    "하나",
    "둘",
    "번갈아",
    "동시에",
    "위아래",
    "상하",
    "좌우",
    "분할",
}

TARGET_ALIASES = [
    ("KR", ["korea", "korean", "한국", "한국어"]),
    ("US", ["usa", "english", "미국", "영어", "영문", "영어권"]),
    ("GB", ["uk", "british", "영국", "영국식"]),
    ("ES", ["spain", "스페인"]),
    ("MX", ["mexico", "spanish", "멕시코", "스페인어", "중남미"]),
    ("JP", ["japan", "japanese", "일본", "일본어"]),
    ("BR", ["brazil", "portuguese", "브라질", "포르투갈어"]),
    ("FR", ["france", "french", "프랑스", "프랑스어"]),
    ("DE", ["germany", "german", "독일", "독일어"]),
    ("CN", ["china", "chinese", "중국", "중국어", "중문", "간체"]),
]


def load_make_shorts_module():
    spec = importlib.util.spec_from_file_location("make_shorts_module", MAKE_SHORTS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MAKE_SHORTS = load_make_shorts_module()
FORMAT_PRESETS = MAKE_SHORTS.FORMAT_PRESETS
DEFAULT_PRESET_NAME = getattr(MAKE_SHORTS, "DEFAULT_FORMAT_PRESET", "clean_fullbleed")
DEFAULT_TARGET_CODES = ["KR", "US"]
RECOMMENDED_SHORT_DURATION_SEC = 35.0


def prompt(text, default=None, required=False):
    suffix = f" [{default}]" if default not in (None, "") else ""
    while True:
        value = input(f"{text}{suffix}: ").strip()
        if value:
            return value
        if default not in (None, ""):
            return default
        if not required:
            return ""


def prompt_yes_no(text, default=True):
    default_text = "Y/n" if default else "y/N"
    while True:
        value = input(f"{text} [{default_text}]: ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False


def print_section(title):
    print(f"\n=== {title} ===", flush=True)


def resolve_path(base_dir, value):
    path = Path(value)
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def is_subpath(path, base):
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def rewrite_spec_paths_for_location(spec, project_dir, spec_path):
    spec = json.loads(json.dumps(spec, ensure_ascii=False))
    spec_dir = spec_path.parent.resolve()
    project_dir = project_dir.resolve()

    def rewrite_value(value):
        if not value:
            return value
        path = Path(value)
        if path.is_absolute():
            return str(path)
        abs_path = (project_dir / path).resolve()
        if is_subpath(spec_dir, project_dir):
            return os.path.relpath(abs_path, spec_dir)
        return str(abs_path)

    for key in ("source_video", "source_srt", "output_dir"):
        if key in spec:
            spec[key] = rewrite_value(spec[key])

    format_spec = spec.get("format") or {}
    if format_spec.get("secondary_input"):
        format_spec["secondary_input"] = rewrite_value(format_spec["secondary_input"])

    return spec


def parse_csv_list(value):
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def humanize_clip_name(name):
    text = Path(name).stem.replace("_", " ").strip()
    return re.sub(r"^\d+\s*", "", text).strip()


def slugify_short_id(value):
    value = str(value or "").strip()
    value = re.sub(r"\s+", "_", value)
    value = value.replace("/", "_")
    value = re.sub(r"[^\w\-]+", "_", value, flags=re.UNICODE)
    value = re.sub(r"_+", "_", value).strip("._-")
    return value or "my_short"


def ts_to_sec(ts):
    parts = str(ts).replace(",", ".").split(":")
    if len(parts) != 3:
        raise ValueError(f"잘못된 timestamp 형식: {ts}")
    return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])


def format_duration_label(seconds):
    total_seconds = max(0, int(round(float(seconds))))
    minutes, secs = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def find_default_source_video(project_dir):
    source_dir = project_dir / "source"
    if not source_dir.exists():
        return ""
    videos = sorted(source_dir.glob("*.mp4"))
    return str(videos[0].relative_to(project_dir)) if videos else ""


def find_default_source_srt(project_dir):
    path = project_dir / "subtitle.srt"
    if path.exists():
        return str(path.relative_to(project_dir))
    return ""


def discover_clip_files(project_dir):
    files = []
    for path in sorted(project_dir.glob("clips*.txt")):
        if path.name.startswith("sample_"):
            continue
        files.append(path)
    return files


def discover_review_files(project_dir):
    files = []
    for path in sorted(project_dir.rglob("clip_subtitles_review.txt")):
        rel_parts = path.relative_to(project_dir).parts
        if any(part.startswith("output") for part in rel_parts):
            continue
        files.append(path)
    return files


def normalize_search_text(value):
    text = str(value or "").lower()
    return re.sub(r"[\s_\-./]+", " ", text)


def extract_search_tokens(value):
    tokens = []
    for token in SEARCH_TOKEN_RE.findall(normalize_search_text(value)):
        if token in COMMON_BRIEF_STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def extract_hashtags(value):
    seen = set()
    tags = []
    for match in HASHTAG_RE.findall(str(value or "")):
        tag = match.strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    return tags


def first_number_in_stem(stem):
    match = re.match(r"^(\d+)", str(stem or ""))
    return match.group(1) if match else ""


def extract_title_from_brief(brief):
    if not brief:
        return ""

    patterns = [
        r"(?:온스크린\s*제목|화면\s*제목|쇼츠\s*제목|제목|title)\s*(?:은|는|:)?\s*[\"'“”‘’]?(.+?)[\"'“”‘’]?(?:[,/\n]|$)",
        r"[\"“](.+?)[\"”]",
    ]
    for pattern in patterns:
        match = re.search(pattern, brief, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def infer_preset_from_brief(brief):
    text = normalize_search_text(brief)
    if not text:
        return "clean_fullbleed"

    for preset_name in FORMAT_PRESETS:
        if preset_name.lower() in text:
            return preset_name

    top_bottom_keywords = ("위아래", "상하", "위 아래", "top bottom", "top and bottom")
    left_right_keywords = ("좌우", "양옆", "왼쪽 오른쪽", "left right", "side by side")
    split_keywords = ("분할", "split", "2분할", "두 화면")
    sequential_keywords = ("번갈아", "순차", "하나씩", "멈춰", "freeze", "멈춰있", "차례대로")
    stitch_keywords = ("이어붙", "이어 붙", "stitch", "setup", "punchline", "앞뒤", "연결")
    quote_keywords = ("명대사", "한 줄", "한줄", "quote", "카드형")
    logo_keywords = ("로고", "브랜드", "brand", "logo")
    title_keywords = ("헤드라인", "headline", "상단 제목", "제목 바", "타이틀 바")

    has_top_bottom = any(keyword in text for keyword in top_bottom_keywords)
    has_left_right = any(keyword in text for keyword in left_right_keywords)
    has_split = has_top_bottom or has_left_right or any(keyword in text for keyword in split_keywords)
    has_sequential = any(keyword in text for keyword in sequential_keywords)

    if any(keyword in text for keyword in stitch_keywords):
        return "stitch_then_punchline"
    if has_sequential and (has_top_bottom or has_split):
        return "alternating_spotlight"
    if has_left_right and has_split:
        return "reaction_duet"
    if has_top_bottom and has_split:
        return "comparison_split"
    if any(keyword in text for keyword in quote_keywords):
        return "quote_focus"
    if any(keyword in text for keyword in logo_keywords):
        return "branded_header_logo"
    if any(keyword in text for keyword in title_keywords):
        return "headline_fullbleed"
    return "clean_fullbleed"


def infer_targets_from_brief(brief, default_codes=None):
    default_codes = default_codes or DEFAULT_TARGET_CODES
    if not brief:
        return parse_target_codes(default_codes)

    text = normalize_search_text(brief)
    codes = []
    seen = set()

    for code in sorted(TARGET_PROFILES):
        if re.search(rf"(?<![a-z0-9]){code.lower()}(?![a-z0-9])", text):
            codes.append(code)
            seen.add(code)

    for code, aliases in TARGET_ALIASES:
        if code in seen:
            continue
        if any(alias in text for alias in aliases):
            codes.append(code)
            seen.add(code)

    if not codes:
        codes = list(default_codes)

    exclusive_patterns = (
        "only",
        "제외",
        "빼고",
        "빼줘",
        "without",
    )
    if any(pattern in text for pattern in exclusive_patterns):
        return parse_target_codes(codes)

    return parse_target_codes([*default_codes, *codes])


def infer_include_nosub_from_brief(brief, default=True):
    text = normalize_search_text(brief)
    if not text:
        return default

    negative_patterns = (
        "자막 없음 빼",
        "자막 없음 제외",
        "nosub 제외",
        "no sub 제외",
        "자막 없는 버전은 필요 없",
    )
    positive_patterns = (
        "자막 없음",
        "nosub",
        "no sub",
        "무자막",
    )
    if any(pattern in text for pattern in negative_patterns):
        return False
    if any(pattern in text for pattern in positive_patterns):
        return True
    return default


def parse_review_file(path):
    snippets = {}
    current_name = None
    texts = []

    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")
            section_match = REVIEW_SECTION_RE.match(line)
            if section_match:
                if current_name and texts:
                    snippets[current_name] = " / ".join(texts[:2])
                current_name = section_match.group(1).strip()
                texts = []
                continue

            if not current_name:
                continue

            text_match = REVIEW_TEXT_RE.match(line)
            if text_match:
                texts.append(text_match.group(1).strip())

    if current_name and texts:
        snippets[current_name] = " / ".join(texts[:2])

    return snippets


def load_review_snippets(project_dir):
    snippets = {}
    for path in discover_review_files(project_dir):
        snippets.update(parse_review_file(path))
    return snippets


def load_clip_candidates(project_dir, preferred_file=None, exclude_output_name=None):
    review_snippets = load_review_snippets(project_dir)
    clip_files = discover_clip_files(project_dir)
    if preferred_file and preferred_file in clip_files:
        clip_files = [preferred_file] + [path for path in clip_files if path != preferred_file]

    candidates = []
    for clip_file in clip_files:
        candidates.extend(parse_clip_file(clip_file, review_snippets))

    if exclude_output_name:
        candidates = [clip for clip in candidates if clip["output_name"] != exclude_output_name]
    return candidates


def score_clip_candidate(candidate, brief):
    if not brief:
        return 0

    haystack = normalize_search_text(
        " ".join([
            candidate["output_name"],
            candidate["stem"],
            humanize_clip_name(candidate["output_name"]),
            candidate["review"],
        ])
    )
    tokens = extract_search_tokens(brief)
    score = 0

    stem_number = first_number_in_stem(candidate["stem"])
    if stem_number and re.search(rf"{stem_number}\s*번", brief):
        score += 20

    for token in tokens:
        if token in haystack:
            score += 1

    return score


def rank_clip_candidates(candidates, brief):
    ranked = []
    for candidate in candidates:
        ranked_candidate = dict(candidate)
        ranked_candidate["_brief_score"] = score_clip_candidate(candidate, brief)
        ranked.append(ranked_candidate)
    return sorted(
        ranked,
        key=lambda clip: (-clip.get("_brief_score", 0), clip["source_file"].name, clip["start"], clip["output_name"]),
    )


def infer_brief_defaults(project_dir, brief):
    defaults = {
        "brief": brief.strip(),
        "preset": infer_preset_from_brief(brief),
        "targets": infer_targets_from_brief(brief, DEFAULT_TARGET_CODES),
        "include_nosub": infer_include_nosub_from_brief(brief, True),
        "publish_title": extract_title_from_brief(brief),
        "description": brief.strip(),
        "tags": extract_hashtags(brief),
    }

    candidates = rank_clip_candidates(load_clip_candidates(project_dir), brief)
    if candidates:
        defaults["primary_candidate"] = candidates[0]

    layout_mode = FORMAT_PRESETS[defaults["preset"]].get("layout_mode", "single")
    if layout_mode in {"split", "stitch"} and candidates:
        primary_name = candidates[0]["output_name"]
        for candidate in candidates[1:]:
            if candidate["output_name"] != primary_name:
                defaults["secondary_candidate"] = candidate
                break

    return defaults


def print_brief_summary(defaults):
    brief = defaults.get("brief")
    if not brief:
        return

    print_section("brief 해석")
    print(f"  brief: {brief}")
    print(f"  추천 preset: {defaults['preset']}")
    print(f"  추천 targets: {', '.join(defaults['targets'])}")
    print(f"  no-sub 출력: {'포함' if defaults['include_nosub'] else '미포함'}")
    if defaults.get("primary_candidate"):
        print(f"  추천 메인 clip: {format_clip_candidate(defaults['primary_candidate'])}")
    if defaults.get("secondary_candidate"):
        print(f"  추천 보조 clip: {format_clip_candidate(defaults['secondary_candidate'])}")


def get_spec_format_options(spec):
    format_spec = dict(spec.get("format") or {})
    preset_name = format_spec.get("preset", DEFAULT_PRESET_NAME)
    base = dict(FORMAT_PRESETS.get(preset_name, FORMAT_PRESETS[DEFAULT_PRESET_NAME]))
    base.update(format_spec)
    return base


def estimate_render_duration_sec(spec):
    clip = spec.get("clip") or {}
    primary_duration = ts_to_sec(clip.get("duration", "00:00:00"))
    format_options = get_spec_format_options(spec)
    layout_mode = format_options.get("layout_mode", "single")
    split_play_mode = format_options.get("split_play_mode", "parallel")
    secondary_duration = ts_to_sec(format_options.get("secondary_t") or clip.get("duration", "00:00:00"))

    if layout_mode == "stitch":
        return primary_duration + secondary_duration
    if layout_mode == "split" and split_play_mode == "sequential_freeze":
        return primary_duration + secondary_duration
    return primary_duration


def build_review_summary(spec):
    review = dict(spec.get("review") or {})
    estimated_duration_sec = estimate_render_duration_sec(spec)
    warnings = []

    if review.get("auto_selected"):
        warnings.append("자동 추천 초안입니다. 메인/보조 clip, preset, target을 확인하세요.")

    if review.get("primary_clip_score") is not None and review.get("primary_clip_score", 0) <= 0:
        warnings.append("메인 clip 추천 확신이 낮습니다.")

    if review.get("secondary_clip_score") is not None and review.get("secondary_clip_score", 0) <= 0:
        warnings.append("보조 clip 추천 확신이 낮습니다.")

    if estimated_duration_sec > RECOMMENDED_SHORT_DURATION_SEC:
        warnings.append(
            f"예상 길이 {format_duration_label(estimated_duration_sec)}로 권장 길이 {format_duration_label(RECOMMENDED_SHORT_DURATION_SEC)}를 넘습니다."
        )

    return {
        **review,
        "requires_confirmation": True,
        "estimated_duration_sec": round(estimated_duration_sec, 3),
        "estimated_duration_label": format_duration_label(estimated_duration_sec),
        "warnings": warnings,
    }


def refresh_review_summary(spec):
    spec["review"] = build_review_summary(spec)
    return spec


def print_spec_summary(spec, spec_path=None, heading="short 요약"):
    review = build_review_summary(spec)
    format_spec = spec["format"]
    preset = format_spec.get("preset", "clean_fullbleed")
    target_labels = [TARGET_PROFILES[code]["label"] for code in spec["targets"]]

    print_section(heading)
    if spec_path:
        print(f"spec: {spec_path}")
    print(f"short_id: {spec['short_id']}")
    if spec.get("brief"):
        print(f"brief: {spec['brief']}")
    print(f"source_video: {spec['source_video']}")
    print(f"source_srt: {spec['source_srt']}")
    print(f"preset: {preset} ({PRESET_DESCRIPTIONS.get(preset, '-')})")
    print(f"targets: {', '.join(target_labels)}")
    print(f"include_nosub: {spec['include_nosub']}")
    print(f"estimated_duration: {review['estimated_duration_label']}")
    if spec.get("publish"):
        publish = spec["publish"]
        print(f"publish.title: {publish.get('title', '')}")
        if publish.get("description"):
            print(f"publish.description: {publish['description']}")
        if publish.get("tags"):
            print(f"publish.tags: {', '.join(publish['tags'])}")
    clip = spec["clip"]
    print(f"clip: {clip['start']} +{clip['duration']} crop={clip.get('crop', '') or '(중앙)'}")
    if format_spec.get("secondary_ss"):
        secondary_crop = format_spec.get("secondary_crop", "") or "(중앙)"
        print(f"secondary: {format_spec['secondary_ss']} +{format_spec['secondary_t']} crop={secondary_crop}")
    if format_spec.get("title"):
        print(f"on-screen title: {format_spec['title']}")
    if review["warnings"]:
        print("warnings:")
        for warning in review["warnings"]:
            print(f"  - {warning}")


def confirm_build(spec, args):
    print_spec_summary(spec, spec_path=args.spec, heading="빌드 전 확인")

    if args.yes:
        return

    if not sys.stdin.isatty():
        raise SystemExit("build-short는 확인 단계가 필요합니다. 먼저 describe-short로 확인한 뒤 --yes로 실행하세요.")

    if not prompt_yes_no("위 설정으로 빌드할까요?", default=False):
        raise SystemExit("사용자 확인 후 빌드를 취소했습니다.")


def parse_clip_file(path, review_snippets):
    clips = []
    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 3:
                continue
            output_name = parts[2]
            stem = Path(output_name).stem
            clips.append({
                "start": parts[0],
                "duration": parts[1],
                "output_name": output_name,
                "stem": stem,
                "crop": parts[3] if len(parts) >= 4 else "",
                "review": review_snippets.get(stem, ""),
                "source_file": path,
            })
    return clips


def format_clip_candidate(candidate):
    crop = candidate["crop"] or "(중앙)"
    text = (
        f"{candidate['output_name']}  "
        f"{candidate['start']} +{candidate['duration']}  "
        f"crop={crop}"
    )
    if candidate["review"]:
        text += f"  |  {candidate['review']}"
    if candidate.get("_brief_score", 0) > 0:
        text += f"  |  score={candidate['_brief_score']}"
    return text


def format_clip_file_option(path):
    return path.name


def format_target_option(code):
    profile = TARGET_PROFILES[code]
    note = "원본 ko 자막 사용" if profile.get("use_original_subtitle") else profile["language"]
    return f"{code}  {profile['label']}  ({note})"


def format_preset_option(name):
    layout = FORMAT_PRESETS[name].get("layout_mode", "single")
    desc = PRESET_DESCRIPTIONS.get(name, layout)
    return f"{name}  [{layout}]  {desc}"


def prompt_menu(header, options, formatter, default_index=1, manual_label=None):
    if not options:
        return None

    print_section(header)
    for idx, option in enumerate(options, start=1):
        print(f"  {idx}. {formatter(option)}")
    if manual_label:
        print(f"  0. {manual_label}")

    default_text = str(default_index) if default_index is not None else None
    while True:
        value = prompt(f"{header} 번호", default_text, required=manual_label is None and default_index is None)
        if manual_label and value == "0":
            return None
        if value.isdigit():
            idx = int(value)
            if 1 <= idx <= len(options):
                return options[idx - 1]
        print("번호를 다시 입력해주세요.")


def prompt_preset(default_name="clean_fullbleed"):
    names = sorted(FORMAT_PRESETS)
    default_index = names.index(default_name) + 1 if default_name in names else 1
    selected = prompt_menu("preset 선택", names, format_preset_option, default_index=default_index)
    return selected


def parse_target_selection(value, option_codes):
    raw_values = parse_csv_list(value)
    resolved = []
    for raw in raw_values:
        if raw.isdigit():
            idx = int(raw)
            if not (1 <= idx <= len(option_codes)):
                raise ValueError(f"target 번호 범위를 벗어났습니다: {raw}")
            resolved.append(option_codes[idx - 1])
        else:
            resolved.append(raw.upper())
    return parse_target_codes(resolved)


def prompt_targets(default_codes):
    option_codes = sorted(TARGET_PROFILES)
    print_section("target 국가/로캘 선택")
    for idx, code in enumerate(option_codes, start=1):
        print(f"  {idx}. {format_target_option(code)}")

    default_text = ",".join(default_codes)
    while True:
        value = prompt("target countries (번호 또는 코드, 쉼표 구분)", default_text, required=True)
        try:
            return parse_target_selection(value, option_codes)
        except ValueError as exc:
            print(exc)


def choose_clip_candidate(project_dir, label, preferred_file=None, exclude_output_name=None, brief=None):
    clip_files = discover_clip_files(project_dir)
    if not clip_files:
        return None

    if preferred_file and preferred_file in clip_files:
        clip_file = preferred_file
    elif len(clip_files) == 1:
        clip_file = clip_files[0]
        print(f"\n{label}: clip 파일 `{clip_file.name}` 사용")
    else:
        clip_file = prompt_menu(
            f"{label}용 clip 파일 선택",
            clip_files,
            format_clip_file_option,
            default_index=1,
            manual_label="직접 시간 입력",
        )
        if clip_file is None:
            return None

    review_snippets = load_review_snippets(project_dir)
    candidates = parse_clip_file(clip_file, review_snippets)
    if exclude_output_name:
        candidates = [clip for clip in candidates if clip["output_name"] != exclude_output_name]
    if not candidates:
        return None

    candidates = rank_clip_candidates(candidates, brief)
    if brief and candidates and candidates[0].get("_brief_score", 0) > 0:
        print(f"\n{label}: brief 기준 추천 순서로 정렬했습니다.")

    return prompt_menu(
        f"{label} clip 선택",
        candidates,
        format_clip_candidate,
        default_index=1,
        manual_label="직접 시간 입력",
    )


def build_publish_metadata(default_title, brief_defaults=None):
    brief_defaults = brief_defaults or {}
    print_section("업로드 메타데이터")
    title = prompt("upload title", default_title, required=True)
    description = prompt("description", brief_defaults.get("description", ""))
    default_tags = ",".join(brief_defaults.get("tags", []))
    tags = parse_csv_list(prompt("tags (comma separated)", default_tags))
    notes = prompt("notes", "")
    data = {"title": title}
    if description:
        data["description"] = description
    if tags:
        data["tags"] = tags
    if notes:
        data["notes"] = notes
    return data


def build_primary_clip(project_dir, brief_defaults=None):
    brief_defaults = brief_defaults or {}
    primary_candidate = choose_clip_candidate(
        project_dir,
        "메인",
        preferred_file=brief_defaults.get("primary_candidate", {}).get("source_file"),
        brief=brief_defaults.get("brief", ""),
    )
    if primary_candidate:
        print(f"\n선택된 메인 clip: {format_clip_candidate(primary_candidate)}")

    start_default = primary_candidate["start"] if primary_candidate else ""
    duration_default = primary_candidate["duration"] if primary_candidate else ""
    crop_default = primary_candidate["crop"] if primary_candidate and primary_candidate["crop"] else "0~10"

    print_section("메인 clip 설정")
    start = prompt("clip start (HH:MM:SS)", start_default, required=True)
    duration = prompt("clip duration (HH:MM:SS)", duration_default, required=True)
    crop = prompt("crop spec", crop_default)

    return primary_candidate, {
        "start": start,
        "duration": duration,
        "crop": crop,
    }


def build_format_spec(project_dir, primary_candidate, primary_clip, publish_title, brief_defaults=None):
    brief_defaults = brief_defaults or {}
    print_section("포맷 선택")
    default_preset = brief_defaults.get("preset", "clean_fullbleed")
    preset = prompt_preset(default_preset)
    format_spec = {"preset": preset}

    on_screen_title_default = brief_defaults.get("publish_title") or publish_title
    on_screen_title = prompt("on-screen title", on_screen_title_default)
    if on_screen_title:
        format_spec["title"] = on_screen_title

    preset_config = FORMAT_PRESETS[preset]
    layout_mode = preset_config.get("layout_mode", "single")
    if layout_mode not in {"split", "stitch"}:
        return format_spec

    preferred_file = primary_candidate["source_file"] if primary_candidate else None
    secondary_candidate = choose_clip_candidate(
        project_dir,
        "보조",
        preferred_file=preferred_file,
        exclude_output_name=primary_candidate["output_name"] if primary_candidate else None,
        brief=brief_defaults.get("brief", ""),
    )
    if secondary_candidate:
        print(f"\n선택된 보조 clip: {format_clip_candidate(secondary_candidate)}")

    print_section("보조 clip 설정")
    secondary_input = prompt("secondary input path (blank = same source)", "")
    secondary_ss_default = secondary_candidate["start"] if secondary_candidate else ""
    secondary_t_default = secondary_candidate["duration"] if secondary_candidate else primary_clip["duration"]
    secondary_crop_default = secondary_candidate["crop"] if secondary_candidate and secondary_candidate["crop"] else ""

    secondary_ss = prompt("secondary start (HH:MM:SS)", secondary_ss_default, required=True)
    secondary_t = prompt("secondary duration (HH:MM:SS)", secondary_t_default, required=True)
    secondary_crop = prompt("secondary crop spec", secondary_crop_default)

    if secondary_input:
        format_spec["secondary_input"] = secondary_input
    format_spec["secondary_ss"] = secondary_ss
    format_spec["secondary_t"] = secondary_t
    if secondary_crop:
        format_spec["secondary_crop"] = secondary_crop

    if layout_mode == "split":
        default_primary_label = preset_config.get("primary_label", "")
        default_secondary_label = preset_config.get("secondary_label", "")
        primary_label = prompt("primary label", default_primary_label)
        secondary_label = prompt("secondary label", default_secondary_label)
        if primary_label:
            format_spec["primary_label"] = primary_label
        if secondary_label:
            format_spec["secondary_label"] = secondary_label

    return format_spec


def build_spec_dict(project_dir):
    print_section("프로젝트 자산")
    source_video_default = find_default_source_video(project_dir)
    source_srt_default = find_default_source_srt(project_dir)
    clip_files = discover_clip_files(project_dir)

    print(f"source video 기본값: {source_video_default or '(없음)'}")
    print(f"source srt 기본값: {source_srt_default or '(없음)'}")
    print(f"clips 파일: {', '.join(path.name for path in clip_files) if clip_files else '(없음)'}")

    print_section("크리에이티브 brief")
    brief = prompt("brief (자연어 요청, blank 허용)", "")
    brief_defaults = infer_brief_defaults(project_dir, brief) if brief else {}
    print_brief_summary(brief_defaults)

    source_video = prompt("source video path", source_video_default, required=True)
    source_srt = prompt("source srt path", source_srt_default, required=True)

    primary_candidate, primary_clip = build_primary_clip(project_dir, brief_defaults=brief_defaults)
    default_title = (
        brief_defaults.get("publish_title")
        or (humanize_clip_name(primary_candidate["output_name"]) if primary_candidate else "my short")
    )
    publish = build_publish_metadata(default_title, brief_defaults=brief_defaults)

    short_id_default = slugify_short_id(primary_candidate["stem"] if primary_candidate else publish["title"])
    short_id = prompt("short id", short_id_default, required=True)

    format_spec = build_format_spec(
        project_dir,
        primary_candidate,
        primary_clip,
        publish["title"],
        brief_defaults=brief_defaults,
    )
    targets = prompt_targets(brief_defaults.get("targets", DEFAULT_TARGET_CODES))
    include_nosub = prompt_yes_no("include no-sub output", brief_defaults.get("include_nosub", True))
    output_dir = prompt("output dir", f"./rendered_shorts/{short_id}", required=True)

    spec = {
        "version": 1,
        "short_id": short_id,
        "source_video": source_video,
        "source_srt": source_srt,
        "output_dir": output_dir,
        "targets": targets,
        "include_nosub": include_nosub,
        "publish": publish,
        "clip": {
            "start": primary_clip["start"],
            "duration": primary_clip["duration"],
            "crop": primary_clip["crop"],
            "output_name": f"{short_id}.mp4",
        },
        "format": format_spec,
        "review": {
            "auto_selected": False,
        },
    }
    if brief:
        spec["brief"] = brief
    return refresh_review_summary(spec)


def build_draft_spec(project_dir, brief):
    if not brief.strip():
        raise SystemExit("draft-short에는 --brief가 필요합니다.")

    source_video = find_default_source_video(project_dir)
    source_srt = find_default_source_srt(project_dir)
    if not source_video or not source_srt:
        raise SystemExit("draft-short를 쓰려면 프로젝트에 source video와 subtitle.srt 기본값이 있어야 합니다.")

    brief_defaults = infer_brief_defaults(project_dir, brief)
    print_brief_summary(brief_defaults)

    primary_candidate = brief_defaults.get("primary_candidate")
    if not primary_candidate:
        raise SystemExit("brief로 추천할 clip 후보를 찾지 못했습니다. clips.txt를 먼저 준비해주세요.")

    publish_title = brief_defaults.get("publish_title") or humanize_clip_name(primary_candidate["output_name"])
    short_id = slugify_short_id(primary_candidate["stem"] or publish_title)
    format_spec = {
        "preset": brief_defaults["preset"],
        "title": brief_defaults.get("publish_title") or publish_title,
    }

    secondary_candidate = brief_defaults.get("secondary_candidate")
    layout_mode = FORMAT_PRESETS[brief_defaults["preset"]].get("layout_mode", "single")
    if layout_mode in {"split", "stitch"}:
        if not secondary_candidate:
            raise SystemExit("split/stitch preset에 필요한 보조 clip 후보를 찾지 못했습니다.")
        format_spec["secondary_ss"] = secondary_candidate["start"]
        format_spec["secondary_t"] = secondary_candidate["duration"]
        if secondary_candidate.get("crop"):
            format_spec["secondary_crop"] = secondary_candidate["crop"]
        if layout_mode == "split":
            preset_config = FORMAT_PRESETS[brief_defaults["preset"]]
            if preset_config.get("primary_label"):
                format_spec["primary_label"] = preset_config["primary_label"]
            if preset_config.get("secondary_label"):
                format_spec["secondary_label"] = preset_config["secondary_label"]

    spec = {
        "version": 1,
        "short_id": short_id,
        "brief": brief,
        "source_video": source_video,
        "source_srt": source_srt,
        "output_dir": f"./rendered_shorts/{short_id}",
        "targets": brief_defaults["targets"],
        "include_nosub": brief_defaults["include_nosub"],
        "publish": {
            "title": publish_title,
            "description": brief_defaults.get("description", ""),
            "tags": brief_defaults.get("tags", []),
            "notes": "brief 기반 자동 초안",
        },
        "clip": {
            "start": primary_candidate["start"],
            "duration": primary_candidate["duration"],
            "crop": primary_candidate.get("crop") or "0~10",
            "output_name": f"{short_id}.mp4",
        },
        "format": format_spec,
        "review": {
            "auto_selected": True,
            "primary_clip_score": primary_candidate.get("_brief_score", 0),
            "secondary_clip_score": secondary_candidate.get("_brief_score", 0) if secondary_candidate else None,
        },
    }
    if not spec["publish"]["description"]:
        spec["publish"].pop("description", None)
    if not spec["publish"]["tags"]:
        spec["publish"].pop("tags", None)
    return refresh_review_summary(spec)


def load_spec(spec_path):
    spec_path = Path(spec_path).resolve()
    with open(spec_path, "r", encoding="utf-8") as f:
        spec = json.load(f)

    if spec.get("version") != 1:
        raise SystemExit("현재는 version 1 short spec만 지원합니다.")

    for key in ("short_id", "source_video", "source_srt", "clip", "format"):
        if key not in spec:
            raise SystemExit(f"spec에 '{key}' 필드가 필요합니다.")

    spec["targets"] = parse_target_codes(spec.get("targets", ["KR"]))
    spec["include_nosub"] = bool(spec.get("include_nosub", True))
    publish = dict(spec.get("publish") or {})
    if publish.get("tags") and not isinstance(publish["tags"], list):
        publish["tags"] = parse_csv_list(publish["tags"])
    spec["publish"] = publish
    return spec_path, refresh_review_summary(spec)


def ensure_translations(spec_path, spec, clips_path, skip_translate):
    spec_dir = spec_path.parent
    source_srt = resolve_path(spec_dir, spec["source_srt"])
    subtitle_dir = source_srt.parent

    translated_by_lang = {}
    missing_langs = []
    for lang in get_required_translation_langs(spec["targets"]):
        translated_path = subtitle_dir / f"subtitle_{lang}.srt"
        translated_by_lang[lang] = translated_path
        if not translated_path.exists():
            missing_langs.append(lang)

    if missing_langs and skip_translate:
        missing_text = ", ".join(missing_langs)
        raise SystemExit(f"번역이 필요한 자막이 없습니다: {missing_text}")

    if missing_langs:
        cmd = [
            "python3",
            str(TRANSLATE_PATH),
            "--srt",
            str(source_srt),
            "--clips",
            str(clips_path),
            "--langs",
            ",".join(missing_langs),
            "--outdir",
            str(subtitle_dir),
        ]
        print(f"\n번역 생성: {', '.join(missing_langs)}", flush=True)
        subprocess.run(cmd, check=True)

    return source_srt, translated_by_lang


def build_resolved_manifest(spec, source_video, source_srt, output_dir, output_name, subtitle_tracks, format_payload):
    return {
        "version": spec["version"],
        "short_id": spec["short_id"],
        "brief": spec.get("brief", ""),
        "source_video": str(source_video),
        "source_srt": str(source_srt),
        "output_dir": str(output_dir),
        "targets": get_target_profiles(spec["targets"]),
        "include_nosub": spec["include_nosub"],
        "publish": spec.get("publish", {}),
        "review": spec.get("review", {}),
        "clip": {**spec["clip"], "output_name": output_name},
        "format": format_payload,
        "subtitle_tracks": subtitle_tracks,
    }


def build_short(args):
    spec_path, spec = load_spec(args.spec)
    spec_dir = spec_path.parent

    confirm_build(spec, args)

    source_video = resolve_path(spec_dir, spec["source_video"])
    output_dir = resolve_path(spec_dir, spec.get("output_dir") or f"./rendered_shorts/{spec['short_id']}")
    output_dir.mkdir(parents=True, exist_ok=True)
    runtime_dir = output_dir / "_runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)

    clip = spec["clip"]
    output_name = clip.get("output_name") or f"{spec['short_id']}.mp4"
    crop = clip.get("crop", "")
    clips_path = runtime_dir / "short_clips.txt"
    clips_path.write_text(
        f"{clip['start']},{clip['duration']},{output_name},{crop}\n",
        encoding="utf-8",
    )

    source_srt, translated_by_lang = ensure_translations(spec_path, spec, clips_path, args.skip_translate)
    subtitle_tracks = build_subtitle_tracks(
        spec["targets"],
        spec["include_nosub"],
        source_srt,
        translated_by_lang,
    )
    subtitle_config_path = runtime_dir / "subtitle_tracks.json"
    subtitle_config_path.write_text(
        json.dumps({"tracks": subtitle_tracks}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    format_payload = dict(spec["format"])
    if not format_payload.get("title"):
        publish_title = spec.get("publish", {}).get("title")
        if publish_title:
            format_payload["title"] = publish_title
    format_config_path = runtime_dir / "formats.json"
    format_config_path.write_text(
        json.dumps({"clips": [{**format_payload, "name": output_name}]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    resolved_manifest_path = runtime_dir / "resolved_short.json"
    resolved_manifest_path.write_text(
        json.dumps(
            build_resolved_manifest(
                spec,
                source_video,
                source_srt,
                output_dir,
                output_name,
                subtitle_tracks,
                format_payload,
            ),
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    cmd = [
        "python3",
        str(MAKE_SHORTS_PATH),
        "--input",
        str(source_video),
        "--clips",
        str(clips_path),
        "--srtdir",
        str(source_srt.parent),
        "--format-config",
        str(format_config_path),
        "--subtitle-config",
        str(subtitle_config_path),
        "--outdir",
        str(output_dir),
        "--workers",
        str(args.workers),
    ]

    print(f"\n빌드 시작: {spec['short_id']}", flush=True)
    subprocess.run(cmd, check=True)
    print(f"\n출력 위치: {output_dir}", flush=True)


def init_short(args):
    project_dir = Path(args.project_dir or ".").resolve()
    project_dir.mkdir(parents=True, exist_ok=True)

    spec = build_spec_dict(project_dir)
    default_spec_dir = project_dir / "shorts"
    default_spec_dir.mkdir(parents=True, exist_ok=True)
    default_spec_path = default_spec_dir / f"{spec['short_id']}.json"
    spec_path = Path(args.spec).resolve() if args.spec else default_spec_path
    spec_path.parent.mkdir(parents=True, exist_ok=True)

    spec = rewrite_spec_paths_for_location(spec, project_dir, spec_path)
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nspec 생성: {spec_path}", flush=True)
    print_spec_summary(spec, spec_path=spec_path, heading="spec 확인")


def draft_short(args):
    project_dir = Path(args.project_dir or ".").resolve()
    project_dir.mkdir(parents=True, exist_ok=True)

    spec = build_draft_spec(project_dir, args.brief)
    default_spec_dir = project_dir / "shorts"
    default_spec_dir.mkdir(parents=True, exist_ok=True)
    default_spec_path = default_spec_dir / f"{spec['short_id']}.json"
    spec_path = Path(args.spec).resolve() if args.spec else default_spec_path
    spec_path.parent.mkdir(parents=True, exist_ok=True)

    spec = rewrite_spec_paths_for_location(spec, project_dir, spec_path)
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nspec 초안 생성: {spec_path}", flush=True)
    print_spec_summary(spec, spec_path=spec_path, heading="draft 확인")


def list_targets(_args):
    for idx, code in enumerate(sorted(TARGET_PROFILES), start=1):
        print(f"{idx:>2}. {format_target_option(code)}")


def list_presets(_args):
    for idx, name in enumerate(sorted(FORMAT_PRESETS), start=1):
        print(f"{idx:>2}. {format_preset_option(name)}")


def list_clips(args):
    project_dir = Path(args.project_dir or ".").resolve()
    candidates = load_clip_candidates(project_dir)
    if not candidates:
        raise SystemExit("clip 후보를 찾지 못했습니다.")

    candidates = rank_clip_candidates(candidates, args.brief or "")
    limit = args.limit or len(candidates)

    print_section("clip 후보")
    if args.brief:
        print(f"brief: {args.brief}")
    for idx, candidate in enumerate(candidates[:limit], start=1):
        print(f"{idx:>2}. [{candidate['source_file'].name}] {format_clip_candidate(candidate)}")


def describe_short(args):
    spec_path, spec = load_spec(args.spec)
    print_spec_summary(spec, spec_path=spec_path, heading="short 요약")


def main():
    parser = argparse.ArgumentParser(description="gshorts single-short CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-short", help="interactive short spec 생성")
    init_parser.add_argument("--project-dir", help="프로젝트 디렉토리")
    init_parser.add_argument("--spec", help="생성할 spec 파일 경로")
    init_parser.set_defaults(func=init_short)

    draft_parser = subparsers.add_parser("draft-short", help="brief 기반 short spec 초안 생성")
    draft_parser.add_argument("--project-dir", help="프로젝트 디렉토리")
    draft_parser.add_argument("--brief", required=True, help="자연어 편집 brief")
    draft_parser.add_argument("--spec", help="생성할 spec 파일 경로")
    draft_parser.set_defaults(func=draft_short)

    build_parser = subparsers.add_parser("build-short", help="short spec 하나를 빌드")
    build_parser.add_argument("--spec", required=True, help="short spec JSON 경로")
    build_parser.add_argument("--skip-translate", action="store_true", help="필요한 번역이 없으면 실패")
    build_parser.add_argument("--yes", action="store_true", help="요약을 이미 확인한 경우 확인 프롬프트 없이 진행")
    build_parser.add_argument("--workers", type=int, default=1, help="렌더 워커 수")
    build_parser.set_defaults(func=build_short)

    targets_parser = subparsers.add_parser("list-targets", help="지원 국가/로캘 target 보기")
    targets_parser.set_defaults(func=list_targets)

    presets_parser = subparsers.add_parser("list-presets", help="지원 format preset 보기")
    presets_parser.set_defaults(func=list_presets)

    clips_parser = subparsers.add_parser("list-clips", help="프로젝트 clip 후보 보기")
    clips_parser.add_argument("--project-dir", help="프로젝트 디렉토리")
    clips_parser.add_argument("--brief", help="자연어 brief를 주면 관련도 순으로 정렬")
    clips_parser.add_argument("--limit", type=int, default=10, help="표시할 최대 후보 수")
    clips_parser.set_defaults(func=list_clips)

    describe_parser = subparsers.add_parser("describe-short", help="short spec 요약 보기")
    describe_parser.add_argument("--spec", required=True, help="short spec JSON 경로")
    describe_parser.set_defaults(func=describe_short)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
