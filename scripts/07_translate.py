#!/usr/bin/env python3
"""
Step 7: 자막 번역
- 한국어 SRT를 영어/스페인어로 번역
- deep-translator 라이브러리 사용 (Google Translate 무료)
- 원본 타이밍을 유지하면서 텍스트만 번역

사용법:
  python3 07_translate.py --srt subtitle.srt --langs en,es

설치:
  pip install deep-translator
"""

import argparse
import re
import os
import time


def parse_srt(path):
    """SRT 파일을 블록 단위로 파싱"""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    blocks = re.split(r"\n\n+", content.strip())
    entries = []
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        index = lines[0]
        timing = lines[1]
        text = "\n".join(lines[2:])
        entries.append({"index": index, "timing": timing, "text": text})
    return entries


def write_srt(entries, path):
    """SRT 형식으로 저장"""
    with open(path, "w", encoding="utf-8") as f:
        for i, entry in enumerate(entries):
            if i > 0:
                f.write("\n")
            f.write(f"{entry['index']}\n")
            f.write(f"{entry['timing']}\n")
            f.write(f"{entry['text']}\n")


def translate_entries(entries, target_lang, batch_size=30):
    """deep-translator로 자막 번역 (배치 처리)"""
    from deep_translator import GoogleTranslator

    translator = GoogleTranslator(source="ko", target=target_lang)
    translated = []
    total = len(entries)

    for i in range(0, total, batch_size):
        batch = entries[i:i + batch_size]
        texts = [e["text"] for e in batch]

        try:
            results = translator.translate_batch(texts)
        except Exception as e:
            print(f"    배치 {i//batch_size + 1} 번역 실패, 개별 처리: {e}")
            results = []
            for text in texts:
                try:
                    results.append(translator.translate(text))
                    time.sleep(0.1)
                except Exception:
                    results.append(text)  # 실패 시 원본 유지

        for j, entry in enumerate(batch):
            translated.append({
                "index": entry["index"],
                "timing": entry["timing"],
                "text": results[j] if j < len(results) else entry["text"],
            })

        done = min(i + batch_size, total)
        print(f"    {done}/{total} ({done*100//total}%)")

    return translated


LANG_NAMES = {
    "en": "English",
    "es": "Spanish",
    "ja": "Japanese",
    "zh-CN": "Chinese (Simplified)",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
}


def parse_time_to_sec(t):
    """HH:MM:SS,mmm 또는 HH:MM:SS 형식을 초 단위로 변환"""
    t = t.replace(",", ".").strip()
    parts = t.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(t)


def parse_clips(clips_path):
    """clips.txt에서 클립 시간 범위를 파싱"""
    clips = []
    with open(clips_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            start = parse_time_to_sec(parts[0])
            duration = parse_time_to_sec(parts[1])
            clips.append((start, start + duration))
    return clips


def filter_entries_by_clips(entries, clips):
    """클립 시간 범위에 해당하는 자막만 필터링"""
    filtered = []
    for entry in entries:
        # timing에서 시작 시간 추출: "00:16:13,000 --> 00:16:15,000"
        m = re.match(r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})", entry["timing"])
        if not m:
            continue
        entry_start = parse_time_to_sec(m.group(1))
        for clip_start, clip_end in clips:
            if clip_start <= entry_start <= clip_end:
                filtered.append(entry)
                break
    return filtered


def main():
    parser = argparse.ArgumentParser(description="SRT 자막 번역")
    parser.add_argument("--srt", "-s", required=True, help="한국어 SRT 파일")
    parser.add_argument("--langs", "-l", default="en,es", help="번역할 언어 코드 (쉼표 구분, 기본: en,es)")
    parser.add_argument("--outdir", "-o", help="출력 디렉토리 (기본: SRT 파일과 같은 위치)")
    parser.add_argument("--clips", "-c", help="clips.txt 파일 (지정 시 클립 구간만 번역)")
    args = parser.parse_args()

    outdir = args.outdir or os.path.dirname(args.srt) or "."
    os.makedirs(outdir, exist_ok=True)

    entries = parse_srt(args.srt)
    print(f"원본 자막: {len(entries)}개 세그먼트")

    if args.clips:
        clips = parse_clips(args.clips)
        entries = filter_entries_by_clips(entries, clips)
        print(f"클립 구간 자막: {len(entries)}개 세그먼트 ({len(clips)}개 클립)")

    langs = [l.strip() for l in args.langs.split(",")]

    for lang in langs:
        lang_name = LANG_NAMES.get(lang, lang)
        print(f"\n  [{lang}] {lang_name} 번역 중...")

        translated = translate_entries(entries, lang)
        out_path = os.path.join(outdir, f"subtitle_{lang}.srt")
        write_srt(translated, out_path)
        print(f"  [{lang}] 저장: {out_path}")

    print(f"\n=== 번역 완료: {len(langs)}개 언어 ===")


if __name__ == "__main__":
    main()
