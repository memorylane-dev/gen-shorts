#!/usr/bin/env python3
"""
Step 4b: 클립별 자막 추출 (번역 전 검토용)
- clips.txt와 subtitle.srt를 읽어 각 클립에 해당하는 자막을 추출
- 클립별 개별 파일 + 전체 요약 파일 생성
- 번역 전에 자막 내용을 검토/수정할 수 있도록 함

사용법:
  python3 04b_extract_clip_subs.py --srt subtitle.srt --clips clips.txt [--outdir previews]
"""

import argparse
import re
import os


def ts_to_sec(ts):
    parts = ts.replace(",", ".").split(":")
    return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])


def sec_to_mmss(sec):
    m = int(sec // 60)
    s = int(sec % 60)
    return f"{m:02d}:{s:02d}"


def parse_srt(path):
    with open(path, "r", encoding="utf-8") as f:
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
        start = ts_to_sec(m.group(1))
        end = ts_to_sec(m.group(2))
        text = "\n".join(lines[2:])
        entries.append({"start": start, "end": end, "text": text})
    return entries


def parse_clips(path):
    clips = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            if len(parts) >= 3:
                ss = parts[0].strip()
                t = parts[1].strip()
                name = parts[2].strip()
                start = ts_to_sec(ss)
                duration = ts_to_sec(t)
                clips.append({
                    "name": name,
                    "start": start,
                    "end": start + duration,
                    "ss": ss,
                    "t": t,
                })
    return clips


def extract_clip_subs(entries, clip_start, clip_end, margin=1.0):
    """클립 구간에 해당하는 자막 추출 (앞뒤 margin초 여유)"""
    result = []
    for e in entries:
        if e["end"] < clip_start - margin or e["start"] > clip_end + margin:
            continue
        result.append(e)
    return result


def main():
    parser = argparse.ArgumentParser(description="클립별 자막 추출 (번역 전 검토용)")
    parser.add_argument("--srt", "-s", required=True, help="한국어 SRT 파일")
    parser.add_argument("--clips", "-c", required=True, help="클립 목록 파일")
    parser.add_argument("--outdir", "-o", default=".", help="출력 디렉토리")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    entries = parse_srt(args.srt)
    clips = parse_clips(args.clips)

    print(f"전체 자막: {len(entries)}개 세그먼트")
    print(f"클립: {len(clips)}개\n")

    # 전체 요약 파일
    summary_path = os.path.join(args.outdir, "clip_subtitles_review.txt")
    with open(summary_path, "w", encoding="utf-8") as summary_f:
        summary_f.write("=" * 60 + "\n")
        summary_f.write("클립별 자막 검토 파일\n")
        summary_f.write("번역 전에 자막 내용을 확인하고 수정하세요.\n")
        summary_f.write("=" * 60 + "\n\n")

        for clip in clips:
            subs = extract_clip_subs(entries, clip["start"], clip["end"])
            clip_base = os.path.splitext(clip["name"])[0]

            # 요약 파일에 추가
            summary_f.write(f"--- [{clip_base}] {clip['ss']} ~ +{clip['t']} ({len(subs)}개 자막) ---\n")
            for s in subs:
                rel_start = sec_to_mmss(s["start"])
                summary_f.write(f"  [{rel_start}] {s['text']}\n")
            summary_f.write("\n")

            # 클립별 개별 파일
            clip_path = os.path.join(args.outdir, f"{clip_base}_subs.txt")
            with open(clip_path, "w", encoding="utf-8") as cf:
                for s in subs:
                    rel_start = sec_to_mmss(s["start"])
                    cf.write(f"[{rel_start}] {s['text']}\n")

            print(f"  {clip['name']}: {len(subs)}개 자막 → {clip_path}")

    print(f"\n전체 요약: {summary_path}")
    print("번역 전에 자막 내용을 확인하세요.")


if __name__ == "__main__":
    main()
