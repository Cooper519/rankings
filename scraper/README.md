# RankingSelect Scraper

æŠ“å–äº”å¤§æ¦œå•æŽ’åä¸Žé¡¹ç›®ç”³è¯·æƒ…æŠ¥,è¾“å‡ºé™æ€ JSON ä¾›å‰ç«¯åŠ è½½ã€‚çº¯ stdlib å®žçŽ°(urllib),
**æ— éœ€ pip å®‰è£…å³å¯è¿è¡Œ**(requirements.txt ä»…å¤‡é€‰)ã€‚

## æ•°æ®ç›®æ ‡

| æ•°æ® | æ¥æº | æ–¹å¼ | ç»“æž„åŒ– |
|------|------|------|--------|
| äº”æ¦œæŽ’å | QS/THE/ARWU/USNews/CS Rankings | çˆ¬è™«/å¼€æºæ•°æ® | å…¨ç»“æž„åŒ– |
| é™¢æ ¡ä¿¡æ¯ | æ¦œå•èšåˆåŽ»é‡ | èšåˆè„šæœ¬ | ç»“æž„åŒ– |
| é¡¹ç›®ç”³è¯·æƒ…æŠ¥ | å„é¡¹ç›®å®˜æ–¹é¡µ | æŠ“å– + éƒ¨åˆ†ç»“æž„åŒ– + äººå·¥æ ¡å¯¹ | éƒ¨åˆ† + æºé“¾æŽ¥ |

## è¾“å‡º

æ‰€æœ‰ JSON è¾“å‡ºè‡³ ../frontend/public/data/:
- rankings/{qs,the,arwu,usnews,csrankings}.json  æ¯æ¦œå‰ 500(USNews å—é™)
- universities.json  äº”æ¦œåŽ»é‡èšåˆ
- programs.json  ç¡•å£«é¡¹ç›®ç”³è¯·æƒ…æŠ¥

## ä½¿ç”¨

```bash
$env:HTTP_PROXY="http://127.0.0.1:7897"; $env:HTTPS_PROXY="http://127.0.0.1:7897"
$env:PYTHONIOENCODING="utf-8"

python main.py --source qs          # æŠ“å•æ¦œ
python main.py                      # å…¨éƒ¨äº”æ¦œ + èšåˆ + programs(ç§å­)
python -m programs.build_programs --scrape   # å¯¹ç§å­ sourceUrl å¯å‘å¼æŠ“å–(verified=False)
```

## äº”æ¦œæŠ“å–çŽ°çŠ¶(2026-08)

| æ¦œå• | ç«¯ç‚¹/æ–¹å¼ | æ¡ç›® | å¤‡æ³¨ |
|------|-----------|------|------|
| THE | æŽ’åé¡µå†…åµŒ __NEXT_DATA__ JSON | 500 | OK |
| ARWU | shanghairanking.com/api/pub/v1/arwu/rank | 500 | OK |
| CS Rankings | GitHub emeryberger/csrankings å¼€æº CSV | 500 | OK(æŒ‰ä½œè€…æ•°ä»£ç†æŽ’åº,æœ‰å·²çŸ¥åå·®) |
| QS | ç«™ç‚¹æ•°æ®ç«¯ç‚¹è¢« Cloudflare JS challenge æ‹¦æˆª -> Wayback Machine å½’æ¡£å›žé€€ | 500 | OK(2025 ç‰ˆ,MIT #1) |
| USNews | ç«™ç‚¹é‡åº¦ SSR + ä»˜è´¹å¢™,å•é¡µ 60-90s è¶…æ—¶ -> Wayback åˆ†é¡µå¿«ç…§(10/é¡µ) | 276 | å½’æ¡£ä¸è¿žç»­,åæ¬¡æœ‰ç©ºç¼º(ranks 1-140 å®Œæ•´,141-500 éƒ¨åˆ†),å¾…äººå·¥è¡¥å½• |

### QS / USNews æŠ“å–ç­–ç•¥è¯´æ˜Ž
ä¸¤ç«™ live ç«¯ç‚¹åˆ†åˆ«å— Cloudflare ä¸Žä»˜è´¹å¢™é™åˆ¶,çº¯ urllib æ— æ³•ç›´å–,é‡‡ç”¨ Wayback Machine å½’æ¡£:
- QS:æŠ“å–å½’æ¡£çš„ä¸–ç•ŒæŽ’åé™æ€æ•°æ®æ–‡ä»¶(.../qs-rankings-data/en/3897789.txt),å« 1498 æ‰€ã€‚
- USNews:CDX æ£€ç´¢ ?page=N çš„å½’æ¡£å¿«ç…§,é€é¡µè§£æž __PAGE_CONTEXT_QUERY_STATE__ã€‚
å½’æ¡£ç¼ºå¤±é¡µåœ¨æŽ§åˆ¶å°æ‰“å°(USNews: å½’æ¡£ç¼ºå¤±é¡µ(åæ¬¡æœ‰ç©ºç¼º,å¾…äººå·¥è¡¥å½•): [...])ã€‚
æœªæ¥è‹¥éœ€ live å¢žé‡,å¯åœ¨è£…æœ‰ Selenium/Playwright çš„æœºå™¨æ›¿æ¢å¯¹åº”æ¨¡å—ã€‚

## é¡¹ç›®ç”³è¯·æƒ…æŠ¥(programs)

scraper/programs/:
- schema.py  æ•°æ®æ¨¡åž‹(å¯¹é½ frontend/src/types/index.ts çš„ Program)
- seed.py  äººå·¥æ•´ç†ç§å­(verified=True,èšç„¦æ¬§é™†é‡ç‚¹é™¢æ ¡:ETH/EPFL/TUM/KTH/TU Delft/KU Leuven/PoliMi/Chalmers/Aalto/Sorbonne/DTU/TU Dresden)
- programs_scraper.py  å¯å‘å¼æŠ“å–å®˜æ–¹é¡µ(deadline/ææ–™/è¯­è¨€è¦æ±‚çº¿ç´¢,verified=False)
- build_programs.py  èšåˆè¾“å‡º programs.json

æ¯ä¸ª program å« sourceUrl(å®˜æ–¹æº)ã€verified(æ ¡å¯¹çŠ¶æ€)ã€updatedAtã€‚ç”³è¯·ç±»ä¿¡æ¯ä»¥å®˜æ–¹æºä¸ºå‡†,æŠ“å–ç»“æžœéœ€äººå·¥æ ¡å¯¹çº æ­£(ç§å­å·²æ ¡å¯¹)ã€‚

## çŽ¯å¢ƒæ³¨æ„
- Python 3.8 æ—§ç‰ˆ pip åœ¨ç³»ç»Ÿä»£ç†ä¸‹å¯èƒ½æŸå;æœ¬çˆ¬è™«ç”¨ stdlib urllib,æ— ä¾èµ–ã€‚
- è®¾ç½® HTTP_PROXY/HTTPS_PROXY èµ°ä»£ç†;ä¸è®¾åˆ™ç›´è¿žã€‚
- OUTPUT_DIR å·² .resolve(),é¿å…ç›¸å¯¹ __file__ è¯¯å†™åµŒå¥—ç›®å½•ã€‚


## Playwright MCP æŠ“å–(USNews / QS live)

éƒ¨åˆ†æ¦œå•(QSã€USNews)è¢« Cloudflare JS challenge æ‹¦æˆª,çº¯ urllib æ— æ³•é€šè¿‡ã€‚æ”¹ç”¨
`@playwright/mcp` MCP server(headed chromium,èµ° Clash ä»£ç†)åœ¨æµè§ˆå™¨å†…æ‰§è¡ŒæŠ“å–ã€‚
ä¸åœ¨é¡¹ç›®å†…å®‰è£… Playwright;æµè§ˆå™¨äºŒè¿›åˆ¶å¤ç”¨ `ms-playwright` ç¼“å­˜ã€‚

- MCP client:`scraper/playwright/mcp_client.js`(spawn `npx.cmd -y @playwright/mcp@latest`,
  stdio JSON-RPC,å°è£… navigate/eval/waitFor/close)
- USNews:`scraper/playwright/scrape_usnews.js`(50 é¡µé€é¡µ navigate,è¯» `__PAGE_CONTEXT_QUERY_STATE__`)
  â†’ `_usnews_raw.json` â†’ `assemble_usnews.py` â†’ `rankings/usnews.json`(year=2025)
- QS:`scraper/playwright/scrape_qs.js`(è¿‡ Cloudflare åŽé¡µé¢å†… `fetch('/rankings/endpoint?nid=4153156...')`,
  items_per_page=600 å•é¡µå–å‰ 600)â†’ `_qs_raw.json` â†’ `assemble_qs.py` â†’ `rankings/qs.json`(year=2027)
- æŽ¢æµ‹:`qs_probe.js` / `qs_probe2.js`(ç¡®è®¤ç«¯ç‚¹ç»“æž„ `score_nodes`)

è¿è¡Œ(å·¥ä½œåŒºæ ¹ç›®å½•):
```
node scraper\playwright\scrape_qs.js
python assemble_qs.py
python scraper\build_universities.py
```

æ³¨æ„:`browser_evaluate` è¿”å›žæ–‡æœ¬å½¢å¦‚ `### Result\n{json}\n### Ran Playwright code...`,
è§£æžç”¨ `txt.replace(/^### Result\s*/,'').split(/\n### Ran Playwright/)[0]` å† `JSON.parse`ã€‚
## ç¡•å£«é¡¹ç›®ç”³è¯·æƒ…æŠ¥æŠ“å–(Playwright MCP)

é’ˆå¯¹æ¬§é™†ç›®æ ‡é™¢æ ¡çš„è‹±æŽˆç¡•å£«é¡¹ç›®,ç”¨ Playwright MCP å‘çŽ°å¼æŠ“å– deadline/ææ–™/è¯­è¨€è¦æ±‚ã€‚

- ç›®å½•é…ç½®:`scraper/playwright/program_catalog.json`(12 æ‰€æ¬§é™†ç›®æ ‡é™¢æ ¡çš„ç¡•å£«é¡¹ç›®åˆ—è¡¨é¡µ URL)
- å‘çŽ°è„šæœ¬:`scraper/playwright/eval_discover.js`(åˆ—è¡¨é¡µå†…æŠ½å–è‹±æŽˆç¡•å£«é¡¹ç›®é“¾æŽ¥,æŒ‰å­è·¯å¾„+å…³é”®è¯è¯„åˆ†æŽ’åº)
- æŠ½å–è„šæœ¬:`scraper/playwright/eval_extract.js`(é¡¹ç›®é¡µæ¸²æŸ“åŽæ­£åˆ™æå– deadline/ææ–™/IELTS/TOEFL,çŒœå­¦ç§‘)
- é©±åŠ¨:`scraper/playwright/scrape_programs.js`(é€æ ¡ navigate åˆ—è¡¨é¡µâ†’å‘çŽ°â†’é€é¡¹ç›®é¡µæŠ½å–â†’`_programs_raw.json`)
- è£…é…:`assemble_programs.py`(ç§å­ verified=True + æŠ“å– verified=False åˆå¹¶,è¿‡æ»¤ hub/info å™ªéŸ³é¡µ,
  æŒ‰ universityId+program åŽ»é‡,ç§å­ä¼˜å…ˆ)â†’ `frontend/public/data/programs.json`

è¿è¡Œ(å·¥ä½œåŒºæ ¹):
```
node scraper\playwright\scrape_programs.py [catalog.json]   # é»˜è®¤ program_catalog.json
python assemble_programs.py
```

è¯´æ˜Ž:æŠ“å–ä¸ºå¯å‘å¼ã€verified=False,éœ€äººå·¥æ ¡å¯¹(äº§å“æ¨¡åž‹:æŠ“å–+ç»“æž„åŒ–+äººå·¥æ ¡å¯¹,ä¿ç•™ sourceUrl)ã€‚
éƒ¨åˆ†é™¢æ ¡(ETH/EPFL/KTH/PoliMi/Aalto ç­‰)åˆ—è¡¨é¡µä¸ºæœç´¢ hub,å‘çŽ°æœªèƒ½åˆ°è¾¾çœŸå®žé¡¹ç›®é¡µ,
è¿™äº›é™¢æ ¡ç”±ç§å­(verified=True)è¦†ç›–ã€‚Chalmers/DTU/TU Delft/TUM å‘çŽ°æ•ˆæžœå¥½,æœ‰æ•ˆæ‰©å……è¦†ç›–ã€‚
### å¢žå¼º(2026-08)

- **äºŒæ®µå‘çŽ°**:å¯¹ ETH/EPFL/KTH/PoliMi/Aalto ç­‰ hub åž‹åˆ—è¡¨é¡µ,æ”¹ä¸ºå…ˆå®šä½ã€Œé¡¹ç›®åˆ—è¡¨å­é¡µã€
  å†å‘çŽ°é¡¹ç›®(`program_catalog.json` å·²æ›´æ–°ä¸ºå„æ ¡é¡¹ç›®åˆ—è¡¨ç›´é“¾;EPFL/PoliMi/Aalto è¡¥åˆ°çœŸå®žé¡¹ç›®)ã€‚
- **deadline åŽå¤„ç†**:`scraper/programs/normalize.py` â€”â€” è§£æž "9 June 2026"â†’ISOã€è¿‡æ»¤ä»Šå¤©ä¹‹å‰
  çš„è¿‡åŽ»æ—¥æœŸã€ä¿ç•™ Non-EU/EU/Round 1/Rolling è½®æ¬¡æ ‡ç­¾ã€‚è£…é…æ—¶å¯¹æŠ“å–æ•°æ®ç»Ÿä¸€è§„èŒƒåŒ–
  (ç§å­ verified æ•°æ®çš„ deadline ä¿æŒåŽŸæ ·)ã€‚
- **å‰ç«¯å¾…æ ¡å¯¹æ ‡è®°**:`Me.tsx` é¡¹ç›®å¡æ–°å¢ž å·²æ ¡å¯¹/å¾…æ ¡å¯¹ å¾½ç« (ç»¿/é»„),ä¸Ž `University.tsx` ä¸€è‡´;
  ä¸¤å¤„å‡ä¿ç•™ã€Œå®˜æ–¹æº â†—ã€ä¸€é”®è·³è½¬ sourceUrlã€‚
- æŠ“å–æ•°æ® verified=False,deadline å¤šä¸ºç©º(æ¬§é™†é™¢æ ¡ deadline é›†ä¸­åœ¨ admissions é¡µ,éžé¡¹ç›®é¡µ),
  ä»¥ç§å­(verified=True)ä¸ºå¯ä¿¡æ¥æº,æŠ“å–ä¸»è¦è¡¥è¦†ç›–(é¡¹ç›®å+sourceUrl+ææ–™çº¿ç´¢)ã€‚

## 2026-08-10 全量爬虫(stage 1) + 阶段丙(round 1)

**目标**:对全部欧陆(除英爱)院校逐一抓取英授硕士申请情报(deadline/材料/语言)。

**stage 1 全量爬虫**:`scraper/playwright/scrape_all_programs.js`
- 对 `program_catalog_all.json` 中 327 所院校逐一执行:Bing 搜索定位项目列表页 → L2 discover 发现项目链接 → extract 抽取(deadline/轮次/材料/IELTS/TOEFL/学科)
- 通过 `@playwright/mcp`(headed,过 Cloudflare),代理 127.0.0.1:7897,resumable(`_crawl_progress.json`/`_programs_all_raw.json`)
- 结果:**327/327 done,850 raw records**(261 所满 3 条;24 所 0 条多为 JS 渲染列表页 discover=0)

**阶段丙 round 1**:`scraper/playwright/program_catalog_fix.json` + `scrape_programs.js`
- 对 12 所 crawler 失败院校(Leiden/Padua/Seville/Valencia/INRIA/Jean Monnet/Montpellier/Goethe/TU Dresden/Siena/Ramon Llull)提供人工核实的英文硕士列表 indexUrl 重抓
- 8 所列表页 JS 渲染(discover=0),仅 Padua/Siena 产出 → +5 条(经 junk 过滤)

**装配**:`scraper/programs/assemble_all.py`
- 合并 seed(15 verified)+ L2 `_programs_raw.json` + 全量 `_programs_all_raw.json`
- `normalize_deadlines`:解析 ISO、过滤 < 2026-08-10、区分 Non-EU/EU/Round
- junk 过滤:cookie/导航/首页/新闻/活动/404 等噪声标题 → 丢弃 63 条
- 去重:verified 种子优先;(universityId + 规范化 program 名)唯一

**最终 programs.json**:**741 条**(15 verified + 726 unverified 待校对),覆盖 **286 所院校**
- with deadlines: 52 | with materials: 663 | with ielts: 15
- 学科分布:General 571(hub/列表页占位,带 sourceUrl 供丙阶段深挖)/ CS 42 / Life 36 / Econ 31 / Civil 24 / Mech 17 / Phys 8 / Math 7 / EE 3
- 前端:`Me.tsx` + `University.tsx` 已有「已校对/待校对」徽章 + sourceUrl 一键跳转;`tsc -b && vite build` 通过

**下一步(阶段丙 round 2)**:
- 对 571 条 General 占位记录与 8 所 JS 渲染失败院校,人工逐项目核实 sourceUrl → 补 deadline/材料/语言,verified=true
- 重点校:ETH/EPFL/KTH/PoliMi/Aalto 已 verified 种子;TUM/TU Delft/KU Leuven/Chalmers/DTU/Sorbonne/TU Dresden 待升级 verified