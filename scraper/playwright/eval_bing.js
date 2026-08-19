() => {
  const dec = (u) => {
    try {
      let s = (u || "").slice(2);
      s = s.replace(/-/g, "+").replace(/_/g, "/");
      while (s.length % 4) s += "=";
      let r = atob(s);
      try { r = decodeURIComponent(r); } catch (e) {}
      return r;
    } catch (e) { return null; }
  };
  const out = [];
  const sels = ["li.b_algo h2 a", "li.b_algo a.tilk", "ol#b_results li.b_algo h2 a"];
  let nodes = [];
  for (const s of sels) { nodes = document.querySelectorAll(s); if (nodes.length) break; }
  nodes.forEach(a => {
    const bh = a.href || ""; const t = (a.innerText || a.textContent || "").trim();
    if (!bh || !t) return;
    let real = null, host = "";
    try {
      const u = new URLSearchParams(new URL(bh).search).get("u") || "";
      if (u.startsWith("a1")) real = dec(u);
      if (real) host = (() => { try { return new URL(real).host; } catch (e) { return ""; } })();
    } catch (e) {}
    if (!real) real = bh;
    out.push({ title: t.slice(0, 160), href: real, host });
  });
  return { count: out.length, sample: out.slice(0, 10) };
}