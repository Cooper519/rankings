const { McpClient } = require('./mcp_client');
const t0 = Date.now();
const log = (...a) => console.log('[' + ((Date.now()-t0)/1000).toFixed(1) + 's]', ...a);
(async () => {
  const c = new McpClient({ headless: false });
  try {
    await c.init();
    log('MCP init done');

    // ---- USNews page 1 ----
    log('USNews navigate page 1 ...');
    try {
      await c.navigate('https://www.usnews.com/education/best-global-universities/rankings?page=1');
      log('USNews nav returned, waiting 3s ...');
      await c.waitFor(3);
      const res = await c.eval(`() => {
        try {
          const st = window.__PAGE_CONTEXT_QUERY_STATE__;
          if (!st) return { ok:false, reason:'no state', winkeys: Object.keys(window).filter(k=>/PAGE|STATE|CONTEXT/i.test(k)) };
          const keys = Object.keys(st);
          let items=null, dk=null;
          for (const k of keys) if (k.endsWith('global-universities/search/index.js')) { dk=k; const d=st[k]&&st[k].data; if (d&&Array.isArray(d.items)) items=d.items; }
          if (!items) return { ok:false, reason:'no items', keys };
          const f = items[0]||null;
          return { ok:true, count: items.length, total: (st[dk]&&st[dk].data&&st[dk].data.total_count)||null, first: f?{name:f.name,country:f.country_name,ranks:f.ranks,stats:f.stats}:null };
        } catch(e){ return { ok:false, reason:'exc', msg:e.message }; }
      }`);
      log('USNews eval:', res.slice(0,600));
    } catch (e) { log('USNews ERROR:', e.message); }

    // ---- QS ----
    log('QS navigate ...');
    try {
      await c.navigate('https://www.topuniversities.com/world-university-rankings');
      log('QS nav returned, waiting 6s ...');
      await c.waitFor(6);
      const res = await c.eval(`() => {
        const html = document.documentElement.innerHTML;
        const cf = /just a moment|cloudflare|cf_chl|challenge-platform|cf-please/i.test(html);
        const scripts = [...document.scripts].map(s=>s.src).filter(s=>/qs-rankings-data|\\.json|\\.txt/i.test(s));
        const dataLinks = [...document.querySelectorAll('a,link,script')].map(a=>a.href||a.src||'').filter(h=>/qs-rankings-data/i.test(h));
        return { title: document.title, url: location.href, cfChallenge: cf, scriptDataUrls: scripts.slice(0,5), dataLinks: dataLinks.slice(0,5), hasTable: !!document.querySelector('table,[class*=ranking],[data-testid*=ranking]') };
      }`);
      log('QS eval:', res.slice(0,600));
    } catch (e) { log('QS ERROR:', e.message); }

  } finally {
    await c.close();
    log('closed');
  }
})().catch(e => { console.error('FATAL', e.message); process.exit(1); });