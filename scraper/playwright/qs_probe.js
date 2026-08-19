const { McpClient } = require('./mcp_client');
const t0 = Date.now();
const log = (...a) => console.log('[' + ((Date.now()-t0)/1000).toFixed(1) + 's]', ...a);

(async () => {
  const c = new McpClient({ headless: false });
  try {
    await c.init();
    log('navigate QS ...');
    await c.navigate('https://www.topuniversities.com/world-university-rankings');
    await c.waitFor(8);
    const probe = await c.eval(`() => {
      const out = { title: document.title, url: location.href };
      out.hasNextData = !!window.__NEXT_DATA__;
      if (window.__NEXT_DATA__) {
        const nd = window.__NEXT_DATA__;
        out.ndPage = nd.page;
        out.ndPropsKeys = nd.props ? Object.keys(nd.props) : [];
        out.ndPropsPageKeys = nd.props && nd.props.pageProps ? Object.keys(nd.props.pageProps) : [];
        // stringify pageProps to estimate size and peek
        try { const s = JSON.stringify(nd.props.pageProps); out.ndPagePropsSize = s.length; out.ndPagePropsPeek = s.slice(0, 500); } catch(e){ out.ndErr = e.message; }
      }
      // table / cards
      out.tableCount = document.querySelectorAll('table').length;
      const nd2 = window.__NEXT_DATA__ && ndKeys(window.__NEXT_DATA__);
      return out;
      function ndKeys(o){ if(!o||typeof o!=='object')return null; const r={}; for(const k of Object.keys(o)){ const v=o[k]; r[k]= typeof v==='object' && v? (Array.isArray(v)?'array:'+v.length:'obj') : typeof v; } return r; }
    }`);
    log('__NEXT_DATA__ probe:', probe.slice(0, 1200));

    log('--- network requests (non-static) ---');
    const nr = await c.call('browser_network_requests', { static: false });
    const txt = McpClient.text(nr);
    const lines = txt.split('\n').filter(l => /\[\d+\]/.test(l));
    log('total non-static requests:', lines.length);
    lines.forEach(l => console.log('  ' + l.slice(0, 200)));
  } finally {
    await c.close();
  }
})().catch(e => { console.error('FATAL', e.message); process.exit(1); });