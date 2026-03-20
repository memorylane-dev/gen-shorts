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

# mlx-whisper (Apple Silicon)
python3 -m venv .venv
source .venv/bin/activate
pip install mlx-whisper
```

---

## 워크플로우

```
1. 다운로드        → 영상/오디오/썸네일 받기
2. 자막 추출       → Whisper로 SRT/TXT 생성
3. 구간 분석       → 오디오 피크 / 키워드 / 직접 검색
                     ⛔ 사용자 확인: 어떤 기준으로 뽑을지 선택
4. 구간 선정       → clips.txt 작성
5. 크롭 미리보기   → 기준선 그리드 또는 LEFT/CENTER/RIGHT 비교
                     ⛔ 사용자 확인: 크롭 범위 지정 (예: "2~8")
6. 폰트 미리보기   → 폰트별 비교 이미지 생성
                     ⛔ 사용자 확인: 폰트 선택 또는 외부 폰트 추가
7. 자막 번역       → 한국어 SRT → 영어/스페인어 SRT
8. 쇼츠 생성       → 클립별 4개 버전 (자막없음/ko/en/es)
```

**⛔ 표시된 단계는 반드시 사용자 확인을 받은 후 다음 단계로 진행해야 한다.**

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
  --outdir previews
```

각 폰트 후보로 자막을 입힌 프레임 이미지 생성. 비교 후 선택.

**폰트 적용**: `08_make_shorts.py` 상단의 `SUBTITLE_STYLE`에서 폰트 조정.

**외부 폰트 추가**:
1. `.ttf` 또는 `.otf` 파일 준비
2. `06_preview_fonts.py`의 `FONT_CANDIDATES` 리스트에 추가:
   ```python
   ("NanumGothicBold", "/경로/NanumGothicBold.ttf"),
   ```
3. 미리보기 재생성하여 비교

### 7. 자막 번역

```bash
python3 ./scripts/07_translate.py \
  --srt "workspace/subtitle.srt" \
  --langs "en,es"
```

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

## 프로젝트 구조

```
gshorts/
├── README.md
├── clips.example.txt               ← clips.txt 템플릿
├── scripts/                        ← 공용 스크립트
│   ├── 01_download.sh
│   ├── 02_transcribe.sh
│   ├── 03_analyze.py
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
