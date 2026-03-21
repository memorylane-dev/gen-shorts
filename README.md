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

**폰트 적용**: `08_make_shorts.py` 상단의 `SUBTITLE_STYLE`에서 폰트 조정.

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

⛔ **사용자 확인**: 자막 위치·크기가 적절한지 확인. 필요 시 `SUBTITLE_STYLE`의 `MarginV`, `FontSize` 조정.

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

자막 스타일은 `08_make_shorts.py` 상단의 `SUBTITLE_STYLE` 상수로 조정 (ASS 형식).

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
