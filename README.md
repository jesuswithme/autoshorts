# autoshorts - 오토 쇼핑 쇼츠

상품 영상 링크 하나로 **쇼핑 쇼츠 완성본(영상 + 썸네일 + 설명글)** 을 만드는 Claude Code / Codex 스킬입니다.
별도 API 키 없이 Claude Code 나 Codex 구독 안에서 돌아가고, 목소리는 무료 TTS(Microsoft Edge 음성)를 씁니다.

```
쇼핑쇼츠 만들어줘 https://www.xiaohongshu.com/explore/xxxx
```

## 하는 일

1. **원본 받기**: 샤오홍슈·더우인·틱톡·유튜브 링크, 또는 내 PC의 mp4
2. **비슷한 원본 3개 자동 수집**: 같은 상품의 다른 영상을 찾아 섞음 → 결과가 원본과 똑같아지지 않음 (같은 영상 재업로드·한국어 영상은 자동 제외)
3. **한국어 영상 거르기**: 제목/화면 한글 OCR 검사 (국내 저작권 신고 위험 회피)
4. **원본 자막 지우기**: 중국어·영어 자막만 지우고 제품 로고·버튼 글씨는 남김, 가로 영상은 9:16 으로 재구성
5. **대본**: 원본 자막을 OCR 로 읽어 상품 특징 파악 → 6가지 결(공감형/반전형/비교형/리스트형/상황극/정보형) 중 골라서 작성
6. **편집**: 무료 TTS, 키워드 노란색 강조 자막, 원본 자막 자리를 덮는 자막 바, 효과음, 배경음악, 상단 제목, '광고' 표기
7. **썸네일 + 설명글**: 두 줄 썸네일, 쿠팡 파트너스 대가성 문구 포함 설명글
8. **말로 수정**: "자막 크게", "목소리 남자로", "썸네일 문구 바꿔줘", "장면 다시 섞어줘"

빌드할 때마다 장면 순서·구간이 무작위로 바뀌어, 같은 상품으로 여러 개를 만들어도 결과가 다릅니다.

## 설치

### 필요한 것
- [Claude Code](https://docs.anthropic.com/claude-code) 또는 [Codex CLI](https://github.com/openai/codex) (구독)
- Python 3.10 ~ 3.13
- ffmpeg (`winget install Gyan.FFmpeg` / macOS `brew install ffmpeg`)

### Windows
```powershell
git clone https://github.com/jesuswithme/autoshorts.git
cd autoshorts
powershell -ExecutionPolicy Bypass -File setup.ps1
```

### macOS / Linux (실험적)
```bash
git clone https://github.com/jesuswithme/autoshorts.git
cd autoshorts
bash setup.sh
```

설치 스크립트가 하는 일: 가상환경(.venv) + 패키지 설치, 효과음 생성, Pretendard 폰트 다운로드(없을 때),
`~/.claude/skills`, `~/.codex/skills` 에 스킬 등록 (Aside 사용자면 Aside 스킬도 등록).
폴더를 옮겼으면 설치 스크립트를 다시 실행하세요 (스킬에 설치 경로가 기록됩니다).

## 사용법

Claude Code 또는 Codex 를 **새로** 열고:
```
쇼핑쇼츠 만들어줘 <상품 영상 링크>
```
1. 링크를 넣는다 → 비슷한 원본 3개를 자동으로 더 모은다
2. 대본 결을 고른다 ("알아서 해줘" 도 가능)
3. 기다린다 (원본 4개 기준 약 10~15분)
4. 결과를 보고 말로 수정 → 업로드는 직접

결과물: `projects/<프로젝트명>/output/`
- `final.mp4` 업로드할 영상 (1080x1920)
- `thumbnail.jpg` 썸네일
- `description.txt` 설명글

쿠팡 파트너스 링크를 같이 주면 설명글에 넣어줍니다: `쇼핑쇼츠 만들어줘 <영상링크>, 쿠팡링크는 <링크>`

### 샤오홍슈 링크
- yt-dlp 로 받기 실패하면 브라우저 쿠키로 재시도합니다 (`--cookies-browser chrome`).
- **Aside 브라우저** 사용자는 rednote.com 에 로그인해 두면 샤오홍슈에서 직접 검색·다운로드해 비슷한 원본을 더 정확하게 모읍니다 (`aside-skill/`).
- 로그인 없이 쓰면 비슷한 원본은 유튜브(중국 상품 쇼츠 재업로드)에서 찾습니다.

## 직접 실행 (CLI)

```
ssm.cmd new <프로젝트> <링크 또는 mp4...>     # 원본 받기
ssm.cmd collect <프로젝트> --query "중국어 상품 키워드" --count 3   # 비슷한 원본 자동 수집
ssm.cmd analyze <프로젝트>                    # 한글 필터 + 원본 자막 OCR
ssm.cmd clean <프로젝트>                      # 원본 자막 지우기
ssm.cmd init-script <프로젝트>                # script.json 템플릿 (대본)
ssm.cmd build <프로젝트> [--only video|tts|thumb|desc]
ssm.cmd voices                                # 무료 한국어 목소리 목록
ssm.cmd doctor                                # 환경 점검
```
macOS/Linux 는 `ssm.cmd` 대신 `./ssm`.

## 설정

- 전체 기본값: `config.json` (목소리, 자막 폰트/크기/색, 썸네일, 광고 표기, 효과음, 수집 개수 등)
- 영상별: `projects/<이름>/config.override.json`
- 배경음악: `assets/bgm/` 에 mp3 를 넣으면 자동 사용 (저작권 없는 음원만)

## 폴더 구조

```
ssm.py                제작 엔진 (CLI)
config.json           기본 설정
skill/                Claude Code / Codex 스킬 (SKILL.md + 대본 결·운영 팁)
aside-skill/          Aside 브라우저용 스킬 (샤오홍슈 직접 검색·다운로드)
assets/sfx/           효과음 (설치 시 생성)
setup.ps1 / setup.sh  설치
```

## 주의

- **저작권**: 한국어 영상을 거르는 것은 국내 신고 위험을 줄일 뿐, 해외 원본 영상에도 저작권이 있습니다. 가능하면 직접 촬영본, 판매자·제조사 제공 영상을 섞어 쓰고, 신고가 들어오면 바로 내리세요. 이 도구의 사용 책임은 사용자에게 있습니다.
- 쿠팡 파트너스 수익을 받으려면 영상의 '광고' 표기와 설명글의 대가성 문구가 필요합니다 (자동으로 들어갑니다).
- 샤오홍슈·더우인 자동 검색은 요청 간격을 두지만, 과도하게 반복하면 계정이 제한될 수 있습니다.
