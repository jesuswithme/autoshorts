// 샤오홍슈(rednote) 헬퍼 - Aside REPL 에서 로드:
//   eval(await fs.readFile('<Aside 스킬 폴더>/scripts/xhs.js', 'utf8'));  (경로는 SKILL.md 참고)
// 이후 globalThis.xhs 사용. 로그인은 rednote.com 도메인 기준 (xiaohongshu.com 링크는 자동 변환).
globalThis.xhs = {
  BASE: 'https://www.rednote.com',

  // 공유 링크(xhslink.com, xiaohongshu.com, rednote.com) -> rednote.com 게시물 URL
  async normalize(page, link) {
    let url = link.trim();
    if (/xhslink\.com/.test(url)) {
      await page.goto(url, { waitUntil: 'domcontentloaded' });
      await sleep(2000);
      url = page.url();
    }
    url = url.replace(/https?:\/\/(www\.)?xiaohongshu\.com/, this.BASE);
    url = url.replace(/\/discovery\/item\//, '/explore/');
    return url;
  },

  // 게시물 상세 (제목, 해시태그, 길이, 좋아요, 영상 주소)
  async note(page, url) {
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    await sleep(2500);
    return await page.evaluate(() => {
      try {
        const m = window.__INITIAL_STATE__.note.noteDetailMap;
        const raw = m._rawValue || m._value || m;
        const n = raw[Object.keys(raw).find((k) => raw[k]?.note?.noteId)]?.note;
        if (!n) return { error: 'no-note (로그인/토큰 확인)', url: location.href };
        const s = n.video?.media?.stream || {};
        let best = null;
        for (const c of ['h264', 'EF4', 'h265', 'EF5', 'av1', 'EF6', 'EF7', 'h266']) {
          for (const x of s[c] || []) {
            if (!best || (x.height || 0) > (best.h || 0)) best = { u: x.masterUrl, backup: x.backupUrls || [], h: x.height, w: x.width, codec: c };
          }
          if (best && (c === 'h264' || c === 'EF4')) break;
        }
        return {
          id: n.noteId, type: n.type, title: n.title || '', desc: n.desc || '',
          tags: (n.tagList || []).map((t) => t.name), duration: n.video?.capa?.duration,
          likes: n.interactInfo?.likedCount, comments: n.interactInfo?.commentCount,
          user: n.user?.nickname, url: location.href.split('#')[0], video: best,
        };
      } catch (e) {
        return { error: e.message, url: location.href };
      }
    });
  },

  // 동영상 검색 -> [{id, url(토큰 포함), title, likes}]
  async search(page, keyword, { limit = 20, scrolls = 2 } = {}) {
    await page.goto(`${this.BASE}/search_result?keyword=${encodeURIComponent(keyword)}&type=51`, { waitUntil: 'domcontentloaded' });
    await sleep(3000);
    await page.evaluate(() => {
      const el = [...document.querySelectorAll('div,span,button')].find((e) => ['동영상', '视频', 'Video', 'Videos'].includes((e.innerText || '').trim()) && e.children.length === 0);
      el?.click();
    });
    await sleep(2500);
    for (let i = 0; i < scrolls; i++) { await page.mouse.wheel(0, 2500); await sleep(1500); }
    const items = await page.evaluate((BASE) => {
      const out = new Map();
      document.querySelectorAll('section').forEach((sec) => {
        const a = [...sec.querySelectorAll('a')].find((x) => /\/search_result\/[0-9a-f]{24}\?xsec_token/.test(x.getAttribute('href') || ''));
        if (!a) return;
        const href = a.getAttribute('href');
        const id = href.match(/[0-9a-f]{24}/)[0];
        const title = (sec.querySelector('.title')?.innerText || sec.innerText.split('\n')[0] || '').trim();
        const likes = sec.querySelector('.count')?.innerText || '';
        const isVideo = !!sec.querySelector('[class*=play]');
        const url = `${BASE}/explore/${href.split('/search_result/')[1].replace(/xsec_source=[^&]*/, 'xsec_source=pc_search')}`;
        if (!out.has(id)) out.set(id, { id, url, title, likes, isVideo });
      });
      return [...out.values()];
    }, this.BASE);
    return items.filter((x) => x.isVideo).slice(0, limit);
  },

  // 영상 + 메타(.info.json) 저장 -> 파일 경로
  async download(note, dir, extra = {}) {
    if (!note?.video?.u) throw new Error('영상 주소 없음: ' + (note?.error || note?.type));
    await fs.mkdir(dir, { recursive: true });
    const urls = [note.video.u, ...(note.video.backup || [])].map((u) => u.replace(/^http:/, 'https:'));
    let buf = null;
    for (const u of urls) {
      try {
        const r = await fetch(u, { headers: { Referer: 'https://www.rednote.com/' } });
        if (r.ok) { buf = Buffer.from(await r.arrayBuffer()); break; }
      } catch (e) { /* 다음 주소 */ }
    }
    if (!buf) throw new Error('다운로드 실패: ' + note.id);
    const mp4 = path.join(dir, `${note.id}.mp4`);
    await fs.writeFile(mp4, buf);
    const title = note.title || (note.desc || '').replace(/\[话题\]/g, '').slice(0, 80);
    const info = { id: note.id, platform: 'xiaohongshu', url: note.url, title, desc: note.desc, tags: note.tags,
      duration: note.duration, likes: note.likes, comments: note.comments, user: note.user, ...extra };
    await fs.writeFile(path.join(dir, `${note.id}.info.json`), JSON.stringify(info, null, 2), 'utf8');
    return mp4;
  },

  // 비슷한 원본 후보 모으기: 검색 -> 상세 확인(길이/한글/중복) -> pool 개 다운로드
  async collect(page, keywords, dir, { pool = 8, maxDuration = 90, minDuration = 6, exclude = [] } = {}) {
    const seen = new Set(exclude);
    const picked = [];
    const hangul = /[\uac00-\ud7a3]/g;
    for (const kw of keywords) {
      const res = await this.search(page, kw, { limit: 20 });
      for (const it of res) {
        if (picked.length >= pool) break;
        if (seen.has(it.id)) continue;
        seen.add(it.id);
        const n = await this.note(page, it.url);
        if (n.error || n.type !== 'video' || !n.video) continue;
        if (!(n.duration >= minDuration && n.duration <= maxDuration)) continue;
        if (((n.title + n.desc).match(hangul) || []).length >= 2) continue;
        try {
          await this.download(n, dir, { query: kw });
          picked.push({ id: n.id, title: n.title, duration: n.duration, likes: n.likes });
          console.log(`  + ${n.id} ${n.duration}s ♥${n.likes} ${n.title.slice(0, 30)}`);
        } catch (e) { console.log('  x', n.id, e.message); }
        await sleep(1200 + Math.random() * 1500); // 과도한 요청 방지
      }
      if (picked.length >= pool) break;
    }
    return picked;
  },
};
console.log('xhs helper loaded');
