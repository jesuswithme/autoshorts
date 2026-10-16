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
          collects: n.interactInfo?.collectedCount, shares: n.interactInfo?.shareCount,
          cover: (n.imageList?.[0]?.urlDefault || n.imageList?.[0]?.url || ''), time: n.time,
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

  // "1.2万" / "3,456" / "10+" -> 숫자
  num(v) {
    if (v == null) return 0;
    const s = String(v).replace(/,/g, '').trim();
    const m = s.match(/([\d.]+)\s*(万|w|W|만)?/);
    if (!m) return 0;
    return Math.round(parseFloat(m[1]) * (m[2] ? 10000 : 1));
  },

  // 상품/분야로 시드 후보 찾기: 검색 -> 상세(길이·댓글·좋아요·저장) -> 필터 -> 점수순 + 커버 저장
  // 점수 = 댓글*3 + 저장*2 + 좋아요 (댓글 많은 영상 = 구매 문의가 많은 영상)
  async find(page, keywords, dir, { max = 12, check = 18, maxDuration = 90, minDuration = 6 } = {}) {
    const hangul = /[\uac00-\ud7a3]/g;
    const seen = new Set();
    const pool = [];
    for (const kw of keywords) {
      for (const it of await this.search(page, kw, { limit: 20 })) {
        if (!seen.has(it.id)) { seen.add(it.id); pool.push({ ...it, query: kw }); }
      }
    }
    pool.sort((a, b) => this.num(b.likes) - this.num(a.likes));
    await fs.mkdir(dir, { recursive: true });
    const out = [];
    for (const it of pool.slice(0, check)) {
      const n = await this.note(page, it.url);
      await sleep(800 + Math.random() * 1200);
      if (n.error || n.type !== 'video' || !n.video) continue;
      if (!(n.duration >= minDuration && n.duration <= maxDuration)) continue;
      if (((n.title + n.desc).match(hangul) || []).length >= 2) continue;
      const likes = this.num(n.likes), comments = this.num(n.comments), collects = this.num(n.collects);
      const row = { id: n.id, url: n.url, title: n.title || (n.desc || '').replace(/\[话题\]/g, '').slice(0, 60),
        tags: n.tags, duration: n.duration, likes, comments, collects, user: n.user, query: it.query,
        score: comments * 3 + collects * 2 + likes, cover: '' };
      if (n.cover) {
        try {
          const r = await fetch(n.cover.replace(/^http:/, 'https:'), { headers: { Referer: 'https://www.rednote.com/' } });
          if (r.ok) { row.cover = path.join(dir, `${n.id}.jpg`); await fs.writeFile(row.cover, Buffer.from(await r.arrayBuffer())); }
        } catch (e) { /* 커버 없이 진행 */ }
      }
      out.push(row);
    }
    out.sort((a, b) => b.score - a.score);
    const top = out.slice(0, max).map((r, i) => ({ rank: i + 1, ...r }));
    await fs.writeFile(path.join(dir, 'found.json'), JSON.stringify(top, null, 2), 'utf8');
    return top;
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
// 쿠팡 판매 여부 확인 (파트너스용): 상위 상품의 이름·가격·리뷰 수·로켓·광고 여부
globalThis.coupang = {
  async check(page, query, { limit = 6 } = {}) {
    await page.goto('https://www.coupang.com/np/search?q=' + encodeURIComponent(query), { waitUntil: 'domcontentloaded' });
    await sleep(2500);
    return await page.evaluate((limit) => {
      const lis = [...document.querySelectorAll('li[class*=ProductUnit], li.search-product, #product-list > li, ul#productList li')];
      return lis.slice(0, limit).map((li) => {
        const t = li.innerText.replace(/\s+/g, ' ');
        const a = li.querySelector('a[href*="/vp/products/"]');
        const prices = [...t.matchAll(/([\d,]+)원/g)].map((m) => parseInt(m[1].replace(/,/g, ''), 10)).filter((p) => p >= 1000);
        const rvs = [...t.matchAll(/\((\d[\d,]*)\)/g)].map((m) => parseInt(m[1].replace(/,/g, ''), 10));
        return {
          name: (li.querySelector('[class*=name], .name')?.innerText || t).trim().slice(0, 70),
          price: prices.length ? prices[prices.length > 1 && /\d+%/.test(t) ? 1 : 0] : null,
          reviews: rvs.length ? Math.max(...rvs) : 0,
          rocket: /내일\(|오늘\(|로켓/.test(t), ad: /광고\s*$/.test(t),
          url: a ? a.href.split('?')[0] : '',
        };
      });
    }, limit);
  },
};
console.log('xhs + coupang helper loaded');
