// 网页端到端核查：真实浏览器里点一遍，把每步结果打印出来并截图。
const path = require("path");
const { chromium } = require("C:/Users/qq165/Documents/deepseek-harness/default-workspace/wsv/repo/node_modules/playwright");

const OUT = "C:/Users/qq165/Documents/deepseek-harness/default-workspace/gandan_scratch";
const BASE = "http://127.0.0.1:8765/";

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: Boolean(ok), detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  → " + detail : ""}`);
}

(async () => {
  const browser = await chromium.launch({ channel: "msedge" });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

  const consoleErrors = [];
  page.on("pageerror", (e) => consoleErrors.push("pageerror: " + e.message));
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("response", (r) => { if (r.status() >= 400) consoleErrors.push(`HTTP ${r.status()} ${r.url()}`); });

  const state = () => page.evaluate(() => fetch("/api/state").then((r) => r.json()));

  // 0. 先开一局新的，避免服务端还停着上一局已经结束的牌局
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.evaluate(() =>
    fetch("/api/new", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ level: "2" }),
    })
  );
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  // 1. 初始渲染
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.waitForTimeout(600);
  const hand0 = await page.locator("#hand .card").count();
  check("初始手牌 27 张", hand0 === 27, `实际 ${hand0}`);
  check("状态栏可见", (await page.locator("#status").innerText()).length > 0,
        await page.locator("#status").innerText());
  check("按钮齐全", (await page.locator("#playBtn").count()) === 1 &&
                    (await page.locator("#passBtn").count()) === 1 &&
                    (await page.locator("#hintBtn").count()) === 1);
  await page.screenshot({ path: path.join(OUT, "ui_1_initial.png") });

  // 2. 选牌：点一张选中，再点取消
  await page.locator("#hand .card").first().click();
  let sel = await page.locator("#hand .card.selected").count();
  check("点一张牌只选中一张", sel === 1, `选中 ${sel}`);
  await page.locator("#hand .card").first().click();
  sel = await page.locator("#hand .card.selected").count();
  check("再点一次取消选中", sel === 0, `选中 ${sel}`);

  // 3. 重复牌不会被绑在一起（两张同点数不同花色的牌）
  const dupInfo = await page.evaluate(() => {
    const cards = [...document.querySelectorAll("#hand .card")];
    const ranks = cards.map((c) => c.querySelector(".rank").textContent);
    const map = {};
    ranks.forEach((r, i) => { (map[r] = map[r] || []).push(i); });
    const dup = Object.entries(map).find(([, v]) => v.length >= 2);
    return dup ? { rank: dup[0], idx: dup[1][0] } : null;
  });
  if (dupInfo) {
    await page.locator("#hand .card").nth(dupInfo.idx).click();
    const one = await page.locator("#hand .card.selected").count();
    check("同点数两张牌只选一张", one === 1, `点数 ${dupInfo.rank}，选中 ${one}`);
    await page.locator("#hand .card").nth(dupInfo.idx).click();
  } else {
    check("同点数两张牌只选一张", true, "本局没有重复点数，跳过");
  }

  // 4. 提示 → 选中 → 出牌
  await page.locator("#hintBtn").click();
  await page.waitForTimeout(300);
  const hintCount = await page.locator(".hint-btn").count();
  check("提示给出可行出牌", hintCount > 0, `${hintCount} 条`);
  if (hintCount > 0) {
    await page.locator(".hint-btn").first().click();
    const picked = await page.locator("#hand .card.selected").count();
    check("点提示会自动选中对应手牌", picked > 0, `选中 ${picked} 张`);
    await page.locator("#playBtn").click();
    await page.waitForTimeout(800);
    const st = await state();
    check("出牌后手牌减少", st.hand.length < 27, `剩 ${st.hand.length} 张`);
    check("出牌流水有记录", (st.history || []).length > 0, `${(st.history || []).length} 条`);

    // 本轮被所有人过掉时，桌面必须保留「上一手」，不能变成空白
    const tableCards = await page.locator("#played .card").count();
    const tableLabel = await page.locator("#tableLabel").innerText();
    check("桌面保留牌面（不会凭空消失）", tableCards > 0, `${tableCards} 张`);
    check("桌面标题写明是谁的牌", tableLabel.includes("打出"), tableLabel);

    await page.screenshot({ path: path.join(OUT, "ui_2_after_play.png") });
  }

  // 5. 流水面板渲染
  const rows = await page.locator("#logList .log-row").count();
  check("流水面板显示每一手", rows > 0, `${rows} 行`);

  // 6. 新的一局
  await page.locator("#newBtn").click();
  await page.waitForTimeout(700);
  const handNew = await page.locator("#hand .card").count();
  const rowsNew = await page.locator("#logList .log-row").count();
  check("新局手牌回到 27 张", handNew === 27, `${handNew} 张`);
  check("新局流水清空", rowsNew === 0, `${rowsNew} 行`);

  // 7. 打完一局（用接口推演，再看界面是否显示结算）
  const finished = await page.evaluate(async () => {
    for (let i = 0; i < 800; i++) {
      const s = await fetch("/api/state").then((r) => r.json());
      if (s.game_over) return s;
      if (!s.your_turn) { await new Promise((r) => setTimeout(r, 60)); continue; }
      if (s.can_pass && Math.random() < 0.15) {
        await fetch("/api/pass", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
        continue;
      }
      const legal = await fetch("/api/legal").then((r) => r.json());
      if (!legal.plays || !legal.plays.length) continue;
      await fetch("/api/play", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cards: legal.plays[0] }),
      });
    }
    return null;
  });

  if (finished) {
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForTimeout(600);
    const overlayShown = await page.locator("#overlay.show").count();
    check("对局结束后弹出结算", overlayShown === 1);
    const ranking = await page.locator("#rankingList li").count();
    check("结算里列出四个名次", ranking === 4, `${ranking} 条`);
    await page.screenshot({ path: path.join(OUT, "ui_3_game_over.png") });
  } else {
    check("对局能打完", false, "800 次操作内没有结束");
  }

  check("无 JS 报错与 4xx", consoleErrors.length === 0, consoleErrors.slice(0, 3).join(" | "));

  await browser.close();

  const failed = results.filter((r) => !r.ok);
  console.log("\n结果：", results.length - failed.length, "/", results.length, "通过");
  process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error("AUDIT FAILED", e.message); process.exit(2); });
