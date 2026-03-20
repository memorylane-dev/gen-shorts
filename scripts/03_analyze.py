#!/usr/bin/env python3
"""
Step 2b: 쇼츠 구간 선정 도우미
- 자막 기반 키워드 검색
- 오디오 피크 감지 (리액션/웃음/박수 등 소리가 큰 구간)
- 선정 기준에 따라 후보 구간 목록 출력

사용법:
  python3 02b_analyze.py --audio 영상_audio.m4a --transcript 자막.txt [--mode 모드]

모드:
  audio_peaks  : 오디오가 갑자기 커지는 구간 (리액션, 웃음, 박수)
  keyword      : 특정 단어가 포함된 구간 검색
  funny        : 웃음/감탄 관련 키워드 자동 검색
  all          : 전체 분석 (기본값)
"""

import argparse
import subprocess
import re
import os
import json


def parse_transcript(path):
    """[MM:SS] 텍스트 형식의 자막 파싱"""
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r"\[(\d{2}):(\d{2})\]\s*(.*)", line.strip())
            if m:
                mm, ss, text = int(m.group(1)), int(m.group(2)), m.group(3)
                sec = mm * 60 + ss
                entries.append({"time_sec": sec, "time_str": f"{mm:02d}:{ss:02d}", "text": text})
    return entries


def analyze_audio_peaks(audio_path, segment_sec=5, top_n=15):
    """
    오디오를 구간별로 나눠 RMS 볼륨을 측정하고,
    평균 대비 볼륨이 급상승하는 구간을 찾는다.
    리액션, 웃음, 박수 등 에너지가 높은 구간을 감지.
    """
    print("  오디오 볼륨 분석 중 (구간별 RMS)...")

    # 구간별 볼륨 측정 (astats 필터)
    cmd = [
        "ffmpeg", "-i", audio_path,
        "-af", f"asegment=timestamps=0,astats=metadata=1:reset={segment_sec},"
               f"ametadata=mode=print:key=lavfi.astats.Overall.RMS_level",
        "-f", "null", "-"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    # RMS 레벨 파싱
    segments = []
    current_time = None
    for line in result.stderr.split("\n"):
        # pts_time
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            current_time = float(m.group(1))
        # RMS level
        m = re.search(r"RMS_level=(-?[\d.]+)", line)
        if m and current_time is not None:
            rms = float(m.group(1))
            if rms > -100:  # -inf 제외
                segments.append({
                    "time_sec": current_time,
                    "rms": rms,
                    "time_str": f"{int(current_time//60):02d}:{int(current_time%60):02d}",
                })
            current_time = None

    if not segments:
        # fallback: ebur128으로 시도
        return analyze_audio_peaks_fallback(audio_path, segment_sec, top_n)

    # 평균 RMS 계산
    avg_rms = sum(s["rms"] for s in segments) / len(segments)

    # 평균 대비 볼륨이 높은 구간 (spike)
    for s in segments:
        s["spike"] = s["rms"] - avg_rms

    # 스파이크 순으로 정렬
    segments.sort(key=lambda x: x["spike"], reverse=True)

    # 상위 구간 반환
    top = segments[:top_n]
    for s in top:
        s["description"] = f"볼륨 {s['rms']:.1f}dB (평균 대비 +{s['spike']:.1f}dB)"
    return top, avg_rms


def analyze_audio_peaks_fallback(audio_path, segment_sec=5, top_n=15):
    """
    astats가 안 되면 volumedetect + 구간 분할로 대체.
    """
    print("  오디오 피크 분석 중 (fallback)...")

    # 전체 길이 확인
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", audio_path
    ], capture_output=True, text=True)
    total_dur = float(probe.stdout.strip())

    segments = []
    for start in range(0, int(total_dur), segment_sec):
        cmd = [
            "ffmpeg", "-ss", str(start), "-t", str(segment_sec),
            "-i", audio_path,
            "-af", "volumedetect",
            "-f", "null", "-"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        m = re.search(r"max_volume:\s*(-?[\d.]+)\s*dB", result.stderr)
        if m:
            vol = float(m.group(1))
            segments.append({
                "time_sec": start,
                "rms": vol,
                "time_str": f"{int(start//60):02d}:{int(start%60):02d}",
            })

    if not segments:
        return [], 0

    avg_rms = sum(s["rms"] for s in segments) / len(segments)
    for s in segments:
        s["spike"] = s["rms"] - avg_rms
        s["description"] = f"최대 볼륨 {s['rms']:.1f}dB (평균 대비 +{s['spike']:.1f}dB)"

    segments.sort(key=lambda x: x["spike"], reverse=True)
    return segments[:top_n], avg_rms


def search_keywords(entries, keywords):
    """자막에서 특정 키워드가 포함된 구간 검색"""
    results = []
    for entry in entries:
        for kw in keywords:
            if kw in entry["text"]:
                results.append({
                    **entry,
                    "matched_keyword": kw
                })
                break
    return results


def search_funny_keywords(entries):
    """웃음/리액션 관련 키워드 자동 검색 (오탐 방지)"""
    funny_keywords = [
        "ㅋㅋ", "하하하", "웃겨", "웃긴", "웃기",
        "미쳤", "대박", "헐 ", "어머",
        "어이없", "황당", "장난 아", "농담",
        "아니 진짜", "말도 안", "뭐야 이게", "왜 그래",
        "죽겠", "터졌", "터지", "폭소", "깜짝", "놀라",
        "세상에", "오마이갓", "레전드",
        "미친", "실화", "찐이", "개웃", "존웃",
        "어떡해", "안 돼", "큰일",
    ]
    return search_keywords(entries, funny_keywords)


def print_section(title, items, max_items=10):
    """결과 섹션 출력"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    if not items:
        print("  (결과 없음)")
        return
    for i, item in enumerate(items[:max_items], 1):
        if "text" in item:
            print(f"  {i:2d}. [{item['time_str']}] {item['text']}")
            if "matched_keyword" in item:
                print(f"      → 매칭: \"{item['matched_keyword']}\"")
        elif "description" in item:
            print(f"  {i:2d}. [{item['time_str']}] {item['description']}")
    if len(items) > max_items:
        print(f"  ... 외 {len(items) - max_items}개")


def print_audio_results(result):
    """오디오 분석 결과 출력"""
    if isinstance(result, tuple):
        peaks, avg_rms = result
        print_section(f"오디오 피크 구간 (평균 {avg_rms:.1f}dB 대비 볼륨 급상승 순)", peaks)
    else:
        print_section("오디오 피크 구간", result)


def interactive_mode(entries, audio_path):
    """대화형 모드: 선정 기준을 묻고 결과 출력"""
    print("\n" + "="*60)
    print("  쇼츠 구간 선정 도우미")
    print("="*60)
    print("""
  어떤 기준으로 쇼츠 구간을 찾으시겠어요?

  [1] 오디오 피크    — 리액션/웃음/박수 등 소리가 큰 구간
  [2] 재밌는 자막    — 웃음/놀람 관련 키워드 자동 검색
  [3] 키워드 검색    — 특정 단어가 포함된 구간 직접 검색
  [4] 전체 분석      — 위 3가지 모두 실행
  [q] 종료
""")

    while True:
        choice = input("  선택 (1/2/3/4/q): ").strip()

        if choice == "1":
            if audio_path:
                result = analyze_audio_peaks(audio_path)
                print_audio_results(result)
            else:
                print("  ⚠ 오디오 파일이 지정되지 않았습니다. --audio 옵션을 사용하세요.")

        elif choice == "2":
            results = search_funny_keywords(entries)
            print_section("재밌는 자막 후보", results, max_items=15)

        elif choice == "3":
            kw_input = input("  검색할 키워드 (쉼표로 구분): ").strip()
            if kw_input:
                keywords = [k.strip() for k in kw_input.split(",")]
                results = search_keywords(entries, keywords)
                print_section(f"키워드 검색 결과: {', '.join(keywords)}", results, max_items=20)

        elif choice == "4":
            if audio_path:
                result = analyze_audio_peaks(audio_path)
                print_audio_results(result)
            results = search_funny_keywords(entries)
            print_section("재밌는 자막 후보", results, max_items=15)

        elif choice in ("q", "Q"):
            break
        else:
            print("  1, 2, 3, 4, q 중 선택하세요.")

        print()


def batch_mode(entries, audio_path, mode):
    """배치 모드: 지정된 분석 실행"""
    if mode in ("audio_peaks", "all") and audio_path:
        result = analyze_audio_peaks(audio_path)
        print_audio_results(result)

    if mode in ("funny", "all"):
        results = search_funny_keywords(entries)
        print_section("재밌는 자막 후보", results, max_items=15)

    if mode == "keyword":
        print("  배치 모드에서 키워드 검색은 --keywords 옵션을 사용하세요.")


def main():
    parser = argparse.ArgumentParser(description="쇼츠 구간 선정 도우미")
    parser.add_argument("--transcript", "-t", required=True, help="자막 텍스트 파일 (.txt)")
    parser.add_argument("--audio", "-a", help="오디오 파일 (오디오 피크 분석용)")
    parser.add_argument("--mode", "-m", default="interactive",
                        choices=["interactive", "audio_peaks", "funny", "keyword", "all"],
                        help="분석 모드 (기본: interactive)")
    parser.add_argument("--keywords", "-k", help="검색할 키워드 (쉼표 구분, keyword 모드용)")
    args = parser.parse_args()

    entries = parse_transcript(args.transcript)
    print(f"자막 로드: {len(entries)}줄")

    if args.mode == "interactive":
        interactive_mode(entries, args.audio)
    elif args.mode == "keyword" and args.keywords:
        keywords = [k.strip() for k in args.keywords.split(",")]
        results = search_keywords(entries, keywords)
        print_section(f"키워드 검색: {', '.join(keywords)}", results, max_items=20)
    else:
        batch_mode(entries, args.audio, args.mode)


if __name__ == "__main__":
    main()
