import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

test("builds the local dashboard shell", async () => {
  const html = await readFile(new URL("dist/index.html", root), "utf8");
  assert.match(html, /FIRE · 本地资产控制台/);
  assert.doesNotMatch(html, /codex-preview|react-loading-skeleton/);
});

test("keeps the app local and broker-free", async () => {
  const source = await readFile(new URL("src/App.tsx", root), "utf8");
  assert.match(source, /仅在本机保存/);
  assert.doesNotMatch(source, /broker|券商登录/i);
});

test("opens fund details from the whole card", async () => {
  const source = await readFile(new URL("src/App.tsx", root), "utf8");
  assert.match(source, /aria-label={`查看 \$\{fund\.name \|\| fund\.fund_code\} 详情`}/);
  assert.match(source, /SNAPSHOT HISTORY/);
  assert.match(source, /查看详情 →/);
});

test("requires an in-app second confirmation before deleting a fund", async () => {
  const source = await readFile(new URL("src/App.tsx", root), "utf8");
  assert.match(source, /SECOND CONFIRMATION/);
  assert.match(source, /确认删除/);
  assert.doesNotMatch(source, /window\.confirm/);
});

test("marks daily limits as not applicable to exchange-traded ETFs", async () => {
  const source = await readFile(new URL("src/App.tsx", root), "utf8");
  assert.match(source, /场内最新价/);
  assert.match(source, /includes\("场内交易"\).*"不适用"/);
});

test("groups off-exchange funds and exchange-traded ETFs separately", async () => {
  const source = await readFile(new URL("src/App.tsx", root), "utf8");
  assert.match(source, /title: "场外基金"/);
  assert.match(source, /title: "场内 ETF"/);
  assert.match(source, /场外申购/);
  assert.match(source, /关注价格、IOPV 与溢价/);
});

test("paginates each fund group in sets of two", async () => {
  const source = await readFile(new URL("src/App.tsx", root), "utf8");
  assert.match(source, /const FUND_PAGE_SIZE = 2/);
  assert.match(source, /visibleFunds: group\.funds\.slice/);
  assert.match(source, /aria-label={`\$\{group\.title\}分页`}/);
  assert.match(source, /className="fund-page-track"/);
  assert.match(source, /aria-current=/);
  assert.match(source, /PAGE/);
});
