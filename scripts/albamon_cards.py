#!/usr/bin/env python3
"""
알바몬 최근 3일 공고를 내부용 카드형 쇼츠로 만든다.

- 원본 이미지/본문을 재배포하지 않고 목록형 메타데이터만 사용
- 최근 3일 + 최신등록순 기준으로 페이지를 순회
- 카드 목록 HTML 리포트 생성
- 필터링된 카드만 9:16 mp4로 렌더 가능

예시:
  python3 scripts/albamon_cards.py fetch --outdir projects/albamon_cards_demo
  python3 scripts/albamon_cards.py render --jobs-json projects/albamon_cards_demo/jobs.json --query 커피
  python3 scripts/albamon_cards.py build --keyword 커피 --keyword 바리스타 --max-items 20
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import shlex
import subprocess
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union
from urllib.parse import urlencode

LISTING_URL = "https://www.albamon.com/jobs/total"
DETAIL_URL = "https://www.albamon.com/jobs/detail/{recruit_no}"
DEFAULT_SEARCH_PERIOD = "WITHIN_THREE_DAYS"
DEFAULT_SORT_TYPE = "POSTED_DATE"
DEFAULT_FONTFILE = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
WIDTH = 1080
HEIGHT = 1920
FPS = 30
AUDIO_SAMPLE_RATE = 48000
SEGMENT_CODEC = "libx264"
SEGMENT_AUDIO_CODEC = "aac"
HEADER_TEXT = "ALBAMON / 최근 3일 신규"
FOOTER_TEXT = "원문 상세 공고 확인 후 판단하세요"

PALETTES = [
    {
        "bg": "0x09111d",
        "panel": "0x121e31@0.96",
        "accent": "0x52b3ff",
        "accent_soft": "0x52b3ff@0.12",
        "muted": "0xffffff@0.72",
    },
    {
        "bg": "0x12110d",
        "panel": "0x1d1913@0.96",
        "accent": "0xffa94d",
        "accent_soft": "0xffa94d@0.12",
        "muted": "0xffffff@0.72",
    },
    {
        "bg": "0x0d1411",
        "panel": "0x142119@0.96",
        "accent": "0x5dd39e",
        "accent_soft": "0x5dd39e@0.12",
        "muted": "0xffffff@0.72",
    },
    {
        "bg": "0x151020",
        "panel": "0x1d172b@0.96",
        "accent": "0xf284ff",
        "accent_soft": "0xf284ff@0.12",
        "muted": "0xffffff@0.72",
    },
    {
        "bg": "0x131313",
        "panel": "0x1d1d1d@0.96",
        "accent": "0xff6b6b",
        "accent_soft": "0xff6b6b@0.12",
        "muted": "0xffffff@0.72",
    },
]


def run_command(cmd: List[str], capture_output: bool = False) -> str:
    result = subprocess.run(cmd, capture_output=capture_output, text=True)
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        details = stderr or stdout or "알 수 없는 오류"
        raise SystemExit(f"명령 실행 실패: {' '.join(shlex.quote(part) for part in cmd)}\n{details}")
    return result.stdout if capture_output else ""


def fetch_text(url: str) -> str:
    return run_command(["curl", "-fsSL", "--compressed", url], capture_output=True)


def build_listing_url(page: int, search_period: str, sort_type: str) -> str:
    query = urlencode(
        {
            "searchPeriodType": search_period,
            "sortType": sort_type,
            "page": page,
        }
    )
    return f"{LISTING_URL}?{query}"


def extract_next_data(raw_html: str) -> dict:
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        raw_html,
        re.DOTALL,
    )
    if not match:
        raise SystemExit("__NEXT_DATA__를 찾지 못했습니다. 페이지 구조가 바뀌었을 수 있습니다.")
    return json.loads(html.unescape(match.group(1)))


def extract_collection(next_data: dict) -> Tuple[List[dict], int]:
    queries = (
        next_data.get("props", {})
        .get("pageProps", {})
        .get("dehydratedState", {})
        .get("queries", [])
    )
    for query in queries:
        state = query.get("state", {})
        data = state.get("data", {})
        base = data.get("base", {})
        normal = base.get("normal", {})
        collection = normal.get("collection")
        if isinstance(collection, list):
            total_count = base.get("pagination", {}).get("totalCount", 0)
            return collection, int(total_count or 0)
    raise SystemExit("공고 목록 데이터를 찾지 못했습니다.")


def clean_text(value: object) -> str:
    text = str(value or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def combine_nonempty(*values: str, sep: str = " · ") -> str:
    parts = [clean_text(value) for value in values if clean_text(value)]
    return sep.join(parts)


def extract_number(value: str) -> int:
    digits = re.findall(r"\d+", value.replace(",", ""))
    if not digits:
        return 0
    return int("".join(digits))


def extract_minutes_ago(value: str) -> int:
    match = re.search(r"(\d+)\s*분전", clean_text(value))
    if match:
        return int(match.group(1))
    if "방금" in clean_text(value):
        return 0
    return 999999


def normalize_primary_area(value: str) -> str:
    text = clean_text(value)
    if not text:
        return ""
    return text.split()[0]


def normalize_job(raw: dict, page: int) -> dict:
    recruit_no = int(raw.get("recruitNo") or 0)
    pay_type = clean_text(raw.get("payType", {}).get("description"))
    pay = clean_text(raw.get("pay"))
    working_time = clean_text(raw.get("workingTime")) or "시간협의"
    working_week = clean_text(raw.get("workingWeek"))
    working_period = clean_text(raw.get("workingPeriod"))
    workplace_area = clean_text(raw.get("workplaceArea")) or clean_text(raw.get("workplaceAddress"))
    parts = [clean_text(part) for part in raw.get("parts", []) if clean_text(part)]
    title = clean_text(raw.get("recruitTitle"))
    company_name = clean_text(raw.get("companyName"))
    closing = clean_text(raw.get("closingDateWithDDay")) or clean_text(raw.get("closingDate"))
    posted_date = clean_text(raw.get("postedDate"))

    return {
        "recruit_no": recruit_no,
        "page": page,
        "title": title,
        "company_name": company_name,
        "posted_date": posted_date,
        "posted_minutes_ago": extract_minutes_ago(posted_date),
        "pay_type": pay_type,
        "pay": pay,
        "pay_amount": extract_number(pay),
        "pay_summary": combine_nonempty(pay_type, pay, sep=" "),
        "workplace_area": workplace_area,
        "area_primary": normalize_primary_area(workplace_area),
        "working_time": working_time,
        "working_week": working_week,
        "working_period": working_period,
        "working_summary": combine_nonempty(working_week, working_time),
        "closing_date": closing,
        "parts": parts,
        "parts_summary": ", ".join(parts[:3]),
        "detail_url": DETAIL_URL.format(recruit_no=recruit_no),
    }


def build_search_text(job: dict) -> str:
    values = [
        job.get("title", ""),
        job.get("company_name", ""),
        job.get("workplace_area", ""),
        job.get("pay_summary", ""),
        job.get("working_summary", ""),
        job.get("parts_summary", ""),
    ]
    return " ".join(values).casefold()


def fetch_matches_keywords(job: dict, include_keywords: List[str], exclude_keywords: List[str]) -> bool:
    haystack = build_search_text(job)
    if include_keywords and not any(keyword.casefold() in haystack for keyword in include_keywords):
        return False
    if any(keyword.casefold() in haystack for keyword in exclude_keywords):
        return False
    return True


def fetch_jobs(
    max_pages: int,
    max_items: int,
    search_period: str,
    sort_type: str,
    include_keywords: List[str],
    exclude_keywords: List[str],
) -> Tuple[List[dict], List[dict], int]:
    jobs: List[dict] = []
    pages: List[dict] = []
    seen: Set[int] = set()
    total_count_estimate = 0

    for page in range(1, max_pages + 1):
        url = build_listing_url(page=page, search_period=search_period, sort_type=sort_type)
        next_data = extract_next_data(fetch_text(url))
        collection, total_count = extract_collection(next_data)
        if total_count:
            total_count_estimate = total_count
        pages.append(
            {
                "page": page,
                "url": url,
                "collection_count": len(collection),
            }
        )

        if not collection:
            break

        for raw in collection:
            job = normalize_job(raw, page=page)
            recruit_no = job["recruit_no"]
            if recruit_no <= 0 or recruit_no in seen:
                continue
            if not fetch_matches_keywords(job, include_keywords, exclude_keywords):
                continue
            job["sort_index"] = len(jobs)
            seen.add(recruit_no)
            jobs.append(job)
            if len(jobs) >= max_items:
                return jobs, pages, total_count_estimate

        if len(collection) < 20:
            break

    return jobs, pages, total_count_estimate


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, payload: Union[dict, list]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def html_escape(value: object) -> str:
    return html.escape(clean_text(value))


def safe_json_dumps(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def display_width(text: str) -> int:
    total = 0
    for ch in text:
        total += 2 if unicodedata.east_asian_width(ch) in {"F", "W"} else 1
    return total


def ellipsize(text: str, max_width: int) -> str:
    text = clean_text(text)
    if display_width(text) <= max_width:
        return text
    ellipsis = "..."
    allowed = max(1, max_width - len(ellipsis))
    result = ""
    for ch in text:
        if display_width(result + ch) > allowed:
            break
        result += ch
    return (result.rstrip() or text[:1]) + ellipsis


def wrap_text(text: str, max_width: int, max_lines: int) -> str:
    text = clean_text(text)
    if not text:
        return ""

    lines: List[str] = []
    current = ""
    index = 0

    while index < len(text):
        ch = text[index]
        if not current and ch == " ":
            index += 1
            continue

        candidate = current + ch
        if current and display_width(candidate) > max_width:
            lines.append(current.rstrip())
            current = ""
            if len(lines) == max_lines:
                remaining = clean_text(text[index:])
                if remaining:
                    lines[-1] = ellipsize(lines[-1] + " " + remaining, max_width)
                return "\n".join(lines)
            continue

        current = candidate
        index += 1

    if current:
        lines.append(current.rstrip())

    if len(lines) > max_lines:
        lines = lines[: max_lines - 1] + [ellipsize(" ".join(lines[max_lines - 1 :]), max_width)]
    return "\n".join(line for line in lines if line)


def build_summary_text(jobs: List[dict]) -> str:
    lines: List[str] = []
    for index, job in enumerate(jobs, start=1):
        lines.append(f"{index}. {job['title']}")
        lines.append(f"   회사: {job['company_name']}")
        lines.append(f"   조건: {combine_nonempty(job['pay_summary'], job['workplace_area'], job['working_summary'])}")
        lines.append(f"   등록: {combine_nonempty(job['posted_date'], job['closing_date'])}")
        lines.append(f"   링크: {job['detail_url']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def build_filter_context(args: argparse.Namespace) -> dict:
    return {
        "query": clean_text(getattr(args, "query", "")),
        "exclude_query": clean_text(getattr(args, "exclude_query", "")),
        "area": clean_text(getattr(args, "area", "")),
        "company": clean_text(getattr(args, "company", "")),
        "pay_type": clean_text(getattr(args, "pay_type", "")),
        "part": clean_text(getattr(args, "part", "")),
        "job_ids": [int(value) for value in (getattr(args, "job_id", []) or [])],
    }


def apply_job_filters(jobs: List[dict], filter_context: dict) -> List[dict]:
    query = filter_context.get("query", "").casefold()
    exclude_query = filter_context.get("exclude_query", "").casefold()
    area = filter_context.get("area", "").casefold()
    company = filter_context.get("company", "").casefold()
    pay_type = filter_context.get("pay_type", "").casefold()
    part = filter_context.get("part", "").casefold()
    job_ids = set(filter_context.get("job_ids", []))

    filtered: List[dict] = []
    for job in jobs:
        haystack = build_search_text(job)
        if query and query not in haystack:
            continue
        if exclude_query and exclude_query in haystack:
            continue
        if area and area not in clean_text(job.get("workplace_area", "")).casefold() and area not in clean_text(job.get("area_primary", "")).casefold():
            continue
        if company and company not in clean_text(job.get("company_name", "")).casefold():
            continue
        if pay_type and pay_type not in clean_text(job.get("pay_type", "")).casefold():
            continue
        if part:
            part_haystack = " ".join(job.get("parts", [])).casefold()
            if part not in part_haystack:
                continue
        if job_ids and int(job.get("recruit_no", 0)) not in job_ids:
            continue
        filtered.append(job)
    return filtered


def build_report_html(outdir: Path, jobs_json_path: Path, payload: dict) -> str:
    jobs = payload.get("jobs", [])
    area_options = sorted({job.get("area_primary", "") for job in jobs if clean_text(job.get("area_primary", ""))})
    pay_type_options = sorted({job.get("pay_type", "") for job in jobs if clean_text(job.get("pay_type", ""))})
    part_options = sorted({part for job in jobs for part in job.get("parts", []) if clean_text(part)})

    report_meta = {
        "generated_at": payload.get("fetched_at"),
        "jobs_json_path": str(jobs_json_path),
        "selection_storage_key": f"albamon_cards::{jobs_json_path.resolve()}",
        "source": payload.get("source", {}),
        "job_count": len(jobs),
        "area_options": area_options,
        "pay_type_options": pay_type_options,
        "part_options": part_options,
        "render_command_hint": "python3 scripts/albamon_cards.py render --jobs-json <filtered_jobs.json> --segment-duration 1.0",
    }

    template = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Albamon Cards Report</title>
  <style>
    :root {
      --bg: #07111b;
      --panel: rgba(16, 30, 46, 0.94);
      --panel-2: rgba(22, 42, 62, 0.84);
      --accent: #52b3ff;
      --accent-soft: rgba(82, 179, 255, 0.14);
      --text: #f4f8fb;
      --muted: rgba(244, 248, 251, 0.72);
      --border: rgba(255, 255, 255, 0.08);
      --shadow: 0 24px 80px rgba(0, 0, 0, 0.36);
      --chip: rgba(255, 255, 255, 0.06);
      --selected: rgba(93, 211, 158, 0.18);
      --selected-border: rgba(93, 211, 158, 0.5);
      --danger: #ff8b8b;
      --font: "Pretendard", "Apple SD Gothic Neo", "Noto Sans KR", sans-serif;
    }

    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; background:
      radial-gradient(circle at top left, rgba(82,179,255,0.18), transparent 28%),
      radial-gradient(circle at bottom right, rgba(255,169,77,0.12), transparent 22%),
      var(--bg);
      color: var(--text);
      font-family: var(--font);
    }

    body {
      padding: 28px;
    }

    .shell {
      max-width: 1440px;
      margin: 0 auto;
      display: grid;
      grid-template-columns: 320px minmax(0, 1fr);
      gap: 22px;
      align-items: start;
    }

    .sidebar,
    .content {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 26px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(16px);
    }

    .sidebar {
      position: sticky;
      top: 20px;
      padding: 22px;
    }

    .content {
      padding: 22px;
    }

    .eyebrow {
      display: inline-flex;
      padding: 8px 12px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.02em;
    }

    h1 {
      margin: 14px 0 8px;
      font-size: 34px;
      line-height: 1.1;
    }

    .lede,
    .hint,
    .summary,
    .command {
      color: var(--muted);
      line-height: 1.55;
    }

    .section-title {
      margin: 22px 0 10px;
      font-size: 14px;
      font-weight: 700;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }

    .field {
      margin-bottom: 12px;
    }

    .field label {
      display: block;
      margin-bottom: 6px;
      font-size: 13px;
      color: var(--muted);
    }

    .field input,
    .field select {
      width: 100%;
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid var(--border);
      background: rgba(255, 255, 255, 0.04);
      color: var(--text);
      font: inherit;
      outline: none;
    }

    .field input:focus,
    .field select:focus {
      border-color: rgba(82, 179, 255, 0.6);
      box-shadow: 0 0 0 4px rgba(82, 179, 255, 0.14);
    }

    .toggle {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-top: 4px;
      color: var(--muted);
      font-size: 14px;
    }

    .toggle input {
      width: 18px;
      height: 18px;
      accent-color: var(--accent);
    }

    .button-row {
      display: grid;
      gap: 10px;
      margin-top: 14px;
    }

    button {
      border: 0;
      border-radius: 14px;
      padding: 12px 14px;
      font: inherit;
      cursor: pointer;
      color: #06121c;
      background: var(--accent);
      font-weight: 700;
    }

    button.secondary {
      background: rgba(255, 255, 255, 0.08);
      color: var(--text);
      border: 1px solid var(--border);
    }

    button.ghost {
      background: transparent;
      color: var(--muted);
      border: 1px dashed var(--border);
    }

    .stats {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }

    .stat {
      padding: 14px 16px;
      border-radius: 18px;
      background: var(--panel-2);
      border: 1px solid var(--border);
    }

    .stat strong {
      display: block;
      font-size: 24px;
      margin-top: 6px;
    }

    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
    }

    .empty {
      padding: 40px 24px;
      text-align: center;
      border: 1px dashed var(--border);
      border-radius: 22px;
      color: var(--muted);
      background: rgba(255, 255, 255, 0.03);
    }

    .card {
      position: relative;
      overflow: hidden;
      border-radius: 24px;
      padding: 18px;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.02)),
        rgba(18, 30, 46, 0.9);
      border: 1px solid var(--border);
      transition: transform 180ms ease, border-color 180ms ease, background 180ms ease;
    }

    .card:hover {
      transform: translateY(-2px);
      border-color: rgba(82, 179, 255, 0.35);
    }

    .card.is-selected {
      background:
        linear-gradient(180deg, rgba(93,211,158,0.08), rgba(93,211,158,0.03)),
        rgba(18, 30, 46, 0.96);
      border-color: var(--selected-border);
      box-shadow: inset 0 0 0 1px rgba(93,211,158,0.18);
    }

    .card::before {
      content: "";
      position: absolute;
      inset: 0 auto 0 0;
      width: 6px;
      background: linear-gradient(180deg, var(--accent), rgba(82,179,255,0.2));
    }

    .card-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      margin-bottom: 14px;
    }

    .badge {
      display: inline-flex;
      padding: 8px 10px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      font-size: 12px;
      font-weight: 700;
    }

    .company {
      margin: 0 0 6px;
      color: var(--muted);
      font-size: 14px;
    }

    .title {
      margin: 0 0 16px;
      font-size: 26px;
      line-height: 1.22;
      letter-spacing: -0.02em;
    }

    .pay-box {
      padding: 14px;
      border-radius: 18px;
      background: var(--accent-soft);
      border: 1px solid rgba(82, 179, 255, 0.18);
      margin-bottom: 14px;
    }

    .pay-box .label,
    .meta-label {
      display: block;
      margin-bottom: 6px;
      font-size: 12px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }

    .pay-value {
      font-size: 30px;
      font-weight: 800;
      color: var(--accent);
      line-height: 1.1;
    }

    .meta-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin-bottom: 12px;
    }

    .meta-box {
      padding: 12px;
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.05);
      min-height: 90px;
    }

    .meta-value {
      font-size: 16px;
      line-height: 1.35;
      word-break: keep-all;
      white-space: pre-line;
    }

    .detail-box {
      padding: 14px;
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.04);
      margin-bottom: 14px;
      min-height: 132px;
    }

    .detail-row + .detail-row {
      margin-top: 12px;
    }

    .detail-value {
      font-size: 18px;
      line-height: 1.45;
      white-space: pre-line;
      word-break: keep-all;
    }

    .chips {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 14px;
    }

    .chip {
      display: inline-flex;
      padding: 7px 10px;
      border-radius: 999px;
      background: var(--chip);
      color: var(--muted);
      font-size: 12px;
    }

    .card-actions {
      display: flex;
      gap: 10px;
      align-items: center;
      margin-top: auto;
    }

    .card-actions a,
    .card-actions button {
      flex: 1;
      text-align: center;
      text-decoration: none;
    }

    .card-actions a {
      padding: 11px 12px;
      border-radius: 14px;
      background: rgba(255, 255, 255, 0.07);
      color: var(--text);
      border: 1px solid var(--border);
      font-weight: 700;
    }

    .command {
      margin-top: 14px;
      padding: 14px;
      border-radius: 16px;
      border: 1px dashed var(--border);
      background: rgba(255, 255, 255, 0.03);
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 13px;
      white-space: pre-wrap;
      word-break: break-word;
    }

    .note {
      margin-top: 14px;
      padding: 14px;
      border-radius: 16px;
      background: rgba(255, 139, 139, 0.08);
      border: 1px solid rgba(255, 139, 139, 0.18);
      color: rgba(255, 229, 229, 0.92);
      line-height: 1.5;
    }

    @media (max-width: 1100px) {
      .shell {
        grid-template-columns: 1fr;
      }
      .sidebar {
        position: static;
      }
    }

    @media (max-width: 720px) {
      body { padding: 16px; }
      .content, .sidebar { padding: 16px; border-radius: 20px; }
      h1 { font-size: 28px; }
      .title { font-size: 22px; }
      .stats { grid-template-columns: 1fr; }
      .meta-grid { grid-template-columns: 1fr; }
      .card-actions { flex-direction: column; }
      .card-actions a, .card-actions button { width: 100%; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <aside class="sidebar">
      <span class="eyebrow">Internal Report</span>
      <h1>카드 목록 필터</h1>
      <p class="lede">먼저 목록을 좁혀보고, 필터 결과나 선택된 카드만 JSON으로 내려받아 1초 템포 쇼츠로 렌더할 수 있습니다.</p>

      <div class="section-title">검색</div>
      <div class="field">
        <label for="query">통합 검색</label>
        <input id="query" type="text" placeholder="제목, 회사, 지역, 직무 검색">
      </div>
      <div class="field">
        <label for="area">대표 지역</label>
        <select id="area"></select>
      </div>
      <div class="field">
        <label for="payType">급여 타입</label>
        <select id="payType"></select>
      </div>
      <div class="field">
        <label for="part">직무</label>
        <select id="part"></select>
      </div>
      <div class="field">
        <label for="company">회사명 검색</label>
        <input id="company" type="text" placeholder="브랜드/회사명">
      </div>
      <div class="field">
        <label for="sort">정렬</label>
        <select id="sort">
          <option value="latest">최신순 유지</option>
          <option value="pay">금액 높은순</option>
          <option value="title">제목 가나다순</option>
          <option value="company">회사명 가나다순</option>
        </select>
      </div>

      <label class="toggle">
        <input id="selectedOnly" type="checkbox">
        <span>선택한 카드만 보기</span>
      </label>

      <div class="button-row">
        <button id="downloadFiltered">필터 결과 JSON 다운로드</button>
        <button id="downloadSelected" class="secondary">선택 카드 JSON 다운로드</button>
        <button id="resetSelection" class="ghost">선택 초기화</button>
      </div>

      <div class="section-title">렌더 힌트</div>
      <div class="command" id="renderCommand"></div>

      <div class="section-title">안내</div>
      <div class="summary" id="reportSummary"></div>

      <div class="note">이 리포트는 메타데이터 기반 내부 참고용입니다. 원문 세부 내용은 링크로 다시 확인하세요.</div>
    </aside>

    <main class="content">
      <div class="stats">
        <div class="stat">
          <div class="summary">전체 카드</div>
          <strong id="totalCount">0</strong>
        </div>
        <div class="stat">
          <div class="summary">필터 결과</div>
          <strong id="filteredCount">0</strong>
        </div>
        <div class="stat">
          <div class="summary">선택 카드</div>
          <strong id="selectedCount">0</strong>
        </div>
      </div>

      <div class="hint" id="activeFilters"></div>
      <div class="grid" id="cardsGrid"></div>
      <div class="empty" id="emptyState" hidden>조건에 맞는 카드가 없습니다. 필터를 완화해보세요.</div>
    </main>
  </div>

  <script>
    const REPORT_META = __REPORT_META__;
    const JOBS = __JOBS__;

    const state = {
      query: "",
      area: "",
      payType: "",
      part: "",
      company: "",
      sort: "latest",
      selectedOnly: false,
    };

    const selectedIds = new Set(JSON.parse(localStorage.getItem(REPORT_META.selection_storage_key) || "[]"));

    const els = {
      query: document.getElementById("query"),
      area: document.getElementById("area"),
      payType: document.getElementById("payType"),
      part: document.getElementById("part"),
      company: document.getElementById("company"),
      sort: document.getElementById("sort"),
      selectedOnly: document.getElementById("selectedOnly"),
      cardsGrid: document.getElementById("cardsGrid"),
      emptyState: document.getElementById("emptyState"),
      totalCount: document.getElementById("totalCount"),
      filteredCount: document.getElementById("filteredCount"),
      selectedCount: document.getElementById("selectedCount"),
      renderCommand: document.getElementById("renderCommand"),
      reportSummary: document.getElementById("reportSummary"),
      activeFilters: document.getElementById("activeFilters"),
      downloadFiltered: document.getElementById("downloadFiltered"),
      downloadSelected: document.getElementById("downloadSelected"),
      resetSelection: document.getElementById("resetSelection"),
    };

    function saveSelection() {
      localStorage.setItem(REPORT_META.selection_storage_key, JSON.stringify(Array.from(selectedIds)));
    }

    function fillSelect(select, options, placeholder) {
      select.innerHTML = "";
      const empty = document.createElement("option");
      empty.value = "";
      empty.textContent = placeholder;
      select.appendChild(empty);
      for (const option of options) {
        const node = document.createElement("option");
        node.value = option;
        node.textContent = option;
        select.appendChild(node);
      }
    }

    function normalizeText(value) {
      return String(value || "").toLowerCase().trim();
    }

    function jobMatches(job) {
      const haystack = [
        job.title,
        job.company_name,
        job.workplace_area,
        job.pay_summary,
        job.working_summary,
        job.parts_summary,
      ].join(" ").toLowerCase();

      if (state.query && !haystack.includes(state.query)) return false;
      if (state.area && normalizeText(job.area_primary) !== state.area) return false;
      if (state.payType && normalizeText(job.pay_type) !== state.payType) return false;
      if (state.part) {
        const partHaystack = (job.parts || []).join(" ").toLowerCase();
        if (!partHaystack.includes(state.part)) return false;
      }
      if (state.company && !normalizeText(job.company_name).includes(state.company)) return false;
      if (state.selectedOnly && !selectedIds.has(job.recruit_no)) return false;
      return true;
    }

    function sortJobs(items) {
      const next = items.slice();
      if (state.sort === "pay") {
        next.sort((a, b) => (b.pay_amount || 0) - (a.pay_amount || 0) || (a.sort_index || 0) - (b.sort_index || 0));
      } else if (state.sort === "title") {
        next.sort((a, b) => (a.title || "").localeCompare(b.title || "", "ko"));
      } else if (state.sort === "company") {
        next.sort((a, b) => (a.company_name || "").localeCompare(b.company_name || "", "ko"));
      } else {
        next.sort((a, b) => (a.sort_index || 0) - (b.sort_index || 0));
      }
      return next;
    }

    function getFilteredJobs() {
      return sortJobs(JOBS.filter(jobMatches));
    }

    function formatFilterSummary() {
      const chips = [];
      if (state.query) chips.push(`검색: ${state.query}`);
      if (state.area) chips.push(`지역: ${state.area}`);
      if (state.payType) chips.push(`급여: ${state.payType}`);
      if (state.part) chips.push(`직무: ${state.part}`);
      if (state.company) chips.push(`회사: ${state.company}`);
      if (state.selectedOnly) chips.push("선택 카드만");
      if (!chips.length) return "현재는 전체 카드가 보입니다.";
      return chips.join(" / ");
    }

    function renderCommandHint() {
      const args = [`python3 scripts/albamon_cards.py render --jobs-json "${REPORT_META.jobs_json_path}" --segment-duration 1.0`];
      if (state.query) args.push(`--query "${state.query}"`);
      if (state.area) args.push(`--area "${state.area}"`);
      if (state.payType) args.push(`--pay-type "${state.payType}"`);
      if (state.part) args.push(`--part "${state.part}"`);
      if (state.company) args.push(`--company "${state.company}"`);
      if (state.selectedOnly && selectedIds.size > 0) {
        for (const id of Array.from(selectedIds).slice(0, 12)) {
          args.push(`--job-id ${id}`);
        }
        if (selectedIds.size > 12) args.push(`# 나머지 ID도 추가`);
      }
      return args.join(" ");
    }

    function downloadJobs(filenamePrefix, jobs, mode) {
      const payload = {
        exported_at: new Date().toISOString(),
        export_mode: mode,
        source: REPORT_META.source,
        source_jobs_json_path: REPORT_META.jobs_json_path,
        filter_snapshot: {
          query: state.query,
          area: state.area,
          pay_type: state.payType,
          part: state.part,
          company: state.company,
          selected_only: state.selectedOnly,
          selected_ids: Array.from(selectedIds),
        },
        job_count: jobs.length,
        jobs,
      };
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${filenamePrefix}_${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    }

    function renderCards() {
      const filteredJobs = getFilteredJobs();
      const selectedJobs = JOBS.filter(job => selectedIds.has(job.recruit_no));
      els.cardsGrid.innerHTML = "";
      els.totalCount.textContent = String(JOBS.length);
      els.filteredCount.textContent = String(filteredJobs.length);
      els.selectedCount.textContent = String(selectedJobs.length);
      els.reportSummary.textContent = `수집 시각: ${REPORT_META.generated_at || "-"} / JSON: ${REPORT_META.jobs_json_path}`;
      els.activeFilters.textContent = formatFilterSummary();
      els.renderCommand.textContent = renderCommandHint();

      if (!filteredJobs.length) {
        els.emptyState.hidden = false;
        return;
      }

      els.emptyState.hidden = true;

      for (const job of filteredJobs) {
        const card = document.createElement("article");
        card.className = "card";
        if (selectedIds.has(job.recruit_no)) card.classList.add("is-selected");

        const chips = [job.area_primary, job.pay_type, job.posted_date].filter(Boolean)
          .map(value => `<span class="chip">${value}</span>`).join("");

        card.innerHTML = `
          <div class="card-head">
            <span class="badge">ID ${job.recruit_no}</span>
            <span class="badge">${(job.sort_index || 0) + 1}번째</span>
          </div>
          <p class="company">${escapeHtml(job.company_name)}</p>
          <h2 class="title">${escapeHtml(job.title)}</h2>
          <div class="pay-box">
            <span class="label">급여</span>
            <div class="pay-value">${escapeHtml(job.pay_summary || "급여 정보 없음")}</div>
          </div>
          <div class="meta-grid">
            <div class="meta-box">
              <span class="meta-label">근무지</span>
              <div class="meta-value">${escapeHtml(job.workplace_area || "-")}</div>
            </div>
            <div class="meta-box">
              <span class="meta-label">시간</span>
              <div class="meta-value">${escapeHtml(job.working_time || "-")}</div>
            </div>
            <div class="meta-box">
              <span class="meta-label">등록</span>
              <div class="meta-value">${escapeHtml(job.posted_date || "-")}</div>
            </div>
          </div>
          <div class="detail-box">
            <div class="detail-row">
              <span class="meta-label">직무</span>
              <div class="detail-value">${escapeHtml(job.parts_summary || "직무 정보 없음")}</div>
            </div>
            <div class="detail-row">
              <span class="meta-label">기간/마감</span>
              <div class="detail-value">${escapeHtml([job.working_period, job.working_week, job.closing_date].filter(Boolean).join(" · ") || "-")}</div>
            </div>
          </div>
          <div class="chips">${chips}</div>
          <div class="card-actions">
            <button type="button" class="secondary select-button">${selectedIds.has(job.recruit_no) ? "선택 해제" : "선택"}</button>
            <a href="${job.detail_url}" target="_blank" rel="noreferrer">상세 열기</a>
          </div>
        `;

        card.querySelector(".select-button").addEventListener("click", () => {
          if (selectedIds.has(job.recruit_no)) {
            selectedIds.delete(job.recruit_no);
          } else {
            selectedIds.add(job.recruit_no);
          }
          saveSelection();
          renderCards();
        });

        els.cardsGrid.appendChild(card);
      }
    }

    function escapeHtml(value) {
      return String(value || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    function syncState() {
      state.query = normalizeText(els.query.value);
      state.area = normalizeText(els.area.value);
      state.payType = normalizeText(els.payType.value);
      state.part = normalizeText(els.part.value);
      state.company = normalizeText(els.company.value);
      state.sort = els.sort.value;
      state.selectedOnly = els.selectedOnly.checked;
      renderCards();
    }

    function init() {
      fillSelect(els.area, REPORT_META.area_options, "전체 지역");
      fillSelect(els.payType, REPORT_META.pay_type_options, "전체 급여 타입");
      fillSelect(els.part, REPORT_META.part_options, "전체 직무");

      [els.query, els.area, els.payType, els.part, els.company, els.sort, els.selectedOnly].forEach((node) => {
        node.addEventListener("input", syncState);
        node.addEventListener("change", syncState);
      });

      els.downloadFiltered.addEventListener("click", () => {
        downloadJobs("albamon_filtered_jobs", getFilteredJobs(), "filtered");
      });

      els.downloadSelected.addEventListener("click", () => {
        const selected = JOBS.filter(job => selectedIds.has(job.recruit_no));
        downloadJobs("albamon_selected_jobs", selected, "selected");
      });

      els.resetSelection.addEventListener("click", () => {
        selectedIds.clear();
        saveSelection();
        renderCards();
      });

      renderCards();
    }

    init();
  </script>
</body>
</html>
"""

    return (
        template
        .replace("__REPORT_META__", safe_json_dumps(report_meta))
        .replace("__JOBS__", safe_json_dumps(jobs))
    )


def write_browser_report(outdir: Path, jobs_json_path: Path, payload: dict) -> Path:
    report_path = outdir / "cards.html"
    write_text(report_path, build_report_html(outdir=outdir, jobs_json_path=jobs_json_path, payload=payload))
    return report_path


def make_card_blocks(job: dict, index: int, total: int) -> dict:
    title = wrap_text(job["title"], max_width=24, max_lines=3)
    company = wrap_text(job["company_name"], max_width=28, max_lines=2)
    pay = wrap_text(job["pay_summary"] or "급여 정보 없음", max_width=20, max_lines=2)
    area_value = wrap_text(job["workplace_area"] or "근무지 미기재", max_width=13, max_lines=2)
    time_value = wrap_text(job["working_time"] or "시간협의", max_width=13, max_lines=2)
    posted_value = wrap_text(job["posted_date"] or "등록일 미기재", max_width=10, max_lines=2)
    parts_value = wrap_text(job["parts_summary"] or "직무 정보 없음", max_width=34, max_lines=2)
    period_value = wrap_text(
        combine_nonempty(job["working_period"], job["working_week"], job["closing_date"]),
        max_width=34,
        max_lines=2,
    )
    id_value = wrap_text(
        f"공고 ID {job['recruit_no']} / 상세 링크는 jobs.json 확인",
        max_width=48,
        max_lines=2,
    )

    return {
        "header": HEADER_TEXT,
        "counter": f"{index}/{total}",
        "title": title,
        "company_label": "회사",
        "company": company,
        "pay_label": "급여",
        "pay": pay,
        "area_label": "근무지",
        "area_value": area_value,
        "time_label": "시간",
        "time_value": time_value,
        "posted_label": "등록",
        "posted_value": posted_value,
        "parts_label": "직무",
        "parts_value": parts_value,
        "period_label": "기간/마감",
        "period_value": period_value,
        "id_value": id_value,
        "footer": FOOTER_TEXT,
    }


def escape_filter_path(path: Union[Path, str]) -> str:
    return str(path).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def text_filter(
    fontfile: Union[Path, str],
    textfile: Path,
    fontsize: int,
    x: Union[str, int],
    y: Union[str, int],
    color: str = "white",
    extra: str = "",
) -> str:
    return (
        "drawtext="
        f"fontfile='{escape_filter_path(fontfile)}':"
        f"textfile='{escape_filter_path(textfile)}':"
        f"fontsize={fontsize}:"
        f"fontcolor={color}:"
        "borderw=0:"
        f"x={x}:"
        f"y={y}"
        + (f":{extra}" if extra else "")
    )


def create_text_files(text_dir: Path, card_id: str, blocks: dict) -> Dict[str, Path]:
    files: Dict[str, Path] = {}
    for key, value in blocks.items():
        path = text_dir / f"{card_id}_{key}.txt"
        write_text(path, value)
        files[key] = path
    return files


def build_segment_filters(fontfile: Path, textfiles: Dict[str, Path], palette: dict, duration: float, index: int, total: int) -> str:
    progress_width = max(40, round(872 * index / max(total, 1)))
    fade_out_start = max(0.1, duration - 0.25)
    filters = [
        f"drawbox=x=72:y=120:w=936:h=1680:color={palette['panel']}:t=fill",
        f"drawbox=x=72:y=120:w=18:h=1680:color={palette['accent']}:t=fill",
        f"drawbox=x=104:y=170:w=340:h=58:color={palette['accent']}:t=fill",
        text_filter(fontfile, textfiles["header"], 30, 126, 182, color="0x08111b"),
        text_filter(fontfile, textfiles["counter"], 28, 866, 182, color=palette["muted"]),
        text_filter(fontfile, textfiles["title"], 64, 104, 308, extra="line_spacing=18"),
        text_filter(fontfile, textfiles["company_label"], 28, 104, 616, color=palette["muted"]),
        text_filter(fontfile, textfiles["company"], 42, 104, 662, extra="line_spacing=10"),
        f"drawbox=x=104:y=772:w=832:h=190:color={palette['accent_soft']}:t=fill",
        text_filter(fontfile, textfiles["pay_label"], 28, 136, 804, color=palette["muted"]),
        text_filter(fontfile, textfiles["pay"], 74, 136, 842, color=palette["accent"], extra="line_spacing=10"),
        f"drawbox=x=104:y=1016:w=260:h=128:color=white@0.06:t=fill",
        f"drawbox=x=390:y=1016:w=260:h=128:color=white@0.06:t=fill",
        f"drawbox=x=676:y=1016:w=260:h=128:color=white@0.06:t=fill",
        text_filter(fontfile, textfiles["area_label"], 24, 132, 1048, color=palette["muted"]),
        text_filter(fontfile, textfiles["area_value"], 36, 132, 1084, extra="line_spacing=8"),
        text_filter(fontfile, textfiles["time_label"], 24, 418, 1048, color=palette["muted"]),
        text_filter(fontfile, textfiles["time_value"], 36, 418, 1084, extra="line_spacing=8"),
        text_filter(fontfile, textfiles["posted_label"], 24, 704, 1048, color=palette["muted"]),
        text_filter(fontfile, textfiles["posted_value"], 36, 704, 1084, extra="line_spacing=8"),
        f"drawbox=x=104:y=1204:w=832:h=360:color=white@0.05:t=fill",
        text_filter(fontfile, textfiles["parts_label"], 28, 136, 1248, color=palette["muted"]),
        text_filter(fontfile, textfiles["parts_value"], 38, 136, 1290, extra="line_spacing=12"),
        text_filter(fontfile, textfiles["period_label"], 28, 136, 1398, color=palette["muted"]),
        text_filter(fontfile, textfiles["period_value"], 38, 136, 1440, extra="line_spacing=12"),
        text_filter(fontfile, textfiles["id_value"], 28, 104, 1640, color=palette["muted"], extra="line_spacing=10"),
        f"drawbox=x=104:y=1708:w=872:h=8:color=white@0.12:t=fill",
        f"drawbox=x=104:y=1708:w={progress_width}:h=8:color={palette['accent']}:t=fill",
        text_filter(fontfile, textfiles["footer"], 26, 104, 1746, color=palette["muted"]),
        "fade=t=in:st=0:d=0.14",
        f"fade=t=out:st={fade_out_start:.3f}:d=0.18",
        "format=yuv420p",
    ]
    return ",".join(filters)


def render_segment(
    job: dict,
    index: int,
    total: int,
    outdir: Path,
    fontfile: Path,
    duration: float,
    fps: int,
) -> Path:
    segments_dir = ensure_directory(outdir / "segments")
    text_dir = ensure_directory(outdir / "segment_text")
    segment_path = segments_dir / f"{index:03d}_{job['recruit_no']}.mp4"
    palette = PALETTES[(index - 1) % len(PALETTES)]
    card_id = f"{index:03d}_{job['recruit_no']}"
    blocks = make_card_blocks(job, index=index, total=total)
    textfiles = create_text_files(text_dir, card_id=card_id, blocks=blocks)
    filters = build_segment_filters(
        fontfile=fontfile,
        textfiles=textfiles,
        palette=palette,
        duration=duration,
        index=index,
        total=total,
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={palette['bg']}:s={WIDTH}x{HEIGHT}:d={duration:.3f}:r={fps}",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=channel_layout=stereo:sample_rate={AUDIO_SAMPLE_RATE}",
        "-vf",
        filters,
        "-r",
        str(fps),
        "-c:v",
        SEGMENT_CODEC,
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        SEGMENT_AUDIO_CODEC,
        "-shortest",
        "-movflags",
        "+faststart",
        str(segment_path),
    ]
    run_command(cmd)
    return segment_path


def concat_segments(segment_paths: List[Path], output_path: Path) -> None:
    concat_path = output_path.parent / "segments.txt"
    lines = [f"file {shlex.quote(str(path.resolve()))}" for path in segment_paths]
    write_text(concat_path, "\n".join(lines))
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    run_command(cmd)


def load_jobs_json(path: Path) -> Tuple[List[dict], dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload, {}
    jobs = payload.get("jobs", [])
    if not isinstance(jobs, list):
        raise SystemExit("jobs.json 형식이 올바르지 않습니다. jobs 배열이 필요합니다.")
    return jobs, payload


def resolve_output_dir(path_arg: Optional[str]) -> Path:
    if path_arg:
        return Path(path_arg).resolve()
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("projects").resolve() / f"albamon_cards_{stamp}"


def validate_fontfile(path_arg: str) -> Path:
    path = Path(path_arg).expanduser().resolve()
    if not path.exists():
        raise SystemExit(f"폰트 파일이 없습니다: {path}")
    return path


def handle_fetch(args: argparse.Namespace) -> Path:
    outdir = resolve_output_dir(args.outdir)
    ensure_directory(outdir)
    jobs, pages, total_count_estimate = fetch_jobs(
        max_pages=args.max_pages,
        max_items=args.max_items,
        search_period=args.search_period,
        sort_type=args.sort_type,
        include_keywords=args.keyword,
        exclude_keywords=args.exclude_keyword,
    )
    if not jobs:
        raise SystemExit("조건에 맞는 공고를 찾지 못했습니다.")

    payload = {
        "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
        "source": {
            "listing_url": LISTING_URL,
            "search_period_type": args.search_period,
            "sort_type": args.sort_type,
        },
        "filters": {
            "include_keywords": args.keyword,
            "exclude_keywords": args.exclude_keyword,
            "max_pages": args.max_pages,
            "max_items": args.max_items,
        },
        "page_count": len(pages),
        "total_count_estimate": total_count_estimate,
        "job_count": len(jobs),
        "pages": pages,
        "jobs": jobs,
    }
    jobs_json = outdir / "jobs.json"
    write_json(jobs_json, payload)
    write_text(outdir / "selected_jobs.txt", build_summary_text(jobs))
    report_path = write_browser_report(outdir=outdir, jobs_json_path=jobs_json, payload=payload)
    print(f"공고 저장: {jobs_json}")
    print(f"카드 리포트: {report_path}")
    print(f"선택 수: {len(jobs)}개 (추정 전체 {total_count_estimate:,}개)")
    return jobs_json


def handle_render(args: argparse.Namespace) -> Path:
    jobs_json = Path(args.jobs_json).resolve()
    if not jobs_json.exists():
        raise SystemExit(f"jobs.json 파일이 없습니다: {jobs_json}")
    jobs, metadata = load_jobs_json(jobs_json)
    if not jobs:
        raise SystemExit("렌더할 공고가 없습니다.")

    outdir = Path(args.outdir).resolve() if args.outdir else jobs_json.parent
    ensure_directory(outdir)
    fontfile = validate_fontfile(args.fontfile)

    filter_context = build_filter_context(args)
    filtered_jobs = apply_job_filters(jobs, filter_context)
    selected_jobs = filtered_jobs[: args.max_items] if args.max_items else filtered_jobs
    if not selected_jobs:
        raise SystemExit("렌더할 공고가 없습니다. 필터나 max-items를 확인하세요.")

    selected_payload = {
        "rendered_at": dt.datetime.now().isoformat(timespec="seconds"),
        "source_jobs_json_path": str(jobs_json),
        "filter_context": filter_context,
        "job_count": len(selected_jobs),
        "jobs": selected_jobs,
    }
    write_json(outdir / "rendered_jobs.json", selected_payload)
    write_text(outdir / "selected_jobs.txt", build_summary_text(selected_jobs))

    segment_paths: List[Path] = []
    for index, job in enumerate(selected_jobs, start=1):
        print(f"[{index}/{len(selected_jobs)}] 카드 렌더링: {job['title']}")
        segment_paths.append(
            render_segment(
                job=job,
                index=index,
                total=len(selected_jobs),
                outdir=outdir,
                fontfile=fontfile,
                duration=args.segment_duration,
                fps=args.fps,
            )
        )

    output_path = outdir / "albamon_recent_cards.mp4"
    concat_segments(segment_paths, output_path)
    render_info = {
        "rendered_at": dt.datetime.now().isoformat(timespec="seconds"),
        "fontfile": str(fontfile),
        "segment_duration_sec": args.segment_duration,
        "fps": args.fps,
        "item_count": len(selected_jobs),
        "jobs_json": str(jobs_json),
        "video": str(output_path),
        "source": metadata.get("source", {}),
        "filter_context": filter_context,
    }
    write_json(outdir / "render_info.json", render_info)
    print(f"영상 출력: {output_path}")
    return output_path


def handle_build(args: argparse.Namespace) -> Path:
    outdir = resolve_output_dir(args.outdir)
    ensure_directory(outdir)

    fetch_args = argparse.Namespace(
        outdir=str(outdir),
        max_pages=args.max_pages,
        max_items=args.max_items,
        search_period=args.search_period,
        sort_type=args.sort_type,
        keyword=args.keyword,
        exclude_keyword=args.exclude_keyword,
    )
    jobs_json = handle_fetch(fetch_args)

    render_args = argparse.Namespace(
        jobs_json=str(jobs_json),
        outdir=str(outdir),
        fontfile=args.fontfile,
        segment_duration=args.segment_duration,
        fps=args.fps,
        max_items=args.max_items,
        query=args.query,
        exclude_query=args.exclude_query,
        area=args.area,
        company=args.company,
        pay_type=args.pay_type,
        part=args.part,
        job_id=args.job_id,
    )
    return handle_render(render_args)


def add_render_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--query", help="통합 검색 필터")
    parser.add_argument("--exclude-query", help="제외 검색 필터")
    parser.add_argument("--area", help="지역 필터 (예: 서울, 경기, 재택근무)")
    parser.add_argument("--company", help="회사명 필터")
    parser.add_argument("--pay-type", help="급여 타입 필터 (예: 시급, 월급)")
    parser.add_argument("--part", help="직무 필터 (예: 바리스타, 편의점)")
    parser.add_argument("--job-id", action="append", default=[], help="특정 공고 ID만 렌더 (여러 번 지정 가능)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="알바몬 목록 메타데이터 기반 카드형 쇼츠 빌더",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_parser = subparsers.add_parser("fetch", help="최근 3일 공고 메타데이터 수집", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    fetch_parser.add_argument("--outdir", help="출력 디렉터리 (없으면 projects/albamon_cards_타임스탬프)")
    fetch_parser.add_argument("--max-pages", type=int, default=5, help="최대 수집 페이지 수")
    fetch_parser.add_argument("--max-items", type=int, default=30, help="최대 저장 공고 수")
    fetch_parser.add_argument("--search-period", default=DEFAULT_SEARCH_PERIOD, help="등록일 필터 코드")
    fetch_parser.add_argument("--sort-type", default=DEFAULT_SORT_TYPE, help="정렬 코드")
    fetch_parser.add_argument("--keyword", action="append", default=[], help="수집 단계 포함 키워드 (여러 번 지정 가능)")
    fetch_parser.add_argument("--exclude-keyword", action="append", default=[], help="수집 단계 제외 키워드 (여러 번 지정 가능)")
    fetch_parser.set_defaults(func=handle_fetch)

    render_parser = subparsers.add_parser("render", help="수집된 jobs.json으로 카드형 쇼츠 렌더", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    render_parser.add_argument("--jobs-json", required=True, help="fetch 단계에서 생성된 jobs.json 또는 필터된 JSON 경로")
    render_parser.add_argument("--outdir", help="렌더 출력 디렉터리 (기본: jobs.json 부모 폴더)")
    render_parser.add_argument("--fontfile", default=DEFAULT_FONTFILE, help="drawtext용 폰트 파일")
    render_parser.add_argument("--segment-duration", type=float, default=1.0, help="카드 1장당 길이(초)")
    render_parser.add_argument("--fps", type=int, default=FPS, help="출력 fps")
    render_parser.add_argument("--max-items", type=int, default=0, help="필터 결과 중 앞에서부터 일부만 렌더 (0이면 전체)")
    add_render_filters(render_parser)
    render_parser.set_defaults(func=handle_render)

    build_parser = subparsers.add_parser("build", help="수집 + 리포트 + 렌더 한번에 실행", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    build_parser.add_argument("--outdir", help="출력 디렉터리 (없으면 projects/albamon_cards_타임스탬프)")
    build_parser.add_argument("--max-pages", type=int, default=5, help="최대 수집 페이지 수")
    build_parser.add_argument("--max-items", type=int, default=20, help="최대 저장 및 렌더 공고 수")
    build_parser.add_argument("--search-period", default=DEFAULT_SEARCH_PERIOD, help="등록일 필터 코드")
    build_parser.add_argument("--sort-type", default=DEFAULT_SORT_TYPE, help="정렬 코드")
    build_parser.add_argument("--keyword", action="append", default=[], help="수집 단계 포함 키워드 (여러 번 지정 가능)")
    build_parser.add_argument("--exclude-keyword", action="append", default=[], help="수집 단계 제외 키워드 (여러 번 지정 가능)")
    build_parser.add_argument("--fontfile", default=DEFAULT_FONTFILE, help="drawtext용 폰트 파일")
    build_parser.add_argument("--segment-duration", type=float, default=1.0, help="카드 1장당 길이(초)")
    build_parser.add_argument("--fps", type=int, default=FPS, help="출력 fps")
    add_render_filters(build_parser)
    build_parser.set_defaults(func=handle_build)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
