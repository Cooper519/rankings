/**
 * CDP-based two-stage official URL discovery for RankingSelect recovery v7.
 * Same logic as v5 but with v6 queue, output dirs, and port.
 */
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PORT = 9370;
const ROOT = 'D:/code Analysis/Rankings';
const RAW_DIR = path.join(ROOT, 'scraper/raw/official-discovery/recovery-v7');
const OUTPUT_DIR = path.join(ROOT, 'scraper/playwright/recovery_v7');
const QUEUE_FILE = path.join(ROOT, 'scraper/playwright/top500_recovery_queue_v7.json');
const sleep = ms => new Promise(r => setTimeout(r, ms));

const DENIED_HOSTS = [
  'wikipedia.org','daad.de','mygermanuniversity.com','studyportals.com',
  'mastersportal.com','findamasters.com','masterstudies.com','educations.com',
  'study.eu','topuniversities.com','timeshighereducation.com','shanghairanking.com',
  'usnews.com','reddit.com','linkedin.com','facebook.com','instagram.com',
  'youtube.com','globalstudyprep.com','globaladmissions.com','university-directory.eu',
  'collegelearners.org','gradcafe.com','gradschools.com','hotcoursesabroad.com',
  'phdportal.com','shortcoursesportal.com','google.com','bing.com','duckduckgo.com',
];

const CATALOG_KEYWORDS = [
  // English
  'master','graduate','postgraduate','msc','meng','m.phil','mphil',
  'program','programme','course','degree','study','admission','apply',
  'tuition','curriculum','catalog','prospectus','ms ','m.sc','m.eng',
  // German
  'studium','studiengang','studiengänge','masterstudiengang','studiengängen',
  'immatrikulation','bewerbung','bewerben','studienangebot','studienangebot',
  'abschluss','masterstudiengänge','studiencounseling','studienangebot',
  // French
  'formation','cursus','candidature','licence','master ','mastère',
  'admission ','scolarité','études','étudier','parcours','diplôme',
  // Spanish/Portuguese
  'posgrado','máster','mestrado','pós-graduação','programa','estudio',
  'admisión','inscripción','inscrição','carreras','grado',
  // Italian
  'corsi','laurea','magistrale','ammissioni','immatricolazione',
  // Japanese
  '大学院','研究科','入試','出願','修士','博士','募集','入学',
  // Turkish
  'bölüm','eğitim','başvuru','lisansüstü',
  // Nordic/Dutch
  'utbildning','masterprogram','programma','opleiding','aanmelding',
  'opiskelu','haku','opinto',
  // Arabic
  'دراسة','ماجستير','قبول','تسجيل','برنامج',
  // Common abbreviations
  'pg ','taught','research','phd',
];
const ENG_CS_KEYWORDS = [
  'engineer','comput','computer science','cs ','electrical','electronic',
  'mechanical','civil','software','data science','machine learning',
  'artificial intelligence','ai','robotics','information technology',
  'it ','cyber','systems','industrial','aerospace','chemical',
  'materials','biomedical','bioengineering',
];
const REQS_KEYWORDS = ['requirement','eligibility','prerequisite','qualification','entry'];
const DEADLINE_KEYWORDS = ['deadline','apply','application','dates','timeline','period','window'];
const DOCS_KEYWORDS = ['document','transcript','recommendation','letter','statement','cv','portfolio','resume'];
const LANG_KEYWORDS = ['language','english','ielts','toefl','pte','cambridge','duolingo','waec'];

function isDenied(url) {
  try { const h = new URL(url).hostname.toLowerCase(); return DENIED_HOSTS.some(d => h.includes(d)); }
  catch { return true; }
}
// Country-code second-level domains that need 3-part registrable domain
const SLD_COUNTRIES = new Set(['uk','jp','kr','au','nz','za','cn','tw','hk','sg','th','in','id','my','ph','vn','tr','eg','sa','ae','br','mx','ar','cl','co','il','gr','pt','ie','pl','hu','ro','ua','cz','sk','si','hr','ee','lv','lt','ng','pk','bd','lk','gh','ke']);
const SLD_PREFIXES = new Set(['ac','co','go','gov','org','net','edu','com','or','ne','gr','mod','mil','sch','nhs','plc','ltd','police','re','asso','fin','med','law','jpd','prd','ens','uni','cri','res','sci']);
function getRegistrableDomain(hostname) {
  const parts = hostname.toLowerCase().split('.');
  if (parts.length >= 3 && SLD_COUNTRIES.has(parts[parts.length-1]) && SLD_PREFIXES.has(parts[parts.length-2])) {
    return parts.slice(-3).join('.');
  }
  return parts.slice(-2).join('.');
}
function isSameDomain(url, baseDomain) {
  try {
    const linkReg = getRegistrableDomain(new URL(url).hostname);
    const baseReg = getRegistrableDomain(baseDomain);
    return linkReg === baseReg;
  } catch { return false; }
}
function matchKeywords(text, keywords) {
  const lower = text.toLowerCase();
  return keywords.some(k => lower.includes(k));
}
function cleanUrl(url) {
  if (!url) return '';
  const hashIdx = url.indexOf('#');
  if (hashIdx >= 0) url = url.substring(0, hashIdx);
  if (url.length > 1 && url.endsWith('/')) url = url.slice(0, -1);
  return url;
}
function isUsefulUrl(url) {
  if (!url || !url.startsWith('http')) return false;
  if (url.includes('#')) return false;
  if (url.startsWith('mailto:') || url.startsWith('tel:') || url.startsWith('javascript:')) return false;
  if (/\.(pdf|jpg|jpeg|png|gif|svg|css|js|ico|woff|woff2|ttf|mp4|mp3|zip|rar)(\?|$)/i.test(url)) return false;
  return true;
}

function makeCdp(ws) {
  let idc = 0; const pending = new Map();
  ws.addEventListener('message', ev => {
    let obj; try { obj = JSON.parse(ev.data); } catch { return; }
    if (obj.id && pending.has(obj.id)) { const {res,rej} = pending.get(obj.id); pending.delete(obj.id); obj.error ? rej(new Error(JSON.stringify(obj.error))) : res(obj.result); }
  });
  return { send(method, params={}) { const id = ++idc; return new Promise((res,rej)=>{ pending.set(id,{res,rej}); ws.send(JSON.stringify({id,method,params})); }); } };
}

function sha256(data) {
  return crypto.createHash('sha256').update(data).digest('hex');
}

function saveRaw(cid, kind, html, url, finalUrl, status, title, extra = {}) {
  const schoolDir = path.join(RAW_DIR, cid);
  fs.mkdirSync(schoolDir, { recursive: true });
  const hash = sha256(html || '');
  const baseName = `${kind}_sha256=${hash}`;
  const htmlPath = path.join(schoolDir, `${baseName}.html`);
  const manifestPath = path.join(schoolDir, `${baseName}.manifest.json`);
  if (html) fs.writeFileSync(htmlPath, html, 'utf-8');
  const manifest = {
    schemaVersion: 1, kind, captureType: 'cdp-browser-rendered',
    requestedUrl: url, finalUrl, title: title || null,
    capturedAt: new Date().toISOString(),
    bytes: html ? Buffer.byteLength(html, 'utf-8') : 0,
    sha256: hash, rawFile: htmlPath, status, ...extra,
  };
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2), 'utf-8');
  return manifest;
}

async function navigateAndWait(c, url, waitMs = 3000) {
  const NAV_TIMEOUT = 15000; // 15s max per page
  const timeoutP = new Promise((_, rej) => setTimeout(() => rej(new Error('NAV_TIMEOUT')), NAV_TIMEOUT));
  try {
    const navResult = await Promise.race([c.send('Page.navigate', { url }), timeoutP]);
    if (navResult.errorText) {
      return { status: 'error', error: navResult.errorText, finalUrl: url };
    }
  } catch (e) {
    return { status: 'error', error: e.message.includes('TIMEOUT') ? 'ERR_NAV_TIMEOUT' : e.message, finalUrl: url };
  }
  await sleep(waitMs);
  try {
    const metricsP = c.send('Runtime.evaluate', {
      expression: 'JSON.stringify({url: location.href, title: document.title, html: document.documentElement.outerHTML, ready: document.readyState})',
      returnByValue: true,
    });
    const metrics = await Promise.race([metricsP, new Promise((_, rej) => setTimeout(() => rej(new Error('EVAL_TIMEOUT')), 5000))]);
    let info = {};
    try { info = JSON.parse(metrics.result.value); } catch { info = { ready: 'unknown' }; }
    return { status: 'ok', finalUrl: info.url, title: info.title, html: info.html, ready: info.ready };
  } catch {
    return { status: 'error', error: 'ERR_EVAL_TIMEOUT', finalUrl: url };
  }
}

async function extractLinks(c, baseUrl) {
  const result = await c.send('Runtime.evaluate', {
    expression: 'JSON.stringify(Array.from(document.querySelectorAll("a[href]")).map(a => ({href: a.href, text: (a.innerText||a.title||"").trim().slice(0,200)})).filter(l => l.href && l.href.startsWith("http") && !l.href.includes("#") && !/\\.(pdf|jpg|jpeg|png|gif|svg|css|js|ico|woff|woff2|ttf|mp4|mp3|zip|rar)(\\?|$)/i.test(l.href)))',
    returnByValue: true,
  });
  try { return JSON.parse(result.result.value); } catch { return []; }
}

async function processSchool(c, item) {
  const cid = item.canonicalId;
  const result = {
    canonicalId: cid, name: item.name, captureStatus: item.captureStatus,
    homepageUrl: item.homepageUrl, visited: [], discoveredUrls: [], errors: [],
  };

  let homeUrl = item.homepageUrl;
  if (!homeUrl) { result.errors.push('no homepage URL'); return result; }

  const baseDomain = (() => { try { return new URL(homeUrl).hostname; } catch { return ''; } })();
  const baseRegDomain = getRegistrableDomain(baseDomain);

  // Stage 1: Visit homepage
  const homeResult = await navigateAndWait(c, homeUrl, 3500);
  if (homeResult.status === 'error') {
    result.errors.push(`homepage: ${homeResult.error}`);
    result.visited.push({ url: homeUrl, status: 'error', error: homeResult.error, kind: 'homepage' });
    saveRaw(cid, 'homepage', homeResult.html || '', homeUrl, homeResult.finalUrl, 'error', null, { error: homeResult.error });
    return result;
  }
  if (!homeResult.html || homeResult.ready === 'loading') await sleep(2000);

  saveRaw(cid, 'homepage', homeResult.html, homeUrl, homeResult.finalUrl, homeResult.ready === 'complete' ? 200 : 'partial', homeResult.title);
  result.visited.push({ url: homeUrl, finalUrl: homeResult.finalUrl, status: 200, kind: 'homepage' });

  const links = await extractLinks(c, homeResult.finalUrl);
  const sameDomainLinks = links.filter(l => !isDenied(l.href) && isSameDomain(l.href, baseDomain));
  const catalogLinks = sameDomainLinks.filter(l => matchKeywords(l.text, CATALOG_KEYWORDS) || matchKeywords(l.href, CATALOG_KEYWORDS));

  result.discoveredUrls.push({ url: cleanUrl(homeResult.finalUrl), type: 'homepage', title: homeResult.title });

  const seen = new Set();
  const uniqueCatalogLinks = catalogLinks.filter(l => {
    if (seen.has(l.href)) return false;
    seen.add(l.href);
    return true;
  }).slice(0, 5);

  // Stage 2: Visit catalog links
  for (const cl of uniqueCatalogLinks) {
    const catResult = await navigateAndWait(c, cl.href, 3000);
    if (catResult.status === 'error') {
      result.errors.push(`catalog ${cl.href}: ${catResult.error}`);
      result.visited.push({ url: cl.href, status: 'error', error: catResult.error, kind: 'catalog' });
      saveRaw(cid, 'catalog', catResult.html || '', cl.href, catResult.finalUrl, 'error', null, { error: catResult.error, linkText: cl.text });
      continue;
    }
    if (!catResult.html) continue;

    const linkTextLower = (cl.text + ' ' + cl.href).toLowerCase();
    let urlType = 'master-catalog';
    if (matchKeywords(linkTextLower, ENG_CS_KEYWORDS)) urlType = 'engineering-cs-catalog';
    else if (matchKeywords(linkTextLower, REQS_KEYWORDS)) urlType = 'admission-requirements';
    else if (matchKeywords(linkTextLower, DEADLINE_KEYWORDS)) urlType = 'application-deadline';
    else if (matchKeywords(linkTextLower, DOCS_KEYWORDS)) urlType = 'required-documents';
    else if (matchKeywords(linkTextLower, LANG_KEYWORDS)) urlType = 'language-requirements';

    saveRaw(cid, urlType, catResult.html, cl.href, catResult.finalUrl, 200, catResult.title, { linkText: cl.text });
    result.visited.push({ url: cl.href, finalUrl: catResult.finalUrl, status: 200, kind: urlType });
    result.discoveredUrls.push({ url: cleanUrl(catResult.finalUrl), type: urlType, title: catResult.title, linkText: cl.text });

    if (urlType === 'master-catalog' || urlType === 'engineering-cs-catalog') {
      const catLinks = await extractLinks(c, catResult.finalUrl);
      const engLinks = catLinks.filter(l => !isDenied(l.href) && isSameDomain(l.href, baseDomain) && matchKeywords(l.text + ' ' + l.href, ENG_CS_KEYWORDS));
      const engSeen = new Set();
      for (const el of engLinks) {
        if (engSeen.has(el.href)) continue;
        engSeen.add(el.href);
        const cleanProgHref = cleanUrl(el.href);
        if (isUsefulUrl(cleanProgHref) && !result.discoveredUrls.some(d => d.url === cleanProgHref)) {
          result.discoveredUrls.push({ url: cleanProgHref, type: 'program-page', title: el.text.slice(0, 100), linkText: el.text });
        }
      }
      for (const el of catLinks) {
        if (isDenied(el.href) || !isSameDomain(el.href, baseDomain)) continue;
        const combined = (el.text + ' ' + el.href).toLowerCase();
        let subType = null;
        if (matchKeywords(combined, REQS_KEYWORDS)) subType = 'admission-requirements';
        else if (matchKeywords(combined, DEADLINE_KEYWORDS)) subType = 'application-deadline';
        else if (matchKeywords(combined, DOCS_KEYWORDS)) subType = 'required-documents';
        else if (matchKeywords(combined, LANG_KEYWORDS)) subType = 'language-requirements';
        const cleanSubHref = cleanUrl(el.href);
        if (subType && isUsefulUrl(cleanSubHref) && !engSeen.has(cleanSubHref)) {
          engSeen.add(cleanSubHref);
          result.discoveredUrls.push({ url: cleanSubHref, type: subType, title: el.text.slice(0, 100), linkText: el.text });
        }
      }
    }
  }
  return result;
}

async function run() {
  fs.mkdirSync(RAW_DIR, { recursive: true });
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });

  const queue = JSON.parse(fs.readFileSync(QUEUE_FILE, 'utf-8'));
  const items = queue.items;

  const args = process.argv.slice(2);
  const limitIdx = args.indexOf('--limit');
  const limit = limitIdx >= 0 ? parseInt(args[limitIdx + 1]) : 10;
  const offsetIdx = args.indexOf('--offset');
  const offset = offsetIdx >= 0 ? parseInt(args[offsetIdx + 1]) : 0;

  const batch = items.slice(offset, offset + limit);
  console.log(`Recovery v7: processing ${batch.length} schools (offset=${offset}, limit=${limit})`);

  const profileDir = os.tmpdir() + '/cdp-recovery-v7';
  const chrome = spawn(CHROME, [
    '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + profileDir,
    '--headless=new',
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    '--window-size=1440,900',
    '--ignore-certificate-errors',
  ], { stdio: 'ignore' });
  chrome.unref();

  let target = null;
  for (let i = 0; i < 40; i++) {
    try {
      const tabs = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json();
      const page = tabs.find(t => t.type === 'page');
      target = page ? page.webSocketDebuggerUrl : null;
      if (target) break;
    } catch { }
    await sleep(250);
  }
  if (!target) { console.error('NO CDP TARGET'); chrome.kill(); process.exit(2); }

  const ws = new WebSocket(target);
  await new Promise((res, rej) => { ws.addEventListener('open', res, { once: true }); ws.addEventListener('error', rej, { once: true }); });
  const c = makeCdp(ws);
  await c.send('Page.enable');
  await c.send('Runtime.enable');
  await c.send('Network.enable');

  const results = [];
  for (let i = 0; i < batch.length; i++) {
    const item = batch[i];
    process.stdout.write(`[${i + 1}/${batch.length}] ${item.canonicalId} (${item.captureStatus})... `);
    try {
      const result = await processSchool(c, item);
      results.push(result);
      const urlCount = result.discoveredUrls.length;
      const errCount = result.errors.length;
      console.log(`found ${urlCount} URLs, ${errCount} errors, visited ${result.visited.length} pages`);
    } catch (e) {
      console.log(`FATAL: ${e.message}`);
      results.push({ canonicalId: item.canonicalId, name: item.name, errors: [e.message], discoveredUrls: [], visited: [] });
    }
    // Save incrementally
    fs.writeFileSync(path.join(OUTPUT_DIR, 'partial_results.json'), JSON.stringify({ generatedAt: new Date().toISOString(), batch: { offset, limit }, results }, null, 2), 'utf-8');
    await sleep(500);
  }

  ws.close();
  chrome.kill();

  const outFile = path.join(OUTPUT_DIR, `batch_${offset}_${offset + limit}.json`);
  fs.writeFileSync(outFile, JSON.stringify({ generatedAt: new Date().toISOString(), results }, null, 2), 'utf-8');

  const totalUrls = results.reduce((s, r) => s + r.discoveredUrls.length, 0);
  const totalErrors = results.reduce((s, r) => s + r.errors.length, 0);
  const totalVisited = results.reduce((s, r) => s + r.visited.length, 0);
  const successCount = results.filter(r => r.discoveredUrls.length > 0).length;
  console.log(`\nSummary: ${successCount}/${results.length} schools found URLs, ${totalUrls} total URLs, ${totalVisited} pages visited, ${totalErrors} errors`);
  console.log(`Results saved: ${outFile}`);
  console.log('DONE');
}

run().catch(e => { console.error('FATAL', e); process.exit(1); });
