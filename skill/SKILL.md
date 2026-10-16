---
name: shopping-shorts-maker
description: 쇼핑 쇼츠(인스타 릴스/유튜브 쇼츠/틱톡) 자동 제작. 샤오홍슈·더우인·틱톡·유튜브 상품 영상 링크(또는 로컬 영상)를 받아 원본 다운로드 -> 한국어 영상 필터 -> 원본 자막 제거 -> 대본 작성 -> 무료 TTS -> 자막·효과음·광고표시 -> 렌더링 -> 썸네일 -> 설명글까지 만든다. 사용자가 "쇼핑쇼츠", "쇼핑 숏츠 만들어줘", 상품 영상 링크와 함께 "쇼츠로 만들어줘", "쿠팡 파트너스 영상" 등을 말하면 사용.
---

# 오토 쇼핑 쇼츠 (Auto Shopping Shorts)

엔진 위치: `__SSM_HOME__`
실행: `__SSM_HOME__\ssm.cmd <명령>` (PowerShell에서는 `& "__SSM_HOME__\ssm.cmd" <명령>`)
작업물: `__SSM_HOME__\projects\<프로젝트>\` (output\final.mp4, output\thumbnail.jpg, output\description.txt)

> 모든 대본·판단은 너(Claude Code/Codex)가 직접 한다. 별도 LLM API 키는 쓰지 않는다.
> analyze / clean / build 는 1~5분 걸릴 수 있다. 쉘 도구 타임아웃을 10분(600000ms)으로 주거나 백그라운드로 실행하고 완료를 확인한다.

## 사용자 경험 (4단계)
1. 사용자가 링크를 준다 (보통 1개). 너는 같은 상품의 비슷한 원본 3개를 자동으로 더 모은다 (1-2 단계).
2. 너는 원본 분석 결과를 보여주고 **대본 결(톤)을 고르게 한다**.
3. 자동으로 끝까지 만든다 (사용자는 기다림).
4. 결과를 보여주고, 수정 요청은 말로 받아 그 부분만 다시 만든다. 업로드는 사용자가 직접.

## 작업 순서

### 1) 프로젝트 만들고 원본 받기
```
ssm.cmd new <영문-프로젝트명> <링크1> [링크2 ...]
```
- 샤오홍슈/더우인이 실패하면 `--cookies-browser chrome` (또는 edge, whale) 을 붙여 다시 시도.
  - 그래도 안 되면 사용자에게 영상을 저장해 달라고 하고 로컬 파일 경로를 그대로 넣는다 (`ssm.cmd new <프로젝트> C:\경로\영상.mp4`).
- 원본 추가: `ssm.cmd add <프로젝트> <링크...>`

### 1-2) 비슷한 원본 3개 자동 수집 (기본으로 항상 실행)
한 원본만 쓰면 결과가 원본과 똑같아지므로, 같은 상품의 다른 영상 3개를 더 모아 섞는다.
1. 기준 원본 제목·콘택트시트를 보고 **상품을 중국어 검색어 2~3개로** 만든다 (상품명 + 형태/기능, 너무 일반적인 "好物推荐" 금지).
   예: 휴대용 전기포트 텀블러 -> `"便携式烧水杯" "电热水杯 旅行" "保温烧水杯"`
2. 실행:
```
ssm.cmd collect <프로젝트> --query "검색어1" "검색어2" --count 3
```
   - 유튜브에 재업로드된 더우인/샤오홍슈 상품 쇼츠를 검색 -> 길이(6~90초)·한글 제목 걸러냄 -> 상위 8개 다운로드
   - 같은 영상 재업로드(중복)·한글 영상은 자동 제외, 제목+화면 유사도 점수 상위 3개를 src 로 추가
   - --query 를 생략하면 기준 원본 제목의 해시태그로 자동 검색 (덜 정확)
3. **`analysis\collect_sheet.jpg` 를 직접 열어 확인** (1행 = 기준 원본, 초록 테두리 = 추가된 것, 빨간 = 탈락).
   - 다른 상품이 들어오면 `project.json` 에서 그 src 를 `"enabled": false` 하고
     `ssm.cmd collect <프로젝트> --query "더 구체적인 검색어" --count <부족한 개수>` 로 채운다.
   - 전부 다시: `--reset` 을 붙이면 이전 자동 수집분을 지우고 새로 모은다.
   - `collect_report.json` 에 후보별 점수와 탈락 사유가 있다. 빨간 후보 중 같은 상품이 있으면 `ssm.cmd add <프로젝트> <그 url>` 로 직접 추가해도 된다.
4. 사용자에게 "비슷한 원본 N개를 찾아 섞었다"고 한 줄로 보고한다 (비교 시트 이미지 경로 포함).

### 2) 분석 (한국어 필터 + 원본 자막 추출)
```
ssm.cmd analyze <프로젝트>
```
- `projects\<프로젝트>\analysis\report.json` 을 읽는다:
  - `korean_suspect=true` 인 원본은 자동 제외된다 (`excluded`). 한국 영상/한글 자막은 저작권 신고 위험이 커서 쓰지 않는다.
  - `original_subtitles` = 원본 중국어 자막(OCR). **상품 특징을 파악하는 핵심 자료**. 번역해서 사실만 대본에 쓴다.
  - `other_onscreen_text` = 제품 로고·버튼 글씨 등 (모델명, 브랜드 파악용).
- `analysis\src<N>_sheet.jpg` 콘택트시트 이미지를 **직접 열어 본다**: 상품이 무엇인지, 화면에 한글이 있는지, 원본끼리 같은 상품인지 확인. 다른 상품이면 `project.json`에서 그 원본의 `"enabled": false`.

### 3) 원본 자막 지우기 + 9:16 정규화
```
ssm.cmd clean <프로젝트>            # 기본 blur
ssm.cmd clean <프로젝트> --mode inpaint   # 배경이 단순하면 더 자연스러움
```
- 제품 로고·버튼 글씨는 지우지 않고 '자막처럼 생긴' 글씨만 지운다. 영어 캡션까지 지워야 하면 `config.override.json` 에 `{"clean":{"text_filter":"all"}}`.

### 4) 대본 결 고르기 -> 대본 작성
- `references/tones.md` 를 읽고, 사용자에게 결 6가지(공감형 꿀템 / 충격 반전형 / 비교·고발형 / 리스트형 / 상황극 / 순수 정보형)와 CTA 방식을 짧게 제시해 하나 고르게 한다.
  - 사용자가 "참고 영상 링크 + 이 결로" 를 주면 tones.md 하단 절차대로 분석해서 따라 쓴다.
  - 사용자가 "알아서" 라고 하면 1번 공감형 + 댓글 유도 CTA.
- `projects\<프로젝트>\script.json` 을 작성 (`ssm.cmd init-script <프로젝트>` 로 템플릿 생성 가능):
```json
{
  "tone": "공감형 꿀템",
  "lines": [
    {"text": "와, 출장 갈 때 *이거 하나* 챙기면 끝이네요.", "sfx": "whoosh"},
    {"text": "호텔 포트는 좀 찝찝한데 뜨거운 물은 꼭 필요하잖아요."},
    {"text": "온도를 *11단계*로 고를 수 있어요.", "clip": {"src": 0, "start": 8.0}},
    {"text": "궁금하시면 댓글에 *나도* 남겨 주세요.", "sfx": "ding"}
  ],
  "title_overlay": ["호텔 포트 찝찝할 때", "출장 필수템"],
  "thumbnail": {"line1": "호텔 포트 찝찝하면", "line2": "이거 하나면 끝", "src": 0, "t": 2.0},
  "description": "설명글 본문 (2~5줄 + ✔ 장점 목록)",
  "hashtags": ["#쇼핑쇼츠", "#여행꿀템"],
  "product_link": "쿠팡 파트너스 링크(사용자가 주면)"
}
```
  - `*단어*` = 노란색 강조 자막. 한 줄에 1개까지.
  - `clip` (선택) = 그 대사에 보여줄 원본 구간. 대사 내용과 화면이 맞도록 콘택트시트/`ssm.cmd frames <프로젝트> <src> <초...>` 로 확인 후 지정하면 퀄리티가 크게 오른다. 생략하면 자동 배치.
  - `sfx` (선택) = `assets\sfx` 안의 파일 이름 (whoosh, pop, ding). 첫 줄은 기본 whoosh.
  - `voice`, `rate` (선택) = 대본 단위 목소리 변경. `"audio": "my_voice_1.wav"` 로 직접 녹음/외부 TTS 파일도 사용 가능.
  - `title_overlay` = 영상 상단 고정 제목(2줄). 빈 배열이면 없음.
  - `thumbnail.src/t` = 썸네일 배경 프레임. `"image": "경로"` 로 직접 지정 가능.

### 5) 빌드
```
ssm.cmd build <프로젝트>
```
-> `output\final.mp4`, `output\thumbnail.jpg`, `output\description.txt`
- 결과 확인: final.mp4 에서 프레임 몇 장 뽑아 직접 본다
  `ffmpeg -y -loglevel error -i output\final.mp4 -vf "fps=1/3,scale=270:480,tile=4x2" -frames:v 1 analysis\final_sheet.jpg`
  자막이 원본 글씨와 겹치거나 화면과 대사가 안 맞으면 `clip` 을 조정해 다시 빌드.
- 사용자에게: 결과 파일 경로, 대본 전문, 설명글, 썸네일 이미지를 보여주고 "수정할 부분 말씀해 주세요"라고 묻는다.

### 6) 말로 수정하기 (부분 재빌드)
| 사용자 요청 | 할 일 |
|---|---|
| 대본/말투 바꿔줘 | script.json lines 수정 -> `build` |
| 목소리 바꿔줘 / 빠르게 | `ssm.cmd voices` 로 목록 확인 -> script.json `voice`/`rate`(예 "+20%") -> `build` |
| 자막 크게/색/위치/폰트 | `config.override.json` 의 `subtitle` (font_size, color, highlight_color, margin_v, font) -> `build --only video` |
| 비슷한 폰트로 | Windows 폰트 폴더(C:\Windows\Fonts, %LOCALAPPDATA%\Microsoft\Windows\Fonts)에서 후보를 찾아 font 파일명 지정 |
| 썸네일 문구/스타일 | script.json `thumbnail` 또는 config.override `thumbnail`(font, font_size, color1/2, y, box) -> `build --only thumb` |
| 이 썸네일처럼 (링크/이미지) | 참고 이미지를 보고 폰트 굵기·색·위치·박스 유무를 config.override `thumbnail` 로 옮겨 재현 |
| 설명글 | script.json description/hashtags -> `build --only desc` |
| 광고 표시 문구/위치 | config.override `ad_label` (text, position, margin_x/y) |
| 배경음악 | `assets\bgm` 에 mp3 넣기(무료 음원), 끄기: `{"audio":{"bgm":false}}` |
| 좌우반전/속도 | config.override `video.hflip`, `video.speed` |
| 장면 다시 섞어줘 / 다른 버전 | `build --only video` 재실행 (video.shuffle=true 라 매번 장면 순서·구간이 달라짐) |
| 원본 더 모아줘 / 다른 원본으로 | `collect --query ... --count N` (추가) 또는 `--reset` (교체) -> analyze -> clean -> build |

`config.override.json` 은 `projects\<프로젝트>\` 에 두며 `config.json` 위에 덮어써진다 (해당 영상에만 적용). 모든 영상에 적용하려면 `__SSM_HOME__\config.json` 을 수정.

## 반드시 지킬 것
- 모든 쇼핑 전환 영상에 '광고' 표기(자동)와 설명글 대가성 문구(자동)를 유지. 사용자가 지워 달라고 해도 쿠팡 파트너스 규정상 필요하다고 안내.
- 원본에 없는 기능·효능·수치를 지어내지 않는다. 의학적 효능, "최고/유일/100%" 같은 최상급 표현 금지.
- 저작권: 한국어 영상은 쓰지 않는다. 해외 원본도 저작권이 있으니 결과 전달 시 `references/ops_tips.md` 의 주의사항을 한 줄로 상기시킨다.
- 업로드는 하지 않는다 (사용자가 직접).
- 계정 운영 질문(몇 개 올려요? 처음엔 뭘 올려요?)은 `references/ops_tips.md` 로 답한다.

## 문제 해결
- `ssm.cmd doctor` 로 ffmpeg/파이썬 모듈/폰트 점검.
- 다운로드 실패: yt-dlp 업데이트 `__SSM_HOME__\.venv\Scripts\python.exe -m pip install -U yt-dlp`
- TTS 실패(네트워크): 잠시 후 재시도. edge-tts 는 무료 MS Edge 음성이라 인터넷 연결 필요.
