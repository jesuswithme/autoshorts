---
name: "shopping-shorts-maker"
description: "쇼핑 쇼츠(인스타 릴스/유튜브 쇼츠/틱톡) 자동 제작. 샤오홍슈(rednote)·더우인·유튜브 상품 영상 링크 하나(또는 제품 이름·분야로 샤오홍슈에서 반응 좋은 영상을 찾아 쿠팡 판매 여부까지 확인)로 비슷한 원본 3개를 샤오홍슈에서 직접 찾아 섞고, 한국어 영상 필터 -> 원본 자막 제거 -> 대본 -> 무료 TTS -> 자막·효과음·광고표시 -> 렌더링 -> 썸네일 -> 설명글까지 만든다. 사용자가 '쇼핑쇼츠', '쇼핑 숏츠 만들어줘', 상품 영상 링크와 '쇼츠로 만들어줘', '쿠팡 파트너스 영상', '쇼핑쇼츠 거리/상품 찾아줘' 등을 말하면 사용."
---

# 오토 쇼핑 쇼츠 (Aside 버전)

- 엔진: `__SSM_HOME__\ssm.cmd` (Bash 도구로 실행, PowerShell)
- 상세 절차·script.json 형식·말로 수정하기 표: `__SSM_HOME__\skill\SKILL.md` (필요한 부분만 읽기)
- 대본 결: `__SSM_HOME__\skill\references\tones.md`
- 운영 팁·저작권: `__SSM_HOME__\skill\references\ops_tips.md`
- 샤오홍슈 헬퍼: REPL 에서 `eval(await fs.readFile('__ASIDE_SKILL_DIR__/scripts/xhs.js', 'utf8'))` -> `xhs.*`

샤오홍슈는 Aside 브라우저에서 **rednote.com 로그인**이 필요하다 (링크는 `xhs.normalize` 로 rednote.com 으로 바꿔 연다). 검색 화면에 로그인 창이 뜨면 사용자에게 로그인을 요청한다.
analyze/clean/build 는 수 분 걸린다: Bash 는 `yield_ms` 로 백그라운드 실행 후 `bash_interact` 로 확인하고, 기다리는 동안 다음 단계를 병렬로 진행한다.

## 진행 순서

프로젝트명: 영문 소문자-하이픈 (예 `hot-water-0516`). 받은 파일은 `__SSM_HOME__\projects\_inbox\<프로젝트>\` 에 둔다.

### 0. 상품 찾기 (링크 대신 제품 이름·분야를 줄 때)
사용자가 "휴대용 선풍기로 찾아줘", "주방 꿀템 쇼핑쇼츠 거리 찾아줘"처럼 말하면:
1. 제품명/분야를 **중국어 검색어 2~3개**로 바꾼다 (예: 주방 꿀템 -> `厨房神器`, `厨房小工具 好物` / 휴대용 선풍기 -> `便携小风扇`, `手持风扇 好物`).
2. 후보 찾기 (약 2분, 검색 후 상위 16개 상세 확인 -> 6~90초 영상, 한글 제외, **댓글×3 + 저장×2 + 좋아요** 점수순):
```js
eval(await fs.readFile('__ASIDE_SKILL_DIR__/scripts/xhs.js', 'utf8'));   // xhs + coupang
const pg = await openTab('https://www.rednote.com/explore');
const found = await xhs.find(pg, ['검색어1','검색어2'], '__SSM_HOME_FWD__/projects/_find/<이름>', { max: 8 });
```
3. 후보 시트 이미지: `ssm.cmd sheet __SSM_HOME__\projects\_find\<이름>\found.json __SSM_HOME__\projects\_find\<이름>\sheet.jpg` -> read_file 로 직접 보고, 답변에도 이미지로 넣는다.
4. 각 후보가 **단일 상품 영상인지** 판단한다 (제목에 "100个", "10个", "合集", 여러 제품이 나오면 '모음 영상' -> 시드로 부적합 표시). 단일 상품은 한국어 상품명을 붙인다.
5. 단일 상품 후보는 **쿠팡 판매 여부** 확인 (쿠팡 파트너스로 팔 수 있어야 의미가 있다):
```js
const cpg = await openTab('https://www.coupang.com');
const items = await coupang.check(cpg, '한국어 상품명', { limit: 5 });   // name, price, reviews, rocket, ad, url
```
6. 표로 제시: 번호 | 상품(한국어) | 댓글/저장/좋아요 | 길이 | 단일/모음 | 쿠팡 최저가·리뷰 수·로켓 | 한줄 추천 이유.
   추천 기준: 댓글 많음(구매 문의) + 단일 상품 + 쿠팡에 리뷰 많은 유사 상품 있음 + 1~3만원대(충동구매가 쉬움). ask_user_question 으로 번호를 고르게 한다.
7. 고른 후보의 `url` 을 시드 링크로 1단계를 진행. 쿠팡 상품 url 은 기록해 두고, 사용자가 파트너스 링크를 만들어 주면 script.json `product_link` 에 넣는다 (파트너스 링크 생성은 사용자 계정에서 직접).

### 1. 기준 원본(시드) 받기
- **샤오홍슈 링크** (xhslink.com / xiaohongshu.com / rednote.com):
```js
eval(await fs.readFile('__ASIDE_SKILL_DIR__/scripts/xhs.js', 'utf8'));
const pg = await openTab('https://www.rednote.com/explore');
const url = await xhs.normalize(pg, '<사용자 링크>');
const seed = await xhs.note(pg, url);            // title, desc, tags, duration, likes, video
const seedFile = await xhs.download(seed, '__SSM_HOME_FWD__/projects/_inbox/<프로젝트>');
```
  `seed.error` 가 나오면: 로그인 풀림(rednote.com 로그인 요청) 또는 토큰 없는 링크(사용자에게 '공유 > 링크 복사' 링크 요청).
- **유튜브/틱톡/더우인 링크**: `ssm.cmd new <프로젝트> <링크>` (yt-dlp).
- 그다음: `ssm.cmd new <프로젝트> <seedFile>` (같은 이름 .info.json 의 제목·태그가 자동으로 들어간다).
- 이어서 `ssm.cmd analyze <프로젝트>` 를 백그라운드로 실행.

### 2. 비슷한 원본 3개 (샤오홍슈에서 직접)
1. 시드 제목·태그·콘택트시트로 상품을 파악해 **중국어 검색어 2~3개**를 만든다 (상품 유형 + 특징, "好物推荐" 같은 일반어 금지).
2. 후보 다운로드 (6~8개, 6~90초 영상만, 한글 게시물 제외, 시드 제외):
```js
await xhs.collect(pg, ['검색어1','검색어2','검색어3'], '__SSM_HOME_FWD__/projects/_inbox/<프로젝트>/cands', { pool: 7, exclude: [seed.id] });
```
3. 점수화 + 3개 선택 (중복 재업로드·한글 영상 자동 제외):
   `ssm.cmd collect <프로젝트> --from-dir __SSM_HOME__\projects\_inbox\<프로젝트>\cands --count 3`
4. `projects\<프로젝트>\analysis\collect_sheet.jpg` 를 **read_file 로 직접 본다** (1행 시드, 초록=선택, 빨강=탈락). 다른 상품이 선택됐으면 project.json 에서 해당 src `"enabled": false`, 빨간 후보 중 같은 상품은 `ssm.cmd add <프로젝트> <cands\파일.mp4>` 로 넣는다.
5. 샤오홍슈 결과가 3개 미만이면 유튜브로 보충: `ssm.cmd collect <프로젝트> --query "검색어" --count <부족분>`.
- 요청 간격을 두고(헬퍼에 내장) 한 번에 검색어 3개, 후보 8개를 넘기지 않는다 (계정 제한 방지).

### 3. 분석·자막 제거
`ssm.cmd analyze <프로젝트> --src <새 src 번호들>` -> `ssm.cmd clean <프로젝트>` (백그라운드).
`analysis\report.json` 의 `original_subtitles` 를 번역해 상품 사실을 파악한다 (없는 기능 지어내기 금지).

### 4. 대본 결 고르기 -> script.json
tones.md 의 6가지 결과 CTA 를 짧게 제시하고 ask_user_question 으로 고르게 한다 ("알아서" = 공감형 + 댓글 유도).
`projects\<프로젝트>\script.json` 작성 (형식은 엔진 SKILL.md 참고: lines/sfx/clip, title_overlay, thumbnail, description, hashtags, product_link).

### 5. 빌드 -> 확인 -> 전달
`ssm.cmd build <프로젝트>` -> 결과 프레임 시트를 만들어 직접 확인:
`ffmpeg -y -loglevel error -i output\final.mp4 -vf "fps=1/3.5,scale=240:426,tile=6x1" -frames:v 1 -update 1 analysis\final_sheet.jpg`
- **결과물 3개(final.mp4, thumbnail.jpg, description.txt)를 모두 세션 artifacts 폴더에 복사**한다 (파일명 앞에 프로젝트명, 예: `<프로젝트>_final.mp4`, `<프로젝트>_thumbnail.jpg`, `<프로젝트>_description.txt`). 영상만 복사하지 말 것.
- 답변에는 대본 전문, 설명글 전문(복사해서 바로 쓰도록 코드블록), 썸네일 이미지와 프레임 시트(markdown 이미지), 결과 폴더 경로를 넣는다.
- 수정 요청은 엔진 SKILL.md 의 "말로 수정하기" 표대로 부분 재빌드. "다른 버전" = `build --only video` (장면 무작위 재배치).

## 지킬 것
- '광고' 표기와 쿠팡 파트너스 대가성 문구 유지. 업로드는 하지 않는다.
- 한국어 영상 사용 금지. 결과 전달 시 해외 원본 저작권 주의 한 줄.
- 샤오홍슈 로그인·토큰 오류, 다운로드 실패가 반복되면 멈추고 사용자에게 알린다 (무리한 재시도 금지).
