#!/usr/bin/env python3
"""
Step 5b: 크롭 기준선 미리보기 + 자동 크롭 범위 제안
- 원본 프레임에 번호 매긴 세로 기준선을 균등 분할로 표시
- 사용자가 "2번~5번 사이로 잘라줘" 식으로 크롭 범위 지정 가능
- 9:16 비율에 딱 맞추지 않아도 됨 (위아래 검은 여백 허용)
- --suggest 옵션: 프레임 분석 후 제안 범위를 초록색으로 표시

사용법:
  python3 05b_preview_gridlines.py --input 영상.mp4 --clips clips.txt [--divisions 10] [--suggest]
"""

import subprocess
import os
import argparse
import tempfile
import struct


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


def parse_clips_file(path):
    clips = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            if len(parts) >= 3:
                clips.append((parts[0].strip(), parts[1].strip(), parts[2].strip()))
    return clips


def analyze_frame_skin(input_video, timestamp, src_w, src_h, divisions):
    """프레임을 세로 구간별로 분석하여 피부색 영역을 감지.
    RGB 기반 피부색 감지로 사람이 있는 구간을 찾음."""
    # 프레임을 rawvideo RGB로 추출 (축소해서 빠르게)
    analyze_w = 480
    analyze_h = int(src_h * analyze_w / src_w)
    analyze_interval = analyze_w / divisions

    with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        cmd = [
            "ffmpeg", "-y", "-ss", timestamp, "-i", input_video,
            "-frames:v", "1",
            "-vf", f"scale={analyze_w}:{analyze_h}",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            tmp_path
        ]
        subprocess.run(cmd, capture_output=True, text=True)

        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
            return None

        with open(tmp_path, "rb") as f:
            raw = f.read()

        expected = analyze_w * analyze_h * 3
        if len(raw) < expected:
            return None

        # 각 구간별 피부색 픽셀 비율 계산 (상단 55%만 - 얼굴/상체 영역)
        scan_h = int(analyze_h * 0.55)
        scores = []
        for i in range(divisions):
            col_start = int(i * analyze_interval)
            col_end = int((i + 1) * analyze_interval)
            skin_count = 0
            pixel_count = 0

            for y in range(scan_h):
                for x in range(col_start, min(col_end, analyze_w)):
                    idx = (y * analyze_w + x) * 3
                    if idx + 2 >= len(raw):
                        continue
                    r, g, b = raw[idx], raw[idx + 1], raw[idx + 2]
                    pixel_count += 1

                    # 피부색 감지 (RGB 기반)
                    # 커튼(순수 빨강: R>>G, G/R<0.4)과 구분하기 위해
                    # 피부색은 G/R 비율이 0.4~0.85 범위
                    if r > 0:
                        gr_ratio = g / r
                    else:
                        gr_ratio = 0
                    if (r > 90 and g > 50 and b > 20
                            and r > g and r > b
                            and 0.4 < gr_ratio < 0.85
                            and (r - g) < 80
                            and (max(r, g, b) - min(r, g, b)) > 15
                            and r < 250):
                        skin_count += 1

            ratio = skin_count / max(1, pixel_count)
            scores.append(ratio)

    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return scores


def suggest_crop_range(scores, divisions):
    """피부색 점수 기반으로 최적 크롭 범위를 제안.
    총 피부색의 70%를 포함하는 가장 좁은 연속 범위를 찾고 여유를 추가."""
    if not scores:
        return None

    total = sum(scores)
    if total < 0.05:  # 피부색이 거의 없으면 제안 불가
        return None

    target = total * 0.70
    best_range = None
    best_width = divisions + 1

    # 슬라이딩 윈도우로 가장 좁은 범위 찾기
    for width in range(1, divisions + 1):
        for start in range(divisions - width + 1):
            window_sum = sum(scores[start:start + width])
            if window_sum >= target and width < best_width:
                best_width = width
                best_range = (start, start + width)
                break  # 같은 width에서 첫 매치면 충분
        if best_range and best_width == width:
            break  # 최소 width를 찾았으면 종료

    if not best_range:
        return None

    # 여유 1칸 추가
    left = max(0, best_range[0] - 1)
    right = min(divisions, best_range[1] + 1)

    return left, right


def generate_gridline_preview(input_video, clip_ss, clip_duration, output_name, src_w, src_h, divisions, outdir, do_suggest=False):
    """기준선이 그려진 프레임 캡처 (시작 + 중간). suggest 모드면 제안 범위도 표시."""
    base = os.path.splitext(output_name)[0]
    interval = src_w / divisions

    clip_start_sec = ts_to_sec(clip_ss)
    clip_dur_sec = ts_to_sec(clip_duration)
    mid_sec = clip_start_sec + clip_dur_sec / 2

    timestamps = [
        (clip_ss, "start"),
        (f"00:{int(mid_sec//60):02d}:{mid_sec%60:06.3f}", "mid"),
    ]

    # 제안 범위 분석 (두 프레임의 분석 결과를 합산)
    suggestion = None
    if do_suggest:
        all_scores = []
        for ts, _ in timestamps:
            scores = analyze_frame_skin(input_video, ts, src_w, src_h, divisions)
            if scores:
                all_scores.append(scores)

        if all_scores:
            # 두 프레임 점수를 평균
            avg_scores = []
            for i in range(divisions):
                avg = sum(s[i] for s in all_scores) / len(all_scores)
                avg_scores.append(avg)
            suggestion = suggest_crop_range(avg_scores, divisions)

    for ts, label in timestamps:
        # drawbox로 세로선 + drawtext로 번호
        filters = []

        # 제안 범위를 초록색 반투명 영역으로 표시
        if suggestion:
            sug_left, sug_right = suggestion
            sug_x = int(sug_left * interval)
            sug_w = int((sug_right - sug_left) * interval)
            # 상단에 초록색 제안 바
            filters.append(
                f"drawbox=x={sug_x}:y=0:w={sug_w}:h=60:color=green@0.5:t=fill"
            )
            # 하단에도
            filters.append(
                f"drawbox=x={sug_x}:y={src_h - 60}:w={sug_w}:h=60:color=green@0.5:t=fill"
            )
            # 제안 범위 텍스트
            filters.append(
                f"drawtext=text='suggest {sug_left}~{sug_right}'"
                f":fontsize=40"
                f":fontcolor=green"
                f":borderw=3:bordercolor=black"
                f":x={sug_x + 10}:y=10"
                f":fontfile=/System/Library/Fonts/AppleSDGothicNeo.ttc"
            )

        for i in range(divisions + 1):
            x = int(i * interval)
            if x >= src_w:
                x = src_w - 1

            # 세로선 (짝수=노란색, 홀수=하얀색)
            color = "yellow" if i % 2 == 0 else "white"
            filters.append(
                f"drawbox=x={x}:y=0:w=2:h={src_h}:color={color}@0.8:t=fill"
            )

            # 번호 라벨
            label_x = x + 5 if x < src_w - 50 else x - 40
            filters.append(
                f"drawtext=text='{i}'"
                f":fontsize=36"
                f":fontcolor={color}"
                f":borderw=2:bordercolor=black"
                f":x={label_x}:y=20"
                f":fontfile=/System/Library/Fonts/AppleSDGothicNeo.ttc"
            )
            # 하단에도 번호
            filters.append(
                f"drawtext=text='{i}'"
                f":fontsize=36"
                f":fontcolor={color}"
                f":borderw=2:bordercolor=black"
                f":x={label_x}:y={src_h - 50}"
                f":fontfile=/System/Library/Fonts/AppleSDGothicNeo.ttc"
            )

        # 픽셀 좌표 안내 (상단 중앙)
        info_text = f"width={src_w}  divisions={divisions}  interval={interval:.0f}px"
        filters.append(
            f"drawtext=text='{info_text}'"
            f":fontsize=24"
            f":fontcolor=white"
            f":borderw=2:bordercolor=black"
            f":x=(w-text_w)/2:y={src_h//2}"
            f":fontfile=/System/Library/Fonts/AppleSDGothicNeo.ttc"
        )

        vf = ",".join(filters)
        output_path = os.path.join(outdir, f"{base}_grid_{label}.jpg")

        subprocess.run([
            "ffmpeg", "-y", "-ss", ts, "-i", input_video,
            "-frames:v", "1", "-vf", vf,
            "-q:v", "2", output_path
        ], capture_output=True, text=True)

        if os.path.exists(output_path):
            print(f"    {label}: {output_path}")

    return suggestion


def main():
    parser = argparse.ArgumentParser(description="크롭 기준선 미리보기")
    parser.add_argument("--input", "-i", required=True, help="원본 영상 파일")
    parser.add_argument("--clips", "-c", required=True, help="클립 목록 파일")
    parser.add_argument("--outdir", "-o", default="previews", help="출력 디렉토리")
    parser.add_argument("--divisions", "-d", type=int, default=10, help="분할 수 (기본: 10)")
    parser.add_argument("--suggest", action="store_true", help="크롭 범위 자동 제안 (프레임 분석)")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    src_w, src_h = get_video_dimensions(args.input)
    clips = parse_clips_file(args.clips)

    print(f"원본: {src_w}x{src_h}")
    print(f"분할: {args.divisions}등분 ({src_w // args.divisions}px 간격)")
    if args.suggest:
        print(f"모드: 자동 크롭 범위 제안 활성화")
    print(f"사용법: '2번~5번 사이로 잘라줘' → 크롭 x={int(2 * src_w / args.divisions)}~{int(5 * src_w / args.divisions)}\n")

    suggestions = {}
    for ss, t, name in clips:
        print(f"  [{name}]")
        sug = generate_gridline_preview(
            args.input, ss, t, name, src_w, src_h, args.divisions, args.outdir,
            do_suggest=args.suggest
        )
        if sug:
            suggestions[name] = sug
            print(f"    → 제안: {sug[0]}~{sug[1]}")

    print(f"\n=== 기준선 미리보기 완료 ===")
    print(f"'{args.outdir}/' 폴더에서 확인하세요.")

    if suggestions:
        print(f"\n자동 제안 범위:")
        for name, (left, right) in suggestions.items():
            print(f"  {name}: {left}~{right}")
        print(f"\n제안은 참고용입니다. 원하는 범위를 알려주세요.")
    else:
        print(f"원하는 범위를 알려주세요 (예: '1번 클립은 2~6, 나머지는 3~7')")


if __name__ == "__main__":
    main()
