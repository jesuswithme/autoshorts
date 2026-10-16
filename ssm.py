# -*- coding: utf-8 -*-
"""
Shopping Shorts Maker (ssm) - 링크 -> 쇼핑 쇼츠 자동 제작 엔진
Claude Code / Codex 스킬이 이 CLI를 호출해서 사용합니다.

명령 요약
  ssm new <project> <url...> [--cookies-browser chrome]   원본 다운로드
  ssm add <project> <url...>                              원본 추가 다운로드
  ssm collect <project> [--count 3] [--query q ...]       비슷한 원본 자동 수집(중복·한글 제외)
  ssm analyze <project>                                   한글 필터 + 자막 영역 + 중국어 자막 OCR + 콘택트시트
  ssm clean <project> [--mode blur|inpaint|none]          원본 자막 지우기 + 9:16 정규화
  ssm init-script <project>                               script.json 템플릿 생성
  ssm build <project> [--only tts|video|thumb|desc]       TTS/자막/편집/렌더/썸네일/설명글
  ssm frames <project> <src> <t1> [t2 ...]                특정 시점 프레임 추출(썸네일 후보 확인용)
  ssm voices                                              무료 한국어 TTS 목소리 목록
  ssm doctor                                              환경 점검
"""
import argparse
import asyncio
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECTS = ROOT / "projects"
ASSETS = ROOT / "assets"
W, H, FPS = 1080, 1920, 30
HANGUL = re.compile(r"[\uac00-\ud7a3\u3131-\u318e]")

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


# ----------------------------------------------------------------- utils
def log(*a):
    print("[ssm]", *a, flush=True)


def die(msg):
    print("[ssm][ERROR]", msg, flush=True)
    sys.exit(1)


def run(cmd, cwd=None, quiet=True):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(r.stdout[-3000:])
        print(r.stderr[-3000:])
        die("command failed: " + " ".join(str(c) for c in cmd[:6]) + " ...")
    return r


def load_json(p, default=None):
    p = Path(p)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def save_json(p, data):
    Path(p).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def deep_merge(a, b):
    out = dict(a)
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def config(project_dir=None):
    cfg = load_json(ROOT / "config.json", {})
    if project_dir:
        cfg = deep_merge(cfg, load_json(Path(project_dir) / "config.override.json", {}))
    return cfg


def pdir(name):
    d = PROJECTS / name
    if not d.exists():
        die(f"프로젝트가 없습니다: {d}")
    return d


def probe(path):
    r = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)])
    j = json.loads(r.stdout)
    v = next((s for s in j["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in j["streams"] if s["codec_type"] == "audio"), None)
    info = {"duration": float(j["format"].get("duration", 0) or 0), "has_audio": a is not None}
    if v:
        fr = v.get("avg_frame_rate", "30/1")
        try:
            n, d = fr.split("/")
            fps = float(n) / float(d) if float(d) else 30.0
        except Exception:
            fps = 30.0
        rot = 0
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = int(sd["rotation"])
        w, h = int(v["width"]), int(v["height"])
        if abs(rot) in (90, 270):
            w, h = h, w
        info.update({"width": w, "height": h, "fps": fps})
    return info


def audio_duration(path):
    return probe(path)["duration"]


def resolve_font(path_or_name):
    cands = [path_or_name,
             str(Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Windows/Fonts" / path_or_name),
             str(Path("C:/Windows/Fonts") / path_or_name),
             str(ASSETS / "fonts" / path_or_name)]
    for c in cands:
        if c and Path(c).exists():
            return str(Path(c))
    for fb in ["C:/Windows/Fonts/malgunbd.ttf", "/System/Library/Fonts/AppleSDGothicNeo.ttc"]:
        if Path(fb).exists():
            log(f"폰트 '{path_or_name}' 없음 -> {fb} 사용")
            return fb
    die(f"폰트를 찾을 수 없습니다: {path_or_name}")


def font_family(path):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(path, 20).getname()[0]
    except Exception:
        return "Malgun Gothic"


# ----------------------------------------------------------------- new / add (download)
def cmd_new(args):
    d = PROJECTS / args.project
    if d.exists() and not args.add:
        die(f"이미 있는 프로젝트입니다: {d} (원본 추가는 ssm add 사용)")
    (d / "sources").mkdir(parents=True, exist_ok=True)
    meta = load_json(d / "project.json", {"name": args.project, "sources": []})
    for url in args.urls:
        idx = max([s["id"] for s in meta["sources"]] + [-1]) + 1
        if Path(url).exists():  # 로컬 파일 (직접 찍은 영상, 판매자 제공 영상, Aside로 받은 샤오홍슈 영상)
            dst = d / "sources" / f"src{idx}{Path(url).suffix.lower() or '.mp4'}"
            shutil.copy(url, dst)
            side = load_json(Path(url).with_suffix(".info.json"), {}) or {}
            meta["sources"].append({"id": idx, "url": side.get("url", str(Path(url).resolve())), "vid": side.get("id"),
                                    "file": str(dst.relative_to(d)),
                                    "title": side.get("title") or Path(url).stem,
                                    "description": (side.get("desc") or "")[:1500], "uploader": side.get("user", "local"),
                                    "extractor": side.get("platform", "local"), "tags": side.get("tags") or [],
                                    "enabled": True})
            log(f"로컬 파일 추가: src{idx} <- {url}")
            continue
        out_tmpl = str(d / "sources" / f"src{idx}.%(ext)s")
        cmd = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-warnings",
               "-f", "bv*[height<=1920]+ba/b", "--merge-output-format", "mp4",
               "--write-info-json", "-o", out_tmpl, url]
        if args.cookies_browser:
            cmd[3:3] = ["--cookies-from-browser", args.cookies_browser]
        log(f"다운로드 중: {url}")
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        files = sorted((d / "sources").glob(f"src{idx}.*"))
        mp4 = next((f for f in files if f.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov")), None)
        if r.returncode != 0 or not mp4:
            print(r.stderr[-1500:])
            log(f"실패: {url}  (샤오홍슈/더우인은 --cookies-browser chrome 옵션을 시도하세요)")
            continue
        info = load_json(next((f for f in files if f.name.endswith(".info.json")), Path("_none")), {}) or {}
        meta["sources"].append({
            "id": idx, "url": url, "vid": info.get("id"), "file": str(mp4.relative_to(d)),
            "title": info.get("title", ""), "description": (info.get("description") or "")[:1500],
            "uploader": info.get("uploader", ""), "extractor": info.get("extractor_key", ""),
            "tags": info.get("tags", [])[:30] if info.get("tags") else [],
            "enabled": True,
        })
        log(f"완료: src{idx} -> {mp4.name}  ({info.get('extractor_key','')}: {info.get('title','')[:60]})")
    save_json(d / "project.json", meta)
    log(f"프로젝트: {d}  원본 {len(meta['sources'])}개")


# ----------------------------------------------------------------- OCR helpers
_OCR = {}


def ocr_engine(kind="ch"):
    if kind in _OCR:
        return _OCR[kind]
    from rapidocr import RapidOCR
    eng = None
    try:
        if kind == "ko":
            from rapidocr import LangRec, OCRVersion, ModelType
            eng = RapidOCR(params={"Rec.lang_type": LangRec.KOREAN, "Rec.ocr_version": OCRVersion.PPOCRV5,
                                   "Rec.model_type": ModelType.MOBILE, "Global.log_level": "error"})
        else:
            eng = RapidOCR(params={"Global.log_level": "error"})
    except Exception as e:
        log(f"OCR 엔진({kind}) 초기화 실패: {e}")
        try:
            eng = RapidOCR() if kind == "ch" else None
        except Exception:
            eng = None
    _OCR[kind] = eng
    return eng


def ocr_frame(img, kind="ch", max_side=960):
    import cv2
    eng = ocr_engine(kind)
    if eng is None:
        return []
    s = min(1.0, max_side / max(img.shape[:2]))
    if s < 1.0:
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    try:
        res = eng(img)
    except Exception:
        return []
    boxes = getattr(res, "boxes", None)
    if boxes is None:
        return []
    out = []
    for b, t, sc in zip(boxes, res.txts or [], res.scores or []):
        xs = [p[0] / s for p in b]
        ys = [p[1] / s for p in b]
        out.append({"box": [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))], "text": t, "score": float(sc)})
    return out


def sample_frames(video, step=0.5, max_frames=400, max_sec=None):
    import cv2
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    dur = n / fps if fps else 0
    if max_sec:
        dur = min(dur, max_sec)
    t = 0.0
    frames = []
    while t < dur and len(frames) < max_frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
        ok, fr = cap.read()
        if ok:
            frames.append((round(t, 2), fr))
        t += step
    cap.release()
    return frames, dur, fps


# ----------------------------------------------------------------- analyze
def cmd_analyze(args):
    from concurrent.futures import ProcessPoolExecutor
    d = pdir(args.project)
    meta = load_json(d / "project.json")
    cfg = config(d)
    (d / "analysis").mkdir(exist_ok=True)
    if args.src is not None:
        todo = [s for s in meta["sources"] if s["id"] in args.src]
    else:
        todo = [s for s in meta["sources"] if s.get("enabled", True)]
    log(f"분석 시작: 원본 {len(todo)}개 (원본당 약 1~2분 소요)")
    with ProcessPoolExecutor(max_workers=min(2, max(1, len(todo)))) as ex:
        rows = list(ex.map(analyze_one, [str(d)] * len(todo), todo, [cfg] * len(todo)))
    old = {r["id"]: r for r in (load_json(d / "analysis" / "report.json", {"sources": []}) or {}).get("sources", [])}
    for s, row in zip(todo, rows):
        old[s["id"]] = row
        if row.get("excluded"):
            s["enabled"] = False
        log(f"src{s['id']}: {row['duration']}s {row['size']} 한글의심={row['korean_suspect']} "
            f"자막프레임={row['subtitle_frames']}" + ("  -> 제외됨" if row.get("excluded") else ""))
    report = {"sources": [old[k] for k in sorted(old)]}
    save_json(d / "project.json", meta)
    save_json(d / "analysis" / "report.json", report)
    log(f"분석 리포트: {d / 'analysis' / 'report.json'}")
    log("다음: 콘택트시트 이미지를 직접 보고 한글/상품 확인 -> ssm clean")


def analyze_one(d, s, cfg):
    import cv2
    import numpy as np
    d = Path(d)
    if True:
        src = d / s["file"]
        info = probe(src)
        frames, dur, fps = sample_frames(src, step=cfg["clean"]["ocr_step"], max_sec=cfg["clean"].get("max_source_sec"))
        # 1) 메타데이터 한글 검사
        meta_text = " ".join([s.get("title", ""), s.get("description", ""), " ".join(s.get("tags", []))])
        hangul_meta = len(HANGUL.findall(meta_text))
        # 2) OCR (중국어/영어 모델) - 자막 영역 + 내용 파악
        ocr_rows = []
        texts = []
        for t, fr in frames:
            res = [r for r in ocr_frame(fr, "ch") if r["score"] >= cfg["clean"]["min_score"]]
            ocr_rows.append({"t": t, "items": res})
            for r in res:
                if r["text"] not in texts:
                    texts.append(r["text"])
        # 3) 한글 OCR 검사 (한국어 모델로 텍스트가 있는 프레임만 재검사)
        hangul_hits = []
        text_frames = [(t, fr) for (t, fr), row in zip(frames, ocr_rows) if row["items"]]
        for t, fr in text_frames[:: max(1, len(text_frames) // 12 or 1)][:12]:
            for r in ocr_frame(fr, "ko"):
                hc = len(HANGUL.findall(r["text"]))
                if r["score"] >= 0.85 and hc >= 2 and hc / max(1, len(r["text"])) > 0.5:
                    hangul_hits.append({"t": t, "text": r["text"], "score": round(r["score"], 2)})
        korean_suspect = hangul_meta >= 5 or len(hangul_hits) >= 2
        # 4) 콘택트 시트 (에이전트가 직접 눈으로 확인)
        pick = [frames[int(i * (len(frames) - 1) / 7)] for i in range(8)] if frames else []
        tiles = []
        for t, fr in pick:
            th = cv2.resize(fr, (270, int(270 * fr.shape[0] / fr.shape[1])))
            th = cv2.resize(th, (270, 480)) if th.shape[0] > 480 else cv2.copyMakeBorder(
                th, 0, 480 - th.shape[0], 0, 0, cv2.BORDER_CONSTANT)
            cv2.putText(th, f"{t:.1f}s", (8, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
            tiles.append(th)
        if tiles:
            while len(tiles) < 8:
                tiles.append(np.zeros_like(tiles[0]))
            sheet = np.vstack([np.hstack(tiles[:4]), np.hstack(tiles[4:8])])
            sheet_path = d / "analysis" / f"src{s['id']}_sheet.jpg"
            cv2.imwrite(str(sheet_path), sheet)
        save_json(d / "analysis" / f"src{s['id']}_ocr.json", ocr_rows)
        fh_, fw_ = frames[0][1].shape[:2] if frames else (1, 1)
        subs = subtitle_items(ocr_rows, fw_, fh_, cfg)
        sub_frames = sum(1 for items in subs if items)
        sub_texts = []
        for items in subs:
            for it in items:
                if it["text"] not in sub_texts:
                    sub_texts.append(it["text"])
        row = {
            "id": s["id"], "file": s["file"], "duration": round(info["duration"], 2),
            "size": f"{info.get('width')}x{info.get('height')}", "has_audio": info["has_audio"],
            "title": s.get("title", ""), "hangul_in_metadata": hangul_meta,
            "hangul_ocr_hits": hangul_hits[:10], "korean_suspect": korean_suspect,
            "subtitle_frames": f"{sub_frames}/{len(ocr_rows)}",
            "original_subtitles": sub_texts[:60],
            "other_onscreen_text": [x for x in texts if x not in sub_texts][:40],
            "contact_sheet": f"analysis/src{s['id']}_sheet.jpg",
        }
        if korean_suspect and cfg["filter"]["exclude_korean"]:
            row["excluded"] = "한국어 콘텐츠 의심 -> 저작권 회피를 위해 제외 (project.json에서 enabled=true로 되돌릴 수 있음)"
        return row


# ----------------------------------------------------------------- clean (remove subtitles + normalize 9:16)
CJK = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7a3]")


def is_subtitle_box(it, w, h, cfg):
    """자막/캡션처럼 생긴 텍스트만 True. 제품 로고·버튼 글씨는 제외.
    clean.text_filter = 'all' 이면 모든 텍스트를 지움."""
    c = cfg["clean"]
    x1, y1, x2, y2 = it["box"]
    bw, bh = x2 - x1, y2 - y1
    if bh > c["max_box_height_ratio"] * h or bw <= 0 or bh <= 0:
        return False
    if c.get("text_filter", "subtitle") == "all":
        return True
    cjk = len(CJK.findall(it["text"]))
    if cjk >= c["min_cjk_chars"] and bw >= c["min_width_ratio"] * w and bw / bh >= 2.5:
        return True
    # 영어 캐프션: 길고(단어 3개+) 넓은 문장형 텍스트만 (짧은 로고/모델명은 제외)
    words = re.findall(r"[A-Za-z]{2,}", it["text"])
    return len(words) >= 3 and len(it["text"]) >= 12 and bw >= 0.3 * w and bw / bh >= 4


def subtitle_bands(ocr_rows, w, h, cfg):
    """확실한 자막 박스들의 세로 위치를 모아 '자막 줄' 대역을 추정"""
    ys = []
    for row in ocr_rows:
        for it in row["items"]:
            if is_subtitle_box(it, w, h, cfg):
                x1, y1, x2, y2 = it["box"]
                ys.append(((y1 + y2) / 2, y2 - y1))
    if len(ys) < 3:
        return []
    ys.sort()
    bands, cur = [], [ys[0]]
    for y in ys[1:]:
        if y[0] - cur[-1][0] < max(cur[-1][1], y[1]) * 0.8:
            cur.append(y)
        else:
            bands.append(cur)
            cur = [y]
    bands.append(cur)
    out = []
    for b in bands:
        if len(b) >= 3:
            cy = sorted(x[0] for x in b)[len(b) // 2]
            hh = sorted(x[1] for x in b)[len(b) // 2]
            out.append((cy, hh))
    return out


def in_band(it, bands):
    x1, y1, x2, y2 = it["box"]
    cy, bh = (y1 + y2) / 2, y2 - y1
    if len(CJK.findall(it["text"])) < 2:
        return False
    return any(abs(cy - by) < bh_ * 0.8 and 0.6 * bh_ <= bh <= 1.6 * bh_ for by, bh_ in bands)


def subtitle_items(ocr_rows, w, h, cfg):
    bands = subtitle_bands(ocr_rows, w, h, cfg)
    return [[it for it in row["items"] if is_subtitle_box(it, w, h, cfg) or in_band(it, bands)] for row in ocr_rows]


def build_masks(ocr_rows, w, h, cfg):
    """sample time -> list of boxes (dilated)"""
    pad = cfg["clean"]["pad"]
    out = []
    subs = subtitle_items(ocr_rows, w, h, cfg)
    for row, items in zip(ocr_rows, subs):
        boxes = []
        for it in items:
            x1, y1, x2, y2 = it["box"]
            boxes.append([max(0, x1 - pad), max(0, y1 - pad), min(w, x2 + pad), min(h, y2 + pad)])
        out.append((row["t"], boxes))
    return out


def cmd_clean(args):
    import cv2
    import numpy as np
    d = pdir(args.project)
    meta = load_json(d / "project.json")
    cfg = config(d)
    mode = args.mode or cfg["clean"]["mode"]
    (d / "clean").mkdir(exist_ok=True)
    step = cfg["clean"]["ocr_step"]
    enabled = [s for s in meta["sources"] if s.get("enabled", True)]
    if args.src is None and len(enabled) > 1:  # 원본 2개씩 병렬 처리
        procs = []
        for s in enabled:
            cmd = [sys.executable, str(ROOT / "ssm.py"), "clean", args.project, "--src", str(s["id"])]
            if args.mode:
                cmd += ["--mode", args.mode]
            procs.append(cmd)
        running = []
        while procs or running:
            while procs and len(running) < 2:
                running.append(subprocess.Popen(procs.pop(0)))
            running[0].wait()
            if running[0].returncode != 0:
                die("clean 실패")
            running.pop(0)
        log("다음: script.json 작성 (ssm init-script) -> ssm build")
        return
    for s in meta["sources"]:
        if args.src is not None and s["id"] != args.src:
            continue
        if not s.get("enabled", True):
            log(f"src{s['id']} 제외됨 - 건너뜀")
            continue
        src = d / s["file"]
        info = probe(src)
        ocr_p = d / "analysis" / f"src{s['id']}_ocr.json"
        ocr_rows = load_json(ocr_p) if ocr_p.exists() else None
        if ocr_rows is None and mode != "none":
            die("먼저 ssm analyze 를 실행하세요")
        cap = cv2.VideoCapture(str(src))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        fw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        fh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        masks = build_masks(ocr_rows or [], fw, fh, cfg)
        ar = fw / fh
        vertical = abs(ar - 9 / 16) < 0.12
        if vertical:
            vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"
        else:  # 가로/정사각 영상 -> 블러 배경 + 가운데를 잘라 크게 배치
            land = cfg["video"].get("landscape", "crop45")
            if land == "fill":
                fg = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
            elif land == "fit":
                fg = f"scale={W}:-2"
            else:  # crop45: 가운데 4:5 또는 1:1
                ratio = 0.8 if land == "crop45" else 1.0
                fg = f"crop='min(iw,ih*{ratio})':ih,scale={W}:-2"
            vf = (f"split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:5[bg];"
                  f"[b]{fg}[fg];[bg][fg]overlay=0:(H-h)/2,setsar=1")
        # 원본 자막 줄 위치를 출력(1080x1920) 좌표로 변환해 저장 -> build 에서 새 자막으로 덮기
        bands = subtitle_bands(ocr_rows or [], fw, fh, cfg) if mode != "none" else []
        if vertical or cfg["video"].get("landscape") == "fill":
            sc_ = max(W / fw, H / fh)
            off = -(fh * sc_ - H) / 2
        else:
            land = cfg["video"].get("landscape", "crop45")
            cw = fw if land == "fit" else min(fw, fh * (0.8 if land == "crop45" else 1.0))
            sc_ = W / cw
            off = (H - fh * sc_) / 2
        save_json(d / "clean" / f"src{s['id']}.json",
                  {"bands": [{"y": round(off + y * sc_), "h": round(bh * sc_)} for y, bh in bands]})
        out = d / "clean" / f"src{s['id']}.mp4"
        ff = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{fw}x{fh}",
              "-r", f"{fps}", "-i", "-", "-filter_complex" if not vertical else "-vf", vf,
              "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-an", str(out)]
        proc = subprocess.Popen(ff, stdin=subprocess.PIPE)
        i = 0
        removed = 0
        max_sec = cfg["clean"].get("max_source_sec") or 1e9
        while True:
            ok, fr = cap.read()
            if not ok or i / fps >= max_sec:
                break
            t = i / fps
            if mode != "none" and masks:
                k = min(int(t / step), len(masks) - 1)
                boxes = list(masks[k][1])
                if k + 1 < len(masks):
                    boxes += masks[k + 1][1]
                if k - 1 >= 0 and (t - masks[k][0]) < step * 0.5:
                    boxes += masks[k - 1][1]
                if boxes:
                    removed += 1
                    if mode == "inpaint":
                        m = np.zeros(fr.shape[:2], np.uint8)
                        for x1, y1, x2, y2 in boxes:
                            m[y1:y2, x1:x2] = 255
                        small = cv2.resize(fr, (fw // 2, fh // 2))
                        ms = cv2.resize(m, (fw // 2, fh // 2))
                        pr = cv2.resize(cv2.inpaint(small, ms, 5, cv2.INPAINT_TELEA), (fw, fh))
                        fr = np.where(m[..., None] > 0, pr, fr)
                    else:
                        k_ = cfg["clean"]["blur_kernel"] | 1
                        for x1, y1, x2, y2 in boxes:
                            roi = fr[y1:y2, x1:x2]
                            if roi.size:
                                fr[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (k_, k_), 0)
            proc.stdin.write(fr.tobytes())
            i += 1
        cap.release()
        proc.stdin.close()
        proc.wait()
        if proc.returncode != 0:
            die(f"clean 실패: src{s['id']}")
        log(f"src{s['id']}: 자막 제거({mode}) 프레임 {removed}/{i} -> {out.name}")
    log("다음: script.json 작성 (ssm init-script) -> ssm build")


# ----------------------------------------------------------------- script template
SCRIPT_TEMPLATE = {
    "tone": "공감형-여행꿀템",
    "voice": None,
    "rate": None,
    "lines": [
        {"text": "와, 여행 갈 때 *이거 하나* 챙기면 되겠는데요."},
        {"text": "호텔 포트는 좀 찝찝한데 뜨거운 물은 또 필요하잖아요."},
        {"text": "궁금하시면 댓글에 *나도* 남겨 주세요.", "sfx": "pop"}
    ],
    "title_overlay": ["", ""],
    "thumbnail": {"line1": "호텔 포트 찝찝하면", "line2": "이거 하나면 끝", "src": 0, "t": 1.5},
    "description": "상품 설명글을 여기에 씁니다.",
    "hashtags": ["#쇼핑쇼츠", "#여행꿀템"],
    "product_link": ""
}


def cmd_init_script(args):
    d = pdir(args.project)
    p = d / "script.json"
    if p.exists() and not args.force:
        die("script.json 이 이미 있습니다 (--force 로 덮어쓰기)")
    save_json(p, SCRIPT_TEMPLATE)
    log(f"템플릿 생성: {p}")


# ----------------------------------------------------------------- TTS
def clean_tts_text(t):
    return re.sub(r"[*\[\]{}]", "", t).strip()


async def _edge_tts(text, voice, rate, pitch, out):
    import edge_tts
    c = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await c.save(str(out))


def tts_line(text, voice, rate, pitch, cache_dir, trim=True):
    key = hashlib.md5(f"{text}|{voice}|{rate}|{pitch}|{trim}".encode()).hexdigest()[:16]
    wav = cache_dir / f"{key}.wav"
    if wav.exists():
        return wav
    mp3 = cache_dir / f"{key}.mp3"
    for attempt in range(3):
        try:
            asyncio.run(_edge_tts(text, voice, rate, pitch, mp3))
            break
        except Exception as e:
            if attempt == 2:
                die(f"TTS 실패: {e}")
    af = "aresample=44100"
    if trim:
        af = ("silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
              "silenceremove=start_periods=1:start_threshold=-45dB,areverse,aresample=44100")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-af", af, "-ac", "1", "-c:a", "pcm_s16le", str(wav)])
    mp3.unlink(missing_ok=True)
    return wav


def concat_wavs(parts, gap, out):
    with wave.open(str(parts[0]), "rb") as w0:
        params = w0.getparams()
    sil = b"\x00\x00" * int(params.framerate * gap)
    timings = []
    t = 0.0
    with wave.open(str(out), "wb") as wo:
        wo.setparams(params)
        for i, p in enumerate(parts):
            with wave.open(str(p), "rb") as wi:
                frames = wi.readframes(wi.getnframes())
                dur = wi.getnframes() / wi.getframerate()
            wo.writeframes(frames)
            timings.append((t, t + dur))
            t += dur
            if i < len(parts) - 1:
                wo.writeframes(sil)
                t += gap
    return timings, t


# ----------------------------------------------------------------- subtitles (ASS)
def split_chunks(text, max_chars):
    words = text.split()
    chunks, cur = [], ""
    for w_ in words:
        cand = (cur + " " + w_).strip()
        if len(cand.replace("*", "")) <= max_chars or not cur:
            cur = cand
        else:
            chunks.append(cur)
            cur = w_
    if cur:
        chunks.append(cur)
    # *강조* 가 청크를 넘어가면 각 청크에서 닫아준다
    fixed, open_ = [], False
    for c in chunks:
        stars = c.count("*")
        if open_:
            c = "*" + c
        if stars % 2 == 1:
            open_ = not open_
        if open_:
            c = c + "*"
        fixed.append(c.replace("**", ""))
    return fixed


def ass_time(t):
    t = max(0, t)
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def ass_text(chunk, hl_color):
    out, on = "", False
    for part in re.split(r"(\*)", chunk):
        if part == "*":
            on = not on
            out += f"{{\\c{hl_color}}}" if on else "{\\c&H00FFFFFF&}"
        else:
            out += part.replace("{", "(").replace("}", ")")
    return out


def rgb_to_ass(hexrgb):
    hexrgb = hexrgb.lstrip("#")
    r, g, b = hexrgb[0:2], hexrgb[2:4], hexrgb[4:6]
    return f"&H00{b}{g}{r}&".upper()


def write_ass(lines, timings, cfg, out, fam):
    sc = cfg["subtitle"]
    hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{fam},{sc['font_size']},{rgb_to_ass(sc['color'])},&H000000FF&,{rgb_to_ass(sc['outline_color'])},&H64000000&,0,0,0,0,100,100,0,0,1,{sc['outline']},{sc['shadow']},2,60,60,{sc['margin_v']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    hl = rgb_to_ass(sc["highlight_color"])
    for line, (a, b) in zip(lines, timings):
        text = line.get("sub") or line["text"]
        chunks = split_chunks(text, sc["max_chars"])
        lens = [max(1, len(c.replace(" ", "").replace("*", ""))) for c in chunks]
        tot = sum(lens)
        t = a
        for c, ln in zip(chunks, lens):
            dur = (b - a) * ln / tot
            pop = "{\\fscx80\\fscy80\\t(0,90,\\fscx100\\fscy100)}" if sc.get("pop", True) else ""
            ev.append(f"Dialogue: 0,{ass_time(t)},{ass_time(t + dur)},Main,,0,0,0,,{pop}{ass_text(c, hl)}")
            t += dur
    Path(out).write_text(hdr + "\n".join(ev) + "\n", encoding="utf-8")


# ----------------------------------------------------------------- overlays (PNG via Pillow)
def make_label_png(text, font_path, out, size=44, bg=(0, 0, 0, 150), fg=(255, 255, 255, 255)):
    from PIL import Image, ImageDraw, ImageFont
    f = ImageFont.truetype(font_path, size)
    l, t, r, b = f.getbbox(text)
    pw, ph = 26, 14
    img = Image.new("RGBA", (r - l + pw * 2, b - t + ph * 2), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    dr.rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=14, fill=bg)
    dr.text((pw - l, ph - t), text, font=f, fill=fg)
    img.save(out)


def fit_font(font_path, text, max_w, start, min_size=40):
    from PIL import ImageFont
    s = start
    while s > min_size:
        f = ImageFont.truetype(font_path, s)
        l, t, r, b = f.getbbox(text)
        if r - l <= max_w:
            return f
        s -= 4
    return ImageFont.truetype(font_path, min_size)


def make_title_png(lines, cfg, out):
    from PIL import Image, ImageDraw
    tc = cfg["title_overlay"]
    font = resolve_font(tc["font"])
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    y = tc["y"]
    colors = [tc["color1"], tc["color2"]]
    for i, ln in enumerate([x for x in lines if x]):
        f = fit_font(font, ln, W - 120, tc["font_size"])
        l, t, r, b = f.getbbox(ln)
        x = (W - (r - l)) // 2 - l
        dr.text((x, y - t), ln, font=f, fill=colors[i % 2], stroke_width=tc["stroke"], stroke_fill="#000000")
        y += (b - t) + 24
    img.save(out)


# ----------------------------------------------------------------- video timeline
def plan_timeline(lines, timings, total, sources, cfg):
    """각 대사에 원본 구간을 배정. line['clip']={'src':0,'start':1.2} 지정 가능"""
    vc = cfg["video"]
    durs = {s["id"]: s["clean_dur"] for s in sources}
    ids = [s["id"] for s in sources]
    if vc.get("shuffle", True):  # 빌드할 때마다 장면 순서·시작 구간이 달라져 똑같은 영상이 나오지 않게
        random.shuffle(ids)
        cursors = {i: random.uniform(vc["skip_head"], max(vc["skip_head"], durs[i] * 0.4)) for i in ids}
    else:
        cursors = {s["id"]: vc["skip_head"] for s in sources}
    segs = []
    rr = 0
    for i, (line, (a, b)) in enumerate(zip(lines, timings)):
        end = timings[i + 1][0] if i + 1 < len(timings) else total
        need = end - a
        clip = line.get("clip")
        while need > 0.05:
            if clip:
                sid = clip["src"]
                st = float(clip.get("start", 0))
                clip = None
            else:
                sid = ids[rr % len(ids)]
                st = cursors[sid]
            seg = min(need, vc["max_seg"])
            if need - seg < vc["min_seg"]:
                seg = need
            if st + seg > durs[sid] - 0.05:
                st = max(0.0, min(vc["skip_head"], durs[sid] - seg - 0.05))
                if st + seg > durs[sid]:
                    seg = max(0.3, durs[sid] - st - 0.05)
            segs.append({"src": sid, "start": round(st, 3), "dur": round(seg, 3)})
            cursors[sid] = st + seg
            need -= seg
        rr += 1
    return segs


def render_video(d, segs, cfg, tmp):
    vc = cfg["video"]
    parts = []
    for i, s in enumerate(segs):
        src = d / "clean" / f"src{s['src']}.mp4"
        z = vc["zoom"] if (i % 2 == 1 and vc["zoom"] > 1) else 1.0
        vf = f"scale=iw*{z}:ih*{z},crop={W}:{H}" if z > 1 else f"scale={W}:{H}"
        if vc.get("hflip"):
            vf += ",hflip"
        if vc.get("speed", 1.0) != 1.0:
            vf += f",setpts=PTS/{vc['speed']}"
        vf += f",fps={FPS},setsar=1"
        p = tmp / f"seg{i:03d}.mp4"
        src_len = s["dur"] * vc.get("speed", 1.0)
        run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{s['start']}", "-t", f"{src_len}", "-i", str(src),
             "-vf", vf, "-t", f"{s['dur']}", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
             "-pix_fmt", "yuv420p", str(p)])
        parts.append(p)
    lst = tmp / "concat.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    out = tmp / "video_raw.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "concat.txt", "-c", "copy",
         "video_raw.mp4"], cwd=tmp)
    return out


def pick_files(folder, exts=(".mp3", ".wav", ".m4a")):
    if not folder.exists():
        return []
    return sorted([p for p in folder.iterdir() if p.suffix.lower() in exts])


# ----------------------------------------------------------------- build
def cmd_build(args):
    d = pdir(args.project)
    cfg = config(d)
    sc = load_json(d / "script.json")
    if not sc:
        die("script.json 이 없습니다 (ssm init-script)")
    meta = load_json(d / "project.json")
    only = args.only
    tmp = d / "build"
    (tmp / "tts").mkdir(parents=True, exist_ok=True)
    (tmp / "fonts").mkdir(exist_ok=True)
    outd = d / "output"
    outd.mkdir(exist_ok=True)
    lines = [l for l in sc["lines"] if l.get("text", "").strip()]

    # --- TTS
    voice = sc.get("voice") or cfg["tts"]["voice"]
    rate = sc.get("rate") or cfg["tts"]["rate"]
    pitch = sc.get("pitch") or cfg["tts"]["pitch"]
    parts = []
    if only in (None, "tts", "video"):
        log(f"TTS: {voice} rate={rate} ({len(lines)}줄)")
        for l in lines:
            if l.get("audio"):  # 사용자 녹음/외부 TTS 파일 직접 지정
                ap = Path(l["audio"]) if Path(l["audio"]).is_absolute() else d / l["audio"]
                key = hashlib.md5(str(ap).encode()).hexdigest()[:12]
                wav = tmp / "tts" / f"ext_{key}.wav"
                run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(ap), "-ac", "1", "-ar", "44100",
                     "-c:a", "pcm_s16le", str(wav)])
                parts.append(wav)
            else:
                parts.append(tts_line(clean_tts_text(l["text"]), l.get("voice") or voice, rate, pitch, tmp / "tts",
                                      cfg["tts"]["trim_silence"]))
        timings, total_voice = concat_wavs(parts, cfg["tts"]["gap"], tmp / "narration.wav")
        total = total_voice + cfg["video"]["tail"]
        save_json(tmp / "timings.json", {"lines": timings, "total": total})
        log(f"내레이션 {total_voice:.1f}s -> 영상 {total:.1f}s")
        if only == "tts":
            return
    else:
        tj = load_json(tmp / "timings.json")
        if not tj:
            die("timings.json 없음 - 먼저 ssm build 전체 실행")
        timings, total = tj["lines"], tj["total"]

    if only in (None, "video"):
        # --- sources
        sources = []
        for s in meta["sources"]:
            cp = d / "clean" / f"src{s['id']}.mp4"
            if s.get("enabled", True) and cp.exists():
                sources.append({"id": s["id"], "clean_dur": probe(cp)["duration"]})
        if not sources:
            die("사용 가능한 원본이 없습니다 (ssm clean 먼저)")
        # --- subtitles
        cover = None
        if cfg["subtitle"].get("auto_cover", True):
            ys = []
            for s in sources:
                for b in (load_json(d / "clean" / f"src{s['id']}.json", {}) or {}).get("bands", []):
                    if b["y"] > H * 0.5:
                        ys.append(b["y"] + b["h"] / 2)
            if ys:
                bottom = sorted(ys)[len(ys) // 2]
                band_h = max(b["h"] for s in sources for b in (load_json(d / "clean" / f"src{s['id']}.json", {}) or {}).get("bands", []))
                mv = int(min(max(H - bottom - 6, cfg["subtitle"]["safe_bottom"]), 900))
                cfg["subtitle"]["margin_v"] = mv
                text_bottom = H - mv
                text_top = text_bottom - cfg["subtitle"]["font_size"] * 1.25
                top = min(bottom - band_h, text_top) - 18
                bot = max(bottom + 10, text_bottom + 18)
                cover = {"y": int(top), "h": int(bot - top)}
                log(f"원본 자막 자리를 덮도록 자막 위치 자동 조정: margin_v={mv}")
        sub_font = resolve_font(cfg["subtitle"]["font"])
        shutil.copy(sub_font, tmp / "fonts" / Path(sub_font).name)
        write_ass(lines, timings, cfg, tmp / "subs.ass", font_family(sub_font))
        # --- timeline
        segs = plan_timeline(lines, timings, total, sources, cfg)
        save_json(tmp / "timeline.json", segs)
        log(f"편집 구간 {len(segs)}개 렌더링...")
        render_video(d, segs, cfg, tmp)
        # --- overlays
        inputs = ["-i", "video_raw.mp4", "-i", "narration.wav"]
        fc = []
        vlabel = "[0:v]"
        cb = cfg["subtitle"].get("cover_bar", {})
        pre = ""
        if cover and cb.get("enabled", True):
            pre = (f"drawbox=x=0:y={cover['y']}:w=iw:h={cover['h']}:color={cb.get('color', 'black')}@{cb.get('opacity', 0.55)}:t=fill,")
        fc.append(f"{vlabel}{pre}subtitles=subs.ass:fontsdir=fonts[vs]")
        vlabel = "[vs]"
        idx = 2
        ad = cfg["ad_label"]
        if ad.get("enabled", True):
            make_label_png(ad["text"], resolve_font(ad["font"]), tmp / "ad.png", ad["font_size"])
            inputs += ["-i", "ad.png"]
            x = f"W-w-{ad['margin_x']}" if ad["position"] == "top-right" else f"{ad['margin_x']}"
            fc.append(f"{vlabel}[{idx}:v]overlay={x}:{ad['margin_y']}[va]")
            vlabel = "[va]"
            idx += 1
        title = sc.get("title_overlay") or []
        if any(t for t in title) and cfg["title_overlay"].get("enabled", True):
            make_title_png(title, cfg, tmp / "title.png")
            inputs += ["-i", "title.png"]
            fc.append(f"{vlabel}[{idx}:v]overlay=0:0[vt]")
            vlabel = "[vt]"
            idx += 1
        # --- audio: narration + bgm + sfx
        amix = ["[1:a]volume=1.0[nar]"]
        alabels = ["[nar]"]
        ac = cfg["audio"]
        bgms = pick_files(ASSETS / "bgm")
        bgm = sc.get("bgm") or (str(random.choice(bgms)) if (bgms and ac["bgm"]) else None)
        if bgm:
            inputs += ["-stream_loop", "-1", "-i", str(bgm)]
            amix.append(f"[{idx}:a]volume={ac['bgm_volume']},atrim=0:{total:.2f}[bgm]")
            alabels.append("[bgm]")
            idx += 1
            log(f"BGM: {Path(bgm).name}")
        if ac["sfx"]:
            sfx_dir = ASSETS / "sfx"
            for i, (l, (a, b)) in enumerate(zip(lines, timings)):
                name = l.get("sfx") or (ac["sfx_default"] if i == 0 else None)
                if not name:
                    continue
                f = next((p for p in pick_files(sfx_dir) if p.stem == name), None)
                if not f:
                    continue
                inputs += ["-i", str(f)]
                ms = int(max(0, a - 0.05) * 1000)
                amix.append(f"[{idx}:a]adelay={ms}|{ms},volume={ac['sfx_volume']}[s{i}]")
                alabels.append(f"[s{i}]")
                idx += 1
        fc += amix
        fc.append(f"{''.join(alabels)}amix=inputs={len(alabels)}:normalize=0:duration=first[aout]")
        out = outd / "final.mp4"
        cmd = ["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(fc),
               "-map", vlabel, "-map", "[aout]", "-t", f"{total:.2f}", "-r", str(FPS),
               "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
        (tmp / "last_ffmpeg.txt").write_text(" ".join(cmd), encoding="utf-8")
        run(cmd, cwd=tmp)
        log(f"영상 완료: {out}")

    if only in (None, "thumb"):
        make_thumbnail(d, sc, cfg, outd / "thumbnail.jpg")
    if only in (None, "desc"):
        write_description(sc, cfg, outd / "description.txt")
    log(f"결과 폴더: {outd}")


# ----------------------------------------------------------------- thumbnail
def grab_frame(video, t, out):
    run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(out)])


def make_thumbnail(d, sc, cfg, out):
    from PIL import Image, ImageDraw, ImageFilter
    th = dict(cfg["thumbnail"])
    th.update({k: v for k, v in (sc.get("thumbnail") or {}).items() if k in th})
    tsc = sc.get("thumbnail") or {}
    src = tsc.get("src", 0)
    t = tsc.get("t", 1.0)
    frame = d / "build" / "thumb_frame.jpg"
    vid = d / "clean" / f"src{src}.mp4"
    if tsc.get("image"):
        frame = Path(tsc["image"]) if Path(tsc["image"]).is_absolute() else d / tsc["image"]
    else:
        grab_frame(vid, t, frame)
    img = Image.open(frame).convert("RGB")
    if img.size != (W, H):
        r = max(W / img.width, H / img.height)
        img = img.resize((int(img.width * r) + 1, int(img.height * r) + 1))
        l = (img.width - W) // 2
        tp = (img.height - H) // 2
        img = img.crop((l, tp, l + W, tp + H))
    # 상단 그라데이션으로 가독성 확보
    grad = Image.new("L", (1, H))
    for y in range(H):
        a = int(th["shade"] * max(0.0, 1 - y / (H * 0.55)))
        grad.putpixel((0, y), a)
    shade = Image.new("RGB", (W, H), (0, 0, 0))
    img = Image.composite(shade, img, grad.resize((W, H)))
    dr = ImageDraw.Draw(img)
    font = resolve_font(th["font"])
    y = th["y"]
    for i, (txt, col) in enumerate([(tsc.get("line1", ""), th["color1"]), (tsc.get("line2", ""), th["color2"])]):
        if not txt:
            continue
        f = fit_font(font, txt, W - 100, th["font_size"])
        l, tt, r, b = f.getbbox(txt)
        x = (W - (r - l)) // 2 - l
        if th.get("box") and i == 1:
            dr.rounded_rectangle([x + l - 30, y - 20, x + r + 30, y + (b - tt) + 30], radius=20, fill=th["box_color"])
            dr.text((x, y - tt), txt, font=f, fill=col, stroke_width=0)
        else:
            dr.text((x, y - tt), txt, font=f, fill=col, stroke_width=th["stroke"], stroke_fill="#000000")
        y += (b - tt) + th["line_gap"]
    ad = cfg["ad_label"]
    if ad.get("enabled", True) and th.get("ad_label", True):
        lab = d / "build" / "ad.png"
        make_label_png(ad["text"], resolve_font(ad["font"]), lab, ad["font_size"])
        li = Image.open(lab)
        img.paste(li, (W - li.width - ad["margin_x"], ad["margin_y"]), li)
    img.save(out, quality=95)
    log(f"썸네일 완료: {out}")


# ----------------------------------------------------------------- description
def write_description(sc, cfg, out):
    dc = cfg["description"]
    parts = [sc.get("description", "").strip()]
    if sc.get("product_link"):
        parts.append(f"{dc['link_prefix']} {sc['product_link']}")
    if sc.get("hashtags"):
        parts.append(" ".join(sc["hashtags"]))
    if dc.get("disclosure"):
        parts.append(dc["disclosure"])
    Path(out).write_text("\n\n".join(p for p in parts if p) + "\n", encoding="utf-8")
    log(f"설명글 완료: {out}")


# ----------------------------------------------------------------- collect (비슷한 원본 자동 수집)
GENERIC_TAGS = {"好物推荐", "好物分享", "shorts", "short", "chinesegoods", "chinese", "家居好物", "好物", "抖音",
                "小红书", "生活好物", "实用好物", "黑科技", "开箱", "推荐", "fyp", "viral", "tiktok"}


def yt_id(url):
    m = re.search(r"(?:v=|shorts/|youtu\.be/)([A-Za-z0-9_-]{11})", url or "")
    return m.group(1) if m else None


def auto_queries(seed):
    title = seed.get("title", "")
    title_tags = [re.split(r"[，,。!！?？、~～]", t)[0].strip() for t in re.findall(r"#([^#\s]+)", title)]
    tags = title_tags + list(seed.get("tags") or [])
    generic_sub = ("好物", "推荐", "分享", "开箱", "测评", "必备", "神器", "生活")
    qs = []
    for t in tags:
        if (t.lower() not in GENERIC_TAGS and CJK.search(t) and 3 <= len(t) <= 12 and t not in qs
                and not any(g in t for g in generic_sub)):
            qs.append(t)
    if qs:
        return qs[:3]
    head = re.sub(r"#\S+|【.*?】|\[.*?\]", " ", title)
    for seg in re.split(r"[，,。!！?？\s|｜]+", head):
        if CJK.search(seg) and 4 <= len(seg) <= 14 and seg not in qs:
            qs.append(seg)
    return qs[:3]


GENERIC_WORDS = ["好物推荐", "好物推薦", "好物分享", "好物", "推荐", "推薦", "分享", "shorts", "short", "chinese",
                 "goodies", "goods", "家居", "生活", "实用", "开箱", "抖音", "小红书", "真的", "太方便了"]


def bigrams(s):
    s = (s or "").lower()
    for g in GENERIC_WORDS:
        s = s.replace(g, " ")
    s = re.sub(r"[^\w\u4e00-\u9fff]", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def text_sim(a, b):
    A, B = bigrams(a), bigrams(b)
    return len(A & B) / max(1, min(len(A), len(B))) if A and B else 0.0


def yt_search(query, n):
    cmd = [sys.executable, "-m", "yt_dlp", "--flat-playlist", "-J", "--no-warnings", f"ytsearch{n}:{query}"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        return [e for e in json.loads(r.stdout).get("entries", []) if e]
    except Exception:
        return []


def keyframes(video, n=6, size=320):
    import cv2
    cap = cv2.VideoCapture(str(video))
    cnt = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    out = []
    for i in range(n):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(cnt * (0.08 + 0.84 * i / max(1, n - 1))))
        ok, fr = cap.read()
        if ok:
            s = size / max(fr.shape[:2])
            out.append(cv2.resize(fr, None, fx=s, fy=s))
    cap.release()
    return out


def frame_feats(frames):
    import cv2
    orb = cv2.ORB_create(600)
    feats = []
    for f in frames:
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        kp, des = orb.detectAndCompute(g, None)
        hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        dh = cv2.resize(g, (17, 16), interpolation=cv2.INTER_AREA)
        dhash = (dh[:, 1:] > dh[:, :-1]).flatten()  # 256bit
        feats.append({"des": des, "nkp": len(kp), "hist": hist, "dhash": dhash})
    return feats


def visual_compare(fa, fb):
    """(상품 유사도 0~1, 중복 여부) - ORB 특징점 매칭 + 색 히스토그램 + dHash"""
    import cv2
    import numpy as np
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    orb_best, hist_best, ham = 0.0, 0.0, []
    for a in fa:
        hb = 256
        for b in fb:
            hist_best = max(hist_best, float(cv2.compareHist(a["hist"], b["hist"], cv2.HISTCMP_CORREL)))
            hb = min(hb, int(np.count_nonzero(a["dhash"] != b["dhash"])))
            if a["des"] is not None and b["des"] is not None and len(a["des"]) > 10 and len(b["des"]) > 10:
                m = [x for x in bf.match(a["des"], b["des"]) if x.distance < 40]
                orb_best = max(orb_best, len(m) / max(1, min(a["nkp"], b["nkp"])))
        ham.append(hb)
    ham.sort()
    duplicate = len(ham) >= 3 and ham[len(ham) // 2] <= 48  # 프레임 절반 이상이 거의 동일 -> 재업로드
    sim = min(1.0, orb_best * 2.5) * 0.6 + max(0.0, hist_best) * 0.4
    return round(sim, 3), duplicate


def quick_korean(video):
    hits = 0
    for f in keyframes(video, n=5, size=960):
        for r in ocr_frame(f, "ko"):
            hc = len(HANGUL.findall(r["text"]))
            if r["score"] >= 0.85 and hc >= 2 and hc / max(1, len(r["text"])) > 0.5:
                hits += 1
    return hits >= 2


def cmd_collect(args):
    import cv2
    import numpy as np
    d = pdir(args.project)
    cfg = config(d)
    cc = cfg["collect"]
    meta = load_json(d / "project.json")
    seeds = [s for s in meta["sources"] if s.get("enabled", True)]
    if not seeds:
        die("기준 원본이 없습니다 (ssm new <프로젝트> <링크> 먼저)")
    seed = seeds[0]
    if args.reset:  # 이전 자동 수집분 삭제 후 다시
        for s in [s for s in meta["sources"] if s.get("auto_collected")]:
            (d / s["file"]).unlink(missing_ok=True)
            for p in (d / "clean").glob(f"src{s['id']}.*"):
                p.unlink(missing_ok=True)
        meta["sources"] = [s for s in meta["sources"] if not s.get("auto_collected")]
    count = args.count or cc["count"]
    queries = args.query or auto_queries(seed)
    if not queries:
        die("검색어를 만들 수 없습니다. --query '상품 중국어 키워드' 를 지정하세요")
    log(f"기준 원본: src{seed['id']} {seed.get('title','')[:50]}")
    log(f"검색어: {queries}")
    ref_text = " ".join([seed.get("title", "")] + queries + [" ".join(seed.get("tags") or [])])
    rep = load_json(d / "analysis" / "report.json", {}) or {}
    for r in rep.get("sources", []):
        if r["id"] == seed["id"]:
            ref_text += " " + " ".join(r.get("original_subtitles", []))
    have = {yt_id(s["url"]) for s in meta["sources"]} | {s.get("vid") for s in meta["sources"]}
    have.discard(None)
    if args.from_dir:  # Aside 등 브라우저로 미리 받아둔 후보 폴더 (mp4 + 같은 이름 .info.json)
        pool = []
        for f in sorted(Path(args.from_dir).glob("*.mp4")):
            info = load_json(f.with_suffix(".info.json"), {}) or {}
            vid = info.get("id") or f.stem
            if vid in have:
                continue
            title = " ".join(x for x in [info.get("title", ""), " ".join(info.get("tags") or [])] if x)
            if len(HANGUL.findall(title)) >= 2:
                continue
            dur = info.get("duration") or probe(f)["duration"]
            pool.append({"vid": vid, "url": info.get("url", str(f)), "title": info.get("title") or f.stem,
                         "duration": dur, "channel": info.get("user", ""), "likes": info.get("likes"),
                         "text_score": round(text_sim(title, ref_text), 3), "query": info.get("query", ""),
                         "file": str(f), "platform": info.get("platform", "local")})
        log(f"후보 폴더: {args.from_dir}  ({len(pool)}개)")
        if not pool:
            die("후보 폴더에 mp4 가 없습니다")
    else:
        pool = collect_youtube(d, queries, cc, have, ref_text, args)
    collect_score(d, meta, seeds, seed, pool, cc, count, queries)


def collect_youtube(d, queries, cc, have, ref_text, args):
    # 1) 검색 + 텍스트 점수
    cands = {}
    for q in queries:
        for e in yt_search(q, cc["search_per_query"]) + yt_search(q + " shorts", cc["search_per_query"]):
            vid = e.get("id")
            dur = e.get("duration") or 0
            title = e.get("title") or ""
            if not vid or vid in have or vid in cands:
                continue
            if not (cc["min_duration"] <= dur <= cc["max_duration"]):
                continue
            if len(HANGUL.findall(title)) >= 2:
                continue
            cands[vid] = {"vid": vid, "url": f"https://www.youtube.com/watch?v={vid}", "title": title,
                          "duration": dur, "channel": e.get("channel") or e.get("uploader") or "",
                          "text_score": round(text_sim(title, ref_text), 3), "query": q}
    pool = sorted(cands.values(), key=lambda c: -c["text_score"])[:args.pool or cc["pool"]]
    log(f"후보 {len(cands)}개 중 상위 {len(pool)}개 다운로드")
    if not pool:
        die("후보가 없습니다. 다른 검색어(--query)로 다시 시도하세요")
    # 2) 다운로드
    cdir = d / "candidates"
    cdir.mkdir(exist_ok=True)
    for c in pool:
        out = cdir / f"{c['vid']}.mp4"
        if not out.exists():
            r = subprocess.run([sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-warnings", "-f",
                                "bv*[height<=1280]+ba/b", "--merge-output-format", "mp4", "-o", str(out), c["url"]],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
        c["file"] = str(out) if out.exists() else None
        c["platform"] = "youtube"
    return pool


def collect_score(d, meta, seeds, seed, pool, cc, count, queries):
    import cv2
    import numpy as np
    # 3) 화면 유사도 / 중복 / 한글 검사
    seed_feats = frame_feats(keyframes(d / seed["file"], n=12))
    other_feats = [frame_feats(keyframes(d / s["file"], n=12)) for s in seeds[1:]]
    chosen_feats = []
    for c in pool:
        if not c["file"]:
            c["reject"] = "다운로드 실패"
            continue
        f = frame_feats(keyframes(c["file"], n=12))
        c["_f"] = f
        c["visual_score"], dup = visual_compare(seed_feats, f)
        if dup or any(visual_compare(o, f)[1] for o in other_feats):
            c["reject"] = "중복(기존 원본과 같은 영상)"
            continue
        if quick_korean(c["file"]):
            c["reject"] = "한글 포함"
            continue
        c["score"] = round(c["text_score"] * cc["w_text"] + c["visual_score"] * (1 - cc["w_text"]), 3)
    ok = sorted([c for c in pool if "score" in c], key=lambda c: -c["score"])
    picked = []
    for c in ok:
        if len(picked) >= count:
            break
        same_meta = any(p["title"] == c["title"] and abs(p["duration"] - c["duration"]) <= 1.5 for p in picked)
        if same_meta or any(visual_compare(p["_f"], c["_f"])[1] for p in picked):
            c["reject"] = "중복(후보끼리 같은 영상)"
            continue
        if c["score"] < cc["min_score"]:
            c["reject"] = f"유사도 낮음({c['score']})"
            continue
        picked.append(c)
    # 4) 프로젝트에 추가
    for c in picked:
        idx = max([s["id"] for s in meta["sources"]] + [-1]) + 1
        dst = d / "sources" / f"src{idx}.mp4"
        shutil.copy(c["file"], dst)
        meta["sources"].append({"id": idx, "url": c["url"], "vid": c["vid"], "file": str(dst.relative_to(d)),
                                "title": c["title"], "description": "", "uploader": c["channel"],
                                "extractor": "Youtube", "tags": [], "enabled": True, "auto_collected": True,
                                "collect_score": c["score"]})
        c["added_as"] = f"src{idx}"
        log(f"추가: src{idx}  점수 {c['score']} (텍스트 {c['text_score']} / 화면 {c['visual_score']})  {c['title'][:50]}")
    save_json(d / "project.json", meta)
    # 5) 비교 시트: 1행 = 기준 원본, 이후 = 후보 (선택된 것 초록 테두리)
    (d / "analysis").mkdir(exist_ok=True)
    rows = []

    def strip(frames, label, color):
        tiles = []
        for fr in frames[:6]:
            t = cv2.resize(fr, (160, int(160 * fr.shape[0] / fr.shape[1])))
            t = cv2.resize(t, (160, 284))
            tiles.append(t)
        while len(tiles) < 6:
            tiles.append(np.zeros((284, 160, 3), np.uint8))
        row = np.hstack(tiles)
        row = cv2.copyMakeBorder(row, 6, 6, 6, 6, cv2.BORDER_CONSTANT, value=color)
        cv2.putText(row, label, (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        return row
    rows.append(strip(keyframes(d / seed["file"]), "SEED src%d" % seed["id"], (255, 255, 255)))
    for c in pool:
        if not c.get("file"):
            continue
        lab = (c.get("added_as", "").upper() or "X") + f" {c.get('score', '-')}"
        col = (0, 200, 0) if c.get("added_as") else (0, 0, 180)
        rows.append(strip(keyframes(c["file"]), lab, col))
    cv2.imwrite(str(d / "analysis" / "collect_sheet.jpg"), np.vstack(rows))
    for c in pool:
        c.pop("_f", None)
    save_json(d / "analysis" / "collect_report.json", {"queries": queries, "candidates": pool})
    log(f"{len(picked)}/{count}개 추가됨. 비교 시트: {d / 'analysis' / 'collect_sheet.jpg'}")
    if len(picked) < count:
        log("목표 개수 미달 -> 다른 중국어 검색어로 다시: ssm collect <프로젝트> --query \"...\" --count <부족분>")
    log("다음: 비교 시트를 보고 다른 상품이면 project.json 에서 enabled=false -> ssm analyze")


# ----------------------------------------------------------------- misc
def cmd_frames(args):
    d = pdir(args.project)
    (d / "analysis").mkdir(exist_ok=True)
    for t in args.times:
        out = d / "analysis" / f"frame_src{args.src}_{t}.jpg"
        vid = d / "clean" / f"src{args.src}.mp4"
        if not vid.exists():
            vid = d / load_json(d / "project.json")["sources"][int(args.src)]["file"]
        grab_frame(vid, t, out)
        log(f"{out}")


def cmd_voices(args):
    import edge_tts

    async def go():
        vs = await edge_tts.list_voices()
        for v in vs:
            if v["Locale"].startswith(args.locale):
                print(v["ShortName"], v["Gender"], ",".join(v.get("VoiceTag", {}).get("VoicePersonalities", []) or []))
    asyncio.run(go())


def cmd_doctor(args):
    ok = True
    for exe in ["ffmpeg", "ffprobe"]:
        p = shutil.which(exe)
        print(f"{exe}: {p or '없음'}")
        ok &= bool(p)
    for mod in ["yt_dlp", "edge_tts", "cv2", "PIL", "rapidocr", "numpy"]:
        try:
            __import__(mod)
            print(f"python {mod}: OK")
        except Exception as e:
            print(f"python {mod}: 실패 {e}")
            ok = False
    cfg = config()
    for k in ["subtitle", "thumbnail", "ad_label", "title_overlay"]:
        print(f"font[{k}]: {resolve_font(cfg[k]['font'])}")
    print("상태:", "정상" if ok else "문제 있음")


def main():
    ap = argparse.ArgumentParser(prog="ssm", description="Shopping Shorts Maker")
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("new"); a.add_argument("project"); a.add_argument("urls", nargs="+")
    a.add_argument("--cookies-browser", default=None); a.set_defaults(func=cmd_new, add=False)
    a = sp.add_parser("add"); a.add_argument("project"); a.add_argument("urls", nargs="+")
    a.add_argument("--cookies-browser", default=None); a.set_defaults(func=cmd_new, add=True)
    a = sp.add_parser("collect"); a.add_argument("project"); a.add_argument("--count", type=int)
    a.add_argument("--query", nargs="*"); a.add_argument("--pool", type=int)
    a.add_argument("--reset", action="store_true"); a.add_argument("--from-dir", default=None)
    a.set_defaults(func=cmd_collect)
    a = sp.add_parser("analyze"); a.add_argument("project"); a.add_argument("--src", type=int, nargs="*", default=None)
    a.set_defaults(func=cmd_analyze)
    a = sp.add_parser("clean"); a.add_argument("project"); a.add_argument("--mode", choices=["blur", "inpaint", "none"])
    a.add_argument("--src", type=int, default=None)
    a.set_defaults(func=cmd_clean)
    a = sp.add_parser("init-script"); a.add_argument("project"); a.add_argument("--force", action="store_true")
    a.set_defaults(func=cmd_init_script)
    a = sp.add_parser("build"); a.add_argument("project"); a.add_argument("--only", choices=["tts", "video", "thumb", "desc"])
    a.set_defaults(func=cmd_build)
    a = sp.add_parser("frames"); a.add_argument("project"); a.add_argument("src"); a.add_argument("times", nargs="+")
    a.set_defaults(func=cmd_frames)
    a = sp.add_parser("voices"); a.add_argument("--locale", default="ko-KR"); a.set_defaults(func=cmd_voices)
    a = sp.add_parser("doctor"); a.set_defaults(func=cmd_doctor)
    args = ap.parse_args()
    PROJECTS.mkdir(exist_ok=True)
    args.func(args)


if __name__ == "__main__":
    main()
