#!/usr/bin/env bash
# 쇼핑쇼츠메이커 설치 (macOS / Linux, 실험적 지원)
# 사용: bash setup.sh
set -e
HOME_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$HOME_DIR"
unset PIP_PREFIX PYTHONHOME VIRTUAL_ENV

echo "== 1/5 Python 확인"
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v $c >/dev/null 2>&1; then PY=$c; break; fi
done
[ -z "$PY" ] && { echo "Python 3.10~3.13 필요 (brew install python@3.13)"; exit 1; }
echo "   $PY"

echo "== 2/5 ffmpeg 확인"
command -v ffmpeg >/dev/null 2>&1 || { echo "ffmpeg 필요 (brew install ffmpeg)"; exit 1; }

echo "== 3/5 가상환경 + 패키지"
[ -x .venv/bin/python ] || $PY -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt
chmod +x ssm

echo "== 4/5 효과음 + 폰트"
mkdir -p assets/sfx assets/bgm assets/fonts projects
if [ ! -f assets/sfx/whoosh.wav ]; then
  ffmpeg -y -loglevel error -f lavfi -i "anoisesrc=d=0.45:c=pink:a=0.8" -af "bandpass=f=1800:w=1500,afade=t=in:d=0.2,afade=t=out:st=0.2:d=0.25,volume=2" -ar 44100 assets/sfx/whoosh.wav
  ffmpeg -y -loglevel error -f lavfi -i "sine=f=880:d=0.15" -af "afade=t=out:st=0.02:d=0.13,volume=0.9" -ar 44100 assets/sfx/pop.wav
  ffmpeg -y -loglevel error -f lavfi -i "sine=f=1320:d=0.12" -f lavfi -i "sine=f=1760:d=0.25" -filter_complex "[0]afade=t=out:st=0.05:d=0.07[a];[1]adelay=90|90,afade=t=out:st=0.1:d=0.25[b];[a][b]amix=inputs=2:normalize=0,volume=0.7" -ar 44100 assets/sfx/ding.wav
fi
if [ ! -f assets/fonts/Pretendard-Black.otf ]; then
  tmp=$(mktemp -d)
  curl -sL -o "$tmp/p.zip" https://github.com/orioncactus/pretendard/releases/download/v1.3.9/Pretendard-1.3.9.zip && \
  unzip -q -j -o "$tmp/p.zip" "public/static/Pretendard-Bold.otf" "public/static/Pretendard-ExtraBold.otf" "public/static/Pretendard-Black.otf" -d assets/fonts || \
  echo "   폰트 다운로드 실패 -> 시스템 고딕으로 대체"
fi

echo "== 5/5 Claude Code / Codex 스킬 등록"
for t in "$HOME/.claude/skills/shopping-shorts-maker" "$HOME/.codex/skills/shopping-shorts-maker"; do
  mkdir -p "$t/references"
  sed "s#__SSM_HOME__\\\\ssm.cmd#__SSM_HOME__/ssm#g; s#__SSM_HOME__#$HOME_DIR#g" skill/SKILL.md > "$t/SKILL.md"
  cp skill/references/* "$t/references/"
  echo "   $t"
done
./ssm doctor
echo "설치 완료! (macOS 에서는 SKILL.md 의 ssm.cmd 대신 ./ssm 을 사용)"
