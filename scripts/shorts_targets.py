#!/usr/bin/env python3
"""Country/locale target profiles for single-short builds."""

TARGET_PROFILES = {
    "KR": {
        "code": "KR",
        "suffix": "kr",
        "language": "ko",
        "label": "한국어 (KR)",
        "country_name": "South Korea",
        "use_original_subtitle": True,
    },
    "US": {
        "code": "US",
        "suffix": "us",
        "language": "en",
        "label": "English (US)",
        "country_name": "United States",
    },
    "GB": {
        "code": "GB",
        "suffix": "gb",
        "language": "en",
        "label": "English (UK)",
        "country_name": "United Kingdom",
    },
    "ES": {
        "code": "ES",
        "suffix": "es",
        "language": "es",
        "label": "Español (ES)",
        "country_name": "Spain",
    },
    "MX": {
        "code": "MX",
        "suffix": "mx",
        "language": "es",
        "label": "Español (MX)",
        "country_name": "Mexico",
    },
    "JP": {
        "code": "JP",
        "suffix": "jp",
        "language": "ja",
        "label": "日本語 (JP)",
        "country_name": "Japan",
    },
    "BR": {
        "code": "BR",
        "suffix": "br",
        "language": "pt",
        "label": "Português (BR)",
        "country_name": "Brazil",
    },
    "FR": {
        "code": "FR",
        "suffix": "fr",
        "language": "fr",
        "label": "Français (FR)",
        "country_name": "France",
    },
    "DE": {
        "code": "DE",
        "suffix": "de",
        "language": "de",
        "label": "Deutsch (DE)",
        "country_name": "Germany",
    },
    "CN": {
        "code": "CN",
        "suffix": "cn",
        "language": "zh-CN",
        "label": "中文 (简体)",
        "country_name": "China",
    },
}


def parse_target_codes(values):
    if values is None:
        return []

    if isinstance(values, str):
        raw_values = [part.strip() for part in values.split(",")]
    else:
        raw_values = [str(value).strip() for value in values]

    seen = set()
    codes = []
    for raw in raw_values:
        if not raw:
            continue
        code = raw.upper()
        if code not in TARGET_PROFILES:
            supported = ", ".join(sorted(TARGET_PROFILES))
            raise ValueError(f"지원하지 않는 target code: {code} (지원: {supported})")
        if code in seen:
            continue
        seen.add(code)
        codes.append(code)
    return codes


def get_target_profiles(codes):
    return [TARGET_PROFILES[code] for code in parse_target_codes(codes)]


def get_required_translation_langs(codes):
    langs = []
    seen = set()
    for profile in get_target_profiles(codes):
        if profile.get("use_original_subtitle"):
            continue
        lang = profile["language"]
        if lang in seen:
            continue
        seen.add(lang)
        langs.append(lang)
    return langs


def build_subtitle_tracks(codes, include_nosub, original_srt_path, translated_path_by_lang):
    tracks = []
    if include_nosub:
        tracks.append({"suffix": "nosub", "label": "자막 없음"})

    for profile in get_target_profiles(codes):
        if profile.get("use_original_subtitle"):
            srt_path = original_srt_path
        else:
            srt_path = translated_path_by_lang[profile["language"]]
        tracks.append({
            "suffix": profile["suffix"],
            "label": profile["label"],
            "srt": str(srt_path),
        })

    return tracks
