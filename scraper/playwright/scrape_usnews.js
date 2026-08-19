const { McpClient } = require('./mcp_client');
const fs = require('fs');
const OUT = '_usnews_raw.json';
const PAGES = 50;
const t0 = Date.now();
const log = (...a) => console.log('[' + ((Date.now()-t0)/1000).toFixed(1) + 's]', ...a);

const EVAL_ITEMS = `() => {
  try {
    const st = window.__PAGE_CONTEXT_QUERY_STATE__;
    if (!st) return { ok:false, reason:'no state' };
    let items=null, dk=null;
    for (const k of Object.keys(st)) if (k.endsWith('global-universities/search/index.js')) { dk=k; const d=st[k]&&st[k].data; if (d&&Array.isArray(d.items)) items=d.items; }
    if (!items) return { ok:false, reason:'no items' };
    const rows = items.map(r => {
      let rank = null;
      for (const x of (r.ranks||[])) if (x.is_ranked) { rank = x.value; break; }
      if (!rank) rank = r.rank_display || null;
      let score = null;
      for (const s of (r.stats||[])) if (/^global score/i.test(s.label||'')) { score = s.value; break; }
      return { name: (r.name||'').trim(), country: (r.country_name||'').trim(), rank, score };
    }).filter(x => x.name && x.rank != null);
    return { ok:true, rows };
  } catch(e){ return { ok:false, reason:'exc', msg:e.message }; }
}`;

(async () => {
  const collected = [];
  const c = new McpClient({ headless: false });
  try {
    await c.init();
    log('init done; scraping USNews pages 1..'+PAGES);
    for (let p = 1; p <= PAGES; p++) {
      const url = 'https://www.usnews.com/education/best-global-universities/rankings?page=' + p;
      try {
        await c.navigate(url);
        await c.waitFor(1.5);
        const txt = await c.eval(EVAL_ITEMS);
        const obj = JSON.parse(txt.replace(/^### Result\s*/, '').split(/\n### Ran Playwright/)[0]);
        if (obj && obj.ok && obj.rows) {
          collected.push(...obj.rows);
          log('p'+p+': +'+obj.rows.length+' (total '+collected.length+')  first='+obj.rows[0].rank+' '+obj.rows[0].name);
        } else {
          log('p'+p+': NO ITEMS', JSON.stringify(obj).slice(0,200));
        }
      } catch (e) {
        log('p'+p+': ERROR '+e.message);
      }
      if (p % 10 === 0) fs.writeFileSync(OUT, JSON.stringify(collected), 'utf8');
    }
    fs.writeFileSync(OUT, JSON.stringify(collected), 'utf8');
    log('DONE: '+collected.length+' rows -> '+OUT);
  } finally {
    await c.close();
  }
})().catch(e => { console.error('FATAL', e.message); process.exit(1); });