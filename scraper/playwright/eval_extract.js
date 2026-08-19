() => {
  const clean = (document.body ? document.body.innerText : "").replace(/\s+/g, " ");
  const blocked = /\b403\b|forbidden|access denied|just a moment|cloudflare/i.test(clean.slice(0, 1600));
  const badTitle = /cookie|privacy|accessibility|menu|navigation|search|welcome|home page|404|not found|403|forbidden|access denied|just a moment|cloudflare|^further information$|^oferta de m.sters oficials$/i;
  const headings = [...document.querySelectorAll("main h1, article h1, [role=main] h1, h1, main h2, article h2")]
    .map(h => (h.innerText || h.textContent || "").replace(/\s+/g, " ").trim())
    .filter(t => t.length >= 4 && t.length <= 200 && !badTitle.test(t));
  let title = headings[0] || (document.title || "").replace(/\s*[|–—-].*$/, "").trim();
  const M = "January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec";
  const DATE = new RegExp("\\b(\\d{1,2}\\s+(?:" + M + ")\\s+20\\d{2}|(?:" + M + ")\\s+\\d{1,2},?\\s*20\\d{2}|\\d{4}-\\d{2}-\\d{2})\\b", "gi");
  const RANGE_NEXT = new RegExp("^\\s*(?:[-–—]|to)\\s*(?:\\d{1,2}\\s+(?:" + M + ")\\s+20\\d{2}|(?:" + M + ")\\s+\\d{1,2},?\\s*20\\d{2}|\\d{4}-\\d{2}-\\d{2})", "i");
  const KW = /(deadline|application|due\s+by|closes?|opens?|submit|non-eu|eu\/eea|\beu\b|round\s*\d|1st\s+round|2nd\s+round|rolling|intake|autumn\s+20\d{2}|spring\s+20\d{2}|apply|admission|opens\s+for)/i;
  const EVENT_LABEL = "(?:open\\s+(?:day|house)|webinar|information\\s+(?:session|event)|virtual\\s+(?:event|session)|fair|conference|graduation|ceremony|orientation|visit\\s+day|meet\\s+(?:us|the\\s+team))";
  const EVENT_BEFORE = new RegExp(EVENT_LABEL + "[^.!?]{0,100}$", "i");
  const EVENT_AFTER = new RegExp("^[^.!?]{0,100}" + EVENT_LABEL, "i");
  const deadlines = [];
  let m;
  while ((m = DATE.exec(clean)) && deadlines.length < 8) {
    const date = m[1].trim();
    if (deadlines.some(x => x.date === date)) continue;
    const start = Math.max(0, m.index - 200);
    const win = clean.slice(start, m.index + 100);
    // Dates attached to events are common on programme pages and are not application deadlines.
    const beforeDate = clean.slice(Math.max(0, m.index - 120), m.index);
    const afterDate = clean.slice(m.index + date.length, m.index + date.length + 120);
    if (EVENT_BEFORE.test(beforeDate) || EVENT_AFTER.test(afterDate)) continue;
    // For an application period, only the range end is a deadline.
    if (RANGE_NEXT.test(afterDate)) continue;
    if (!KW.test(win)) continue;
    let round = "Application";
    if (/rolling/i.test(win)) round = "Rolling";
    else if (/non-eu|non-eea|outside\s+the\s+eu|non\s*e\.?u/i.test(win)) round = "Non-EU";
    else if (/(?:^|\s)eu(?:\s|\/| applicants|\/eea)|eea|within\s+the\s+eu/i.test(win) && !/non/i.test(win)) round = "EU";
    else if (/round\s*2|2nd\s+round/i.test(win)) round = "Round 2";
    else if (/round\s*1|1st\s+round/i.test(win)) round = "Round 1";
    deadlines.push({ round, date });
  }
  const low = clean.toLowerCase();
  const MATS = ["transcript","cv","curriculum vitae","motivation letter","statement of purpose","recommendation","reference letter","letter of recommendation","degree certificate","english proof","language certificate","portfolio","gre","passport","application form"];
  const materials = [];
  const escaped = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  for (const kw of MATS) {
    const hit = new RegExp("(?:^|[^a-z])" + escaped(kw) + "(?:$|[^a-z])", "i").test(low);
    if (hit && !materials.includes(kw)) materials.push(kw);
  }
  let ielts = null, toefl = null, gpa = null, language = null;
  const im = clean.match(/ielts[^0-9]{0,10}(\d[\d.]{1,3})/i); if (im) ielts = im[1];
  const tm = clean.match(/toefl[^0-9]{0,10}(\d{2,3})/i); if (tm) toefl = tm[1];
  const gm = clean.match(/(?:minimum|required|at least)[^.!?]{0,30}(?:gpa|grade point average)[^0-9]{0,12}(\d(?:\.\d{1,2})?)/i)
    || clean.match(/(?:gpa|grade point average)[^0-9]{0,12}(\d(?:\.\d{1,2})?)/i);
  if (gm) gpa = gm[1];
  const lm = clean.match(/(?:english|anglais)[^.!?]{0,80}\b([ABC][12])\b/i)
    || clean.match(/\b([ABC][12])\b[^.!?]{0,80}(?:english|anglais)/i);
  if (lm) language = "English " + lm[1].toUpperCase();
  let subject = "General";
  const tl = title.toLowerCase();
  if (/computer|informatics|data|software|algorithm|\bai\b|artificial intelligence|machine learning/.test(tl)) subject = "Computer Science";
  else if (/electrical|electronic|embed|power|signal|telecomm/.test(tl)) subject = "Electrical Engineering";
  else if (/mechan|robot|mechatron|aerospac|automot/.test(tl)) subject = "Mechanical Engineering";
  else if (/math|statistic/.test(tl)) subject = "Mathematics";
  else if (/physic/.test(tl)) subject = "Physics";
  else if (/civil|architect|construct|environ|geotec/.test(tl)) subject = "Civil/Environmental Engineering";
  else if (/econ|manage|business|finance/.test(tl)) subject = "Economics/Management";
  else if (/biolog|chemistr|life|bio|medical|health/.test(tl)) subject = "Life Sciences";
  return { title: title.slice(0,200), url: location.href, deadlines, materials, ielts, toefl, gpa, language, subject, blocked, len: clean.length };
}
