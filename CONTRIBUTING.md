# Contributing

이 문서는 `gshorts`의 커밋 규칙과 변경 단위 기준을 정리한다.

## Commit Convention

커밋 메시지는 아래 형식을 기본으로 한다.

```text
<type>(<scope>): <summary>
```

예시:

```text
feat(renderer): add image subtitle renderer
fix(subtitles): apply final fade to audio and overlays
docs(readme): document subtitle renderer selection rules
content(checkin-ep19): add localized short assets for 1_침묵해주세요
refactor(gshorts): split short review summary from build flow
```

## Types

이 프로젝트에서는 아래 type만 사용한다.

- `feat`: 사용자 가치가 생기는 기능 추가
- `fix`: 버그 수정, 회귀 방지, 렌더 안정화
- `refactor`: 동작 변화 없이 구조 개선
- `docs`: README, 가이드, 예제 spec 문서화
- `test`: 검증 코드, 스모크 테스트, 테스트 보강
- `chore`: 빌드/도구/정리 작업
- `content`: 특정 프로젝트의 short spec, 자막, preview, runtime asset 추가/수정

## Scope Rules

scope는 가능한 한 변경의 중심 축을 적는다.

- 엔진/파이프라인: `pipeline`, `renderer`, `subtitles`, `gshorts`, `formats`
- 문서: `readme`, `docs`
- 프로젝트 산출물: `checkin-ep19`, `wowsan-tv`, `project-<id>` 같이 사람이 알아볼 수 있는 프로젝트 단위

권장:

- `feat(renderer): add image subtitle renderer`
- `fix(pipeline): apply final fade to composite audio/video`
- `content(checkin-ep19): add localized short assets for 1_침묵해주세요`

비권장:

- `update`
- `작업함`
- `자막 수정 및 이것저것`
- `Add stuff`

## Summary Rules

- 영어 동사 원형(imperative mood)으로 시작한다.
- 72자 안팎으로 짧게 쓴다.
- 마침표를 붙이지 않는다.
- 구현 방식보다 결과를 우선 적는다.
- `and`로 두세 가지를 억지로 이어붙이지 않는다. 한 커밋에 주제가 둘 이상이면 커밋을 나눈다.

좋은 예:

- `fix(subtitles): resolve Jua font lookup in image renderer`
- `feat(pipeline): support configurable final fade timing`

나쁜 예:

- `fix a lot of subtitle issues and also rename files`
- `change fade`

## What Belongs In One Commit

원칙은 `한 커밋 = 한 의도(one intent)`다.

다음은 분리하는 것이 좋다.

1. 엔진 코드 변경과 프로젝트 산출물 추가
2. 범용 렌더러 수정과 특정 영상용 자막 문안 수정
3. 문서 수정과 기능 추가

추천 분리 예:

1. `feat(renderer): add image subtitle renderer`
2. `fix(pipeline): support configurable final fade timing`
3. `content(checkin-ep19): add localized short assets for 1_침묵해주세요`
4. `docs(readme): document renderer and fade configuration`

## This Repository's Preferred Pattern

실제로는 아래 두 패턴을 가장 많이 쓰게 된다.

### 1. 엔진/도구 변경

```text
feat(<scope>): <summary>
fix(<scope>): <summary>
refactor(<scope>): <summary>
docs(<scope>): <summary>
```

예:

- `feat(gshorts): add brief-driven short build flow`
- `fix(renderer): keep emoji and jp fallback in image subtitles`

### 2. 개별 쇼츠/프로젝트 산출물 변경

```text
content(<project-scope>): <summary>
```

예:

- `content(checkin-ep19): add reviewed subtitles for 1_침묵해주세요`
- `content(wowsan-tv): add clip candidates and preview subtitles`

## Before You Commit

커밋 전에 아래를 확인한다.

1. 이번 커밋이 `엔진 변경`인지 `콘텐츠 변경`인지 섞여 있지 않은가
2. scope가 너무 넓지 않은가
3. summary가 결과를 설명하는가
4. staged 파일이 의도한 범위만 포함하는가
5. 생성 산출물이 필요한 경우에만 포함했는가

## Current Recommendation

현재 staged 변경처럼 `렌더러/파이프라인 개선 + 특정 프로젝트 산출물 추가`가 함께 들어 있으면, 가장 좋은 방법은 두 커밋으로 나누는 것이다.

예:

1. `feat(renderer): add image subtitle rendering and final fade controls`
2. `content(checkin-ep19): add localized assets for 1_침묵해주세요`
