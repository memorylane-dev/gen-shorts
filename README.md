# gshorts

YouTube 영상에서 쇼츠를 만드는 CLI 파이프라인.
영상 다운로드 → 자막 추출 → 구간 분석 → 크롭/폰트 확인 → 최종 생성까지 7단계.

---

## 사전 준비

```bash
# yt-dlp
brew install yt-dlp

# ffmpeg (drawtext/subtitles 필터 포함)
brew tap homebrew-ffmpeg/ffmpeg
brew install homebrew-ffmpeg/ffmpeg/ffmpeg

# Python 가상환경 (Apple Silicon)
python3 -m venv .venv
source .venv/bin/activate
pip install mlx-whisper deep-translator
```

**중요: 모든 Python 스크립트는 반드시 `.venv` 환경에서 실행해야 한다.**
```bash
source .venv/bin/activate  # 매 세션 시작 시 활성화
```

---

## 워크플로우

```
1. 다운로드         → 영상/오디오/썸네일 받기
2. 자막 추출        → Whisper로 SRT/TXT 생성
3. 구간 분석        → 오디오 피크 / 키워드 / 직접 검색
                      ⛔ 사용자 확인: 어떤 기준으로 뽑을지 선택
4. 구간 선정        → clips.txt 작성 (크롭 범위 없이)
                      ⛔ 사용자 확인: 클립 후보 목록 + 클립별 자막 내용 승인
4b. 자막 검토       → 클립별 자막 추출 (번역 전 오탈자/인식 오류 확인)
                      ⛔ 사용자 확인: 자막 내용 승인 후 번역 진행
5. 크롭 미리보기    → 기준선 그리드 또는 LEFT/CENTER/RIGHT 비교
                      ⛔ 사용자 확인: 각 클립별 크롭 범위 지정 (예: "1번은 2~6, 나머지 1~9")
6. 폰트 미리보기    → 폰트별 비교 이미지 생성
                      ⛔ 사용자 확인: 폰트 선택 또는 외부 폰트 추가
6b. 자막 위치 확인  → 실제 영상에서 자막 위치 프리뷰
                      ⛔ 사용자 확인: 자막 위치·크기 승인 (MarginV 조정)
7. 자막 번역        → 한국어 SRT → 영어/스페인어 SRT
8. 쇼츠 생성        → 클립별 4개 버전 (자막없음/ko/en/es)
```

**⛔ 표시된 단계는 반드시 사용자 확인을 받은 후 다음 단계로 진행해야 한다.**
**절대로 사용자 확인 없이 다음 단계로 넘어가지 말 것.**
**이전 영상에서 같은 설정을 사용했더라도 매번 확인을 받아야 한다. "이전과 동일" 판단을 임의로 하지 말 것.**

## Single Short CLI (Beta)

기존 `01~08` 스크립트는 그대로 유지하면서, **한 번에 short 하나를 spec으로 관리하는 새 CLI**를 추가했다.
앞으로는 `clips.txt` 여러 줄 대신 `short.json` 하나를 기준으로 빌드할 수 있다.

- short 하나 = spec 파일 하나
- 여러 개를 만들고 싶으면 spec 파일을 여러 개 두면 된다
- 번역 target은 언어(`en`, `es`)가 아니라 국가/로캘(`KR`, `US`, `MX`) 기준으로 선택한다
- 같은 언어를 쓰는 국가가 여러 개여도 출력 폴더는 국가별로 분리된다
- spec 안에 `publish.title`, `publish.description`, `publish.tags` 같은 업로드 메타데이터를 함께 저장할 수 있다

예시 spec: [`short.example.json`](/Users/shlee/Developments/gen-shorts/short.example.json)

지원 target 보기:

```bash
python3 ./scripts/gshorts.py list-targets
```

지원 preset 보기:

```bash
python3 ./scripts/gshorts.py list-presets
```

interactive spec 생성:

```bash
python3 ./scripts/gshorts.py init-short --project-dir "projects/프로젝트명"
```

brief 한 줄로 spec 초안 생성:

```bash
python3 ./scripts/gshorts.py draft-short \
  --project-dir "projects/프로젝트명" \
  --brief "위아래 분할로 로키 드립이랑 성대모사를 번갈아 보여주고 미국/멕시코용 자막과 자막없는 버전도 같이 만들어줘"
```

clip 후보 보기:

```bash
python3 ./scripts/gshorts.py list-clips \
  --project-dir "projects/프로젝트명" \
  --brief "로키 성대모사 위주로"
```

spec 요약 보기:

```bash
python3 ./scripts/gshorts.py describe-short \
  --spec "projects/프로젝트명/shorts/my_short.json"
```

`init-short`가 도와주는 것:

- 프로젝트 안의 `clips.txt` 후보를 자동 탐색
- `clip_subtitles_review.txt`가 있으면 대사 미리보기와 함께 clip 선택
- 자연어 brief를 먼저 받아 preset / target / clip 후보를 추천
- preset 설명을 보여주며 선택
- 국가/로캘 target을 번호 또는 코드로 선택
- upload title / description / tags / notes를 spec에 저장

`draft-short`가 해주는 것:

- brief 문장에서 split/stitch/headline 같은 편집 의도 추론
- country/locale target 추천
- clip 후보 관련도 점수 기반 추천
- spec 초안을 바로 파일로 저장

spec 하나 빌드:

```bash
python3 ./scripts/gshorts.py build-short \
  --spec "projects/프로젝트명/shorts/my_short.json"
```

요약을 이미 확인했다면:

```bash
python3 ./scripts/gshorts.py build-short \
  --spec "projects/프로젝트명/shorts/my_short.json" \
  --yes
```

`build-short` 동작:

- 빌드 전에 short 요약과 예상 길이를 항상 보여주고 확인을 받음
- 예상 길이가 길면 warning을 표시
- short spec에서 클립/포맷/runtime 파일을 자동 생성
- 필요한 번역 자막이 이미 있으면 재사용
- 필요한 번역 자막이 없으면 누락된 언어만 생성
- 최종 렌더는 내부적으로 `08_make_shorts.py`를 호출
- `_runtime/resolved_short.json`에 실제 빌드에 사용된 resolved manifest를 저장

샘플 spec:

- [`sample_short.json`](/Users/shlee/Developments/gen-shorts/projects/인생은%20어떤%20여행일까,%20질문/sample_short.json)

spec의 주요 필드:

- `short_id`: short 고유 id
- `source_video`, `source_srt`: 원본 영상/자막
- `targets`: `KR`, `US`, `MX` 같은 국가/로캘 target 목록
- `brief`: 자연어 편집 요청 원문
- `publish`: 업로드용 title / description / tags / notes
- `review`: 확인 필요 여부, 예상 길이, warning
- `clip`: 메인 clip start / duration / crop
- `format`: preset, on-screen title, secondary clip 정보

### 링크를 줄 때 같이 주면 좋은 정보

유튜브 링크만 있어도 시작할 수 있지만, 아래를 함께 주면 추천 품질이 좋아진다.

- 원하는 포맷: 예) `위아래 분할`, `좌우 분할`, `이어붙이기`, `명대사 카드형`
- 타겟 국가: 예) `KR`, `US`, `MX`
- 원하는 톤: 예) `웃긴 장면`, `명대사`, `브랜드형`
- 꼭 살리고 싶은 키워드/인물/장면
- 피하고 싶은 요소: 예) `너무 긴 setup`, `과한 자막`, `영문 제외`

시스템은 먼저 brief를 바탕으로 spec 초안을 만들고, **클립/포맷/타겟/예상 길이 확인 단계**를 거친 뒤 렌더하도록 설계한다.

---

### 1. 다운로드

```bash
./scripts/01_download.sh "https://www.youtube.com/watch?v=VIDEO_ID" ./workspace
```

비디오(.mp4), 오디오(.m4a), 썸네일(.webp) 다운로드.

### 2. 자막 추출

```bash
./scripts/02_transcribe.sh "workspace/영상_audio.m4a" "workspace/subtitle"
```

- `subtitle.srt` — 타임스탬프 포함 SRT 자막
- `subtitle.txt` — `[MM:SS] 텍스트` 형태 (사람이 읽기 편한 형식)

1시간 영상 기준 약 10분 소요 (Apple Silicon).

### 3. 구간 분석

어떤 기준으로 쇼츠 구간을 뽑을지 결정한다.

```bash
# 대화형 모드 — 기준을 선택하며 탐색
python3 ./scripts/03_analyze.py \
  --transcript "workspace/subtitle.txt" \
  --audio "workspace/영상_audio.m4a"

# 전체 분석 한번에
python3 ./scripts/03_analyze.py \
  --transcript "workspace/subtitle.txt" \
  --audio "workspace/영상_audio.m4a" \
  --mode all

# 특정 키워드 검색
python3 ./scripts/03_analyze.py \
  --transcript "workspace/subtitle.txt" \
  --mode keyword \
  --keywords "다이어트,내기,100만원"
```

| 기준 | 설명 | 적합한 상황 |
|---|---|---|
| `audio_peaks` | 소리가 갑자기 커지는 구간 | 웃음, 리액션, 박수 |
| `funny` | 웃음/놀람 키워드 자동 검색 | 재밌는 대사 |
| `keyword` | 특정 단어 포함 구간 | 주제/인물 언급 |
| `all` | 전부 실행 | 전체 파악 |

### 4. 구간 선정

분석 결과를 바탕으로 `clips.txt` 작성.

```
# 시작시간,길이,출력파일명,크롭범위
00:01:50,00:00:35,1_clip.mp4,2~8       ← 기준선 2~8 사이 크롭
00:06:05,00:00:40,2_clip.mp4,3~7       ← 기준선 3~7 사이 크롭
00:09:08,00:00:40,3_clip.mp4           ← 생략 시 9:16 중앙 크롭
00:08:07,00:00:38,4_clip.mp4,+300      ← 기존 오프셋 방식도 호환
```

4번째 컬럼 형식:
- `2~8` — 기준선 번호 범위 (Step 5에서 확인)
- `+300` / `-500` — 9:16 중앙 기준 오프셋
- 생략 — 9:16 중앙 크롭

9:16 비율에 안 맞는 범위는 위아래 검은 여백이 자동 추가됨.

빈 템플릿: `clips.example.txt` 참고.

### 4b. 클립별 자막 검토

```bash
python3 ./scripts/04b_extract_clip_subs.py \
  --srt "workspace/subtitle.srt" \
  --clips clips.txt \
  --outdir previews
```

각 클립에 해당하는 자막을 추출하여 개별 파일 + 전체 요약 파일(`clip_subtitles_review.txt`)을 생성.
번역 전에 자막 내용(오탈자, Whisper 인식 오류 등)을 검토·수정할 수 있다.

### 5. 크롭 미리보기

**기준선 그리드 방식** (추천):

```bash
python3 ./scripts/05b_preview_gridlines.py \
  --input "workspace/영상.mp4" \
  --clips clips.txt \
  --outdir previews \
  --divisions 10
```

화면을 10등분한 번호 매긴 세로 기준선을 표시. "2번~8번 사이로 잘라줘" 식으로 범위 지정.

`--suggest` 옵션을 추가하면 피부색 기반 자동 크롭 범위 제안이 초록색으로 표시됨.
1인 샷에서는 정확도가 높고, 2인 이상에서는 참고용.

```bash
python3 ./scripts/05b_preview_gridlines.py \
  --input "workspace/영상.mp4" \
  --clips clips.txt \
  --outdir previews \
  --divisions 10 \
  --suggest
```

**LEFT/CENTER/RIGHT 비교 방식**:

```bash
python3 ./scripts/05_preview_crop.py \
  --input "workspace/영상.mp4" \
  --clips clips.txt \
  --outdir previews
```

각 클립마다 LEFT/CENTER/RIGHT 3가지 크롭 비교 시트 생성.

두 명이 양쪽에 앉은 장면이면 누구를 중심으로 잡을지 한눈에 판단 가능.

**조정**: `clips.txt`의 오프셋 수정 → 미리보기 재생성 → 확인.

### 6. 폰트 미리보기

```bash
python3 ./scripts/06_preview_fonts.py \
  --input "workspace/영상.mp4" \
  --clips clips.txt \
  --srt "workspace/subtitle.srt" \
  --sizes 16,20,24,32 \
  --outdir previews
```

각 폰트 후보로 자막을 입힌 프레임 이미지 생성. 기본 비교 크기는 `16,20,24,32`.
현재 스크립트는 `drawtext` 기반으로 폰트를 직접 지정하므로, macOS의 폰트 fallback 영향 없이 실제 폰트 차이를 확인할 수 있다.

**폰트 적용**: `08_make_shorts.py` 상단의 `SUBTITLE_FONT`, `SUBTITLE_SIZE_RATIO`, `SUBTITLE_Y_RATIO`, `_SUBTITLE_BASE`로 조정.

**외부 폰트 추가**:
1. `.ttf` 또는 `.otf` 파일 준비
2. 시스템에 설치한 뒤 `06_preview_fonts.py`의 `FONT_CANDIDATES` 리스트에 추가:
   ```python
   ("MyFont", "폰트 패밀리명"),
   ```
3. 미리보기 재생성하여 비교

### 6b. 자막 위치 미리보기

폰트 선택 후, 실제 영상에서 자막 위치를 확인하는 단계.
크롭 비율에 따라 검은 여백 크기가 달라지므로 자막 위치(MarginV)가 적절한지 반드시 확인해야 한다.

```bash
# 자막이 있는 시점의 프레임을 추출하여 확인
ffmpeg -y -i "workspace/영상.mp4" -ss 00:14:20 -frames:v 1 \
  -vf "crop=...,scale=...,pad=...,subtitles=subtitle.srt:force_style='...'" \
  -q:v 2 previews/subtitle_position_test.jpg
```

**주의**: `-ss`를 `-i` 뒤에 배치해야 자막 타임스탬프가 매칭됨.
`-ss`를 `-i` 앞에 두면 출력 타임스탬프가 0부터 시작하여 자막이 표시되지 않음.

⛔ **사용자 확인**: 자막 위치·크기가 적절한지 확인. 필요 시 `SUBTITLE_SIZE_RATIO`, `SUBTITLE_Y_RATIO`, `_SUBTITLE_BASE` 조정.

### 7. 자막 번역

```bash
# 클립 구간만 번역 (기본 — 빠르고 필요한 부분만)
source .venv/bin/activate
python3 ./scripts/07_translate.py \
  --srt "workspace/subtitle.srt" \
  --clips clips.txt \
  --langs "en,es"
```

**반드시 `--clips`를 지정하여 클립 구간의 자막만 번역한다.**
전체 SRT를 번역하면 불필요하게 느리다 (2000+ 세그먼트 vs 클립 구간 100개 이하).

한국어 SRT를 영어/스페인어로 번역하여 `subtitle_en.srt`, `subtitle_es.srt` 생성.
Google Translate 기반 (deep-translator). 다른 언어도 추가 가능: `ja`, `zh-CN`, `fr`, `de`, `pt` 등.

### 8. 쇼츠 생성

```bash
python3 ./scripts/08_make_shorts.py \
  --input "workspace/영상.mp4" \
  --clips clips.txt \
  --srtdir workspace/ \
  --format-config formats.json \
  --outdir output \
  --workers 4
```

각 클립별 **4개 버전** 생성:

| 폴더 | 내용 |
|---|---|
| `output/nosub/` | 자막 없음 |
| `output/ko/` | 한국어 자막 |
| `output/en/` | 영어 자막 |
| `output/es/` | 스페인어 자막 |

자막 스타일은 `08_make_shorts.py` 상단의 `SUBTITLE_FONT`, `SUBTITLE_SIZE_RATIO`, `SUBTITLE_Y_RATIO`, `_SUBTITLE_BASE`로 조정.

### 8a. 포맷 프리셋 (선택)

쇼츠의 "포맷"은 단순 효과 모음이 아니라, **화면 구성 + 제목/브랜드 위치 + 자막 안전영역**의 조합이다.
이 프로젝트에서는 이를 `format preset`으로 분리하여, 같은 클립도 다른 포맷으로 렌더링할 수 있게 확장했다.

현재 렌더러가 바로 지원하는 preset:

| preset | 용도 |
|---|---|
| `clean_fullbleed` | 기본형. 영상만 꽉 채우고 자막만 표시 |
| `headline_fullbleed` | 상단 제목 바 + 전체 클립 |
| `branded_header_logo` | 상단 제목 + 하단 브랜드 영역(로고 또는 텍스트 pill) |
| `quote_focus` | 큰 제목 카드형. 명대사/강한 한 줄용 |
| `reaction_duet` | 좌우 분할 반응형. 메인 클립 + 보조 클립 동시 재생 |
| `comparison_split` | A/B 비교형. 상하 분할 + 라벨 표시 |
| `stitch_then_punchline` | 앞 클립 후 뒤 클립 연결형 |
| `alternating_spotlight` | 상하 분할 순차형. 한 패널이 재생될 때 다른 패널은 freeze |

다음에 확장하기 좋은 taxonomy:

- `freeze_emphasis` — 중간 정지 + 확대/강조형
- `alternating_spotlight` — 분할 상태에서 번갈아 강조형

설정 파일 예시: [`formats.example.json`](/Users/shlee/Developments/gen-shorts/formats.example.json)

```json
{
  "defaults": {
    "preset": "headline_fullbleed",
    "brand_text": "WOWSAN TV"
  },
  "clips": [
    {
      "name": "1_첫번째클립.mp4",
      "preset": "branded_header_logo",
      "title": "대표 달더니... ㄷㄷ"
    },
    {
      "name": "2_두번째클립.mp4",
      "preset": "reaction_duet",
      "title": "반응 미쳤다",
      "secondary_ss": "00:19:02"
    },
    {
      "name": "3_세번째클립.mp4",
      "preset": "comparison_split",
      "title": "둘의 반응 비교",
      "secondary_input": "./source/다른영상.mp4",
      "secondary_ss": "00:00:42",
      "secondary_t": "00:00:18",
      "primary_label": "HOST",
      "secondary_label": "GUEST"
    },
    {
      "name": "4_네번째클립.mp4",
      "preset": "stitch_then_punchline",
      "title": "앞은 빌드업, 뒤가 펀치라인",
      "secondary_ss": "00:47:08",
      "secondary_t": "00:00:06"
    }
  ]
}
```

추가 규칙:

- `--format-config`는 선택 사항이다. 생략하면 모든 클립이 `clean_fullbleed`로 렌더된다.
- `logo_path`를 지정하면 하단 브랜드 pill 대신 실제 로고 이미지를 오버레이한다.
- `logo_path`가 상대경로면 JSON 파일 기준으로 해석된다.
- `secondary_input`가 없으면 기본적으로 현재 `--input` 영상을 다시 사용한다. 즉 같은 원본 안의 다른 타임코드끼리 `duet/split/stitch`를 만들 수 있다.
- `secondary_ss`를 생략하면 메인 클립의 시작 시각을 재사용한다.
- `secondary_t`를 생략하면 메인 클립 길이(`clips.txt`의 2번째 컬럼)를 재사용한다.
- `reaction_duet`, `comparison_split`은 출력 길이가 메인 클립 길이와 같다.
- `stitch_then_punchline`은 출력 길이가 `메인 clip 길이 + secondary_t`가 된다.
- `alternating_spotlight`은 출력 길이가 `메인 clip 길이 + secondary_t`가 되며, 전반부엔 primary만 재생되고 후반부엔 secondary만 재생된다.
- `comparison_split`은 기본값으로 상하 분할 + `A/B` 라벨이 켜져 있다. `primary_label`, `secondary_label`로 바꿀 수 있다.
- 같은 구간을 여러 포맷으로 뽑고 싶으면 `clips.txt`에 출력 파일명을 다르게 두 줄 넣고, `formats.json`에서 각각 다른 preset을 지정하면 된다.

자주 쓰는 키:

| 키 | 설명 |
|---|---|
| `preset` | 사용할 포맷 이름 |
| `title` | 상단 제목 텍스트 |
| `brand_text` | 하단 브랜드 텍스트 |
| `logo_path` | 하단 로고 이미지 경로 |
| `secondary_input` | 두 번째 영상 파일 경로 |
| `secondary_ss` | 두 번째 영상 시작 시각 |
| `secondary_t` | 두 번째 영상 길이 |
| `secondary_crop` | 두 번째 영상 크롭 스펙 (`2~8`, `+300` 등) |
| `primary_label` / `secondary_label` | split 포맷 패널 라벨 |

### (부록) 영상 단순 자르기

재인코딩 없이 구간만 빠르게 잘라내기:

```bash
./scripts/cut_video.sh "영상.mp4" "04:50" "00:20:00" "output.mp4"
```

---

## 와우산TV 채널 쇼츠 분석

실제 와우산TV(@wowsantv) 쇼츠 85개를 분석한 결과. 클립 선정 시 참고.

### 길이

- **인기작(조회수 상위 10개) 평균: 22초**
- 조회수 1위(29K): 15초 — 짧을수록 조회수 높은 경향
- 중앙값: ~38초
- 60초 이상은 대체로 조회수 낮음

→ **15~30초를 목표로 클립 선정. 길어도 40초를 넘기지 않는다.**

### 제목

- 짧고 임팩트 있는 한 줄 (평균 12~15자)
- 말줄임표/이모티콘 활용: "대표달더니...ㄷㄷ", "흙흙 ㅜㅜ"
- 궁금증 유발형: "장들레 불효 논란", "공부는 잘했지만 수능은 못봄"
- **해시태그는 제목에 넣지 않는다** — 해시태그가 많으면 오히려 조회수 낮음
- 영어 버전은 별도 업로드 (같은 영상 한/영 2개)

### 조회수와 특징

| 조회수 | 특징 |
|--------|------|
| 20K+ | 짧음(15~30초), 제목 한 줄, 해시태그 없음, 감정 포인트 명확 |
| 5~10K | 중간 길이(20~45초), 구체적 제목 |
| 1~3K | 길거나(60초+), 해시태그 과다, 진지한 톤 |

### 클립 선정 기준 (이 분석에서 도출)

1. **감정 포인트 하나에 집중** — 한 클립에 여러 이야기보다 "이 한마디/이 순간"
2. **15~30초로 자른다** — 맥락 설명은 최소화, 핵심만
3. **제목은 대사/상황 그대로** — "삼행시실패" 보다 "렛...렛...렛..." 이 낫다
4. **영어 버전은 영어 제목으로 별도 업로드** — 자막만 바꾸는 것보다 효과적

---

## 프로젝트 구조

```
gshorts/
├── README.md
├── clips.example.txt               ← clips.txt 템플릿
├── formats.example.json            ← format preset 템플릿
├── scripts/                        ← 공용 스크립트
│   ├── 01_download.sh
│   ├── 02_transcribe.sh
│   ├── 03_analyze.py
│   ├── 04b_extract_clip_subs.py   ← 클립별 자막 추출 (번역 전 검토)
│   ├── 05_preview_crop.py          ← 크롭 미리보기 (LEFT/CENTER/RIGHT)
│   ├── 05b_preview_gridlines.py    ← 크롭 기준선 그리드 미리보기
│   ├── 06_preview_fonts.py
│   ├── 07_translate.py             ← 자막 번역 (ko → en, es)
│   ├── 08_make_shorts.py           ← 쇼츠 생성 (자유 크롭 + 4버전)
│   └── cut_video.sh
└── projects/                       ← 영상별 작업 폴더
    └── 프로젝트명/
        ├── source/                 ←   원본 영상/오디오/썸네일
        ├── clips.txt               ←   구간 목록
        ├── formats.json            ←   클립별 포맷/제목/브랜드 설정(선택)
        ├── subtitle.srt            ←   한국어 SRT
        ├── subtitle_en.srt         ←   영어 SRT
        ├── subtitle_es.srt         ←   스페인어 SRT
        ├── subtitle.txt            ←   읽기용 자막
        ├── previews/               ←   크롭/폰트 미리보기
        └── output/
            ├── nosub/              ←   자막 없음
            ├── ko/                 ←   한국어 자막
            ├── en/                 ←   영어 자막
            └── es/                 ←   스페인어 자막
```

Step 4(구간 선정)는 사용자가 `clips.txt`를 작성하는 단계이므로 별도 스크립트 없음.
새 영상 작업 시 `projects/` 아래에 폴더를 만들어 시작.
