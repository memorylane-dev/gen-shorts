#!/usr/bin/env python3
"""Shared subtitle font profile defaults for gshorts."""

from copy import deepcopy


FONT_PROFILES = {
    "cute_ko": {
        "subtitle_renderer": "image",
        "subtitle_font": "Jua",
    },
    "cute_multilingual": {
        "subtitle_renderer": "image",
        "subtitle_font": "Jua",
        "subtitle_font_by_suffix": {
            "jp": "Hiragino Maru Gothic ProN",
        },
    },
    "clean_sans": {
        "subtitle_renderer": "image",
        "subtitle_font": "SUIT",
        "subtitle_font_by_suffix": {
            "jp": "Hiragino Sans",
        },
    },
    "safe_multilingual": {
        "subtitle_renderer": "image",
        "subtitle_font": "Apple SD Gothic Neo",
        "subtitle_font_by_suffix": {
            "jp": "Hiragino Sans",
        },
    },
}


def get_font_profile(profile_name):
    if not profile_name:
        return None
    profile = FONT_PROFILES.get(str(profile_name).strip())
    return deepcopy(profile) if profile else None


def apply_font_profile_defaults(data, profile_name):
    profile = get_font_profile(profile_name)
    if profile is None:
        raise ValueError(f"알 수 없는 font_profile: {profile_name}")

    merged = deepcopy(data)
    for key, value in profile.items():
        if isinstance(value, dict):
            current = merged.get(key)
            if isinstance(current, dict):
                profile_map = deepcopy(value)
                profile_map.update(current)
                merged[key] = profile_map
            elif current is None:
                merged[key] = deepcopy(value)
        else:
            merged.setdefault(key, value)
    return merged
