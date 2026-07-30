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
  assert.match(source, /isExchangeTraded\(fund\).*"不适用"/);
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

test("shows fund scale and manager QDII quota", async () => {
  const source = await readFile(new URL("src/App.tsx", root), "utf8");
  const types = await readFile(new URL("src/types.ts", root), "utf8");
  assert.match(source, /基金规模/);
  assert.match(source, /管理人 QDII 外汇额度/);
  assert.match(source, /不代表本基金剩余额度/);
  assert.match(source, /className="source-link"/);
  assert.match(source, /target="_blank"/);
  assert.match(source, /latest\?\.fund_scale_source_url/);
  assert.match(source, /latest\?\.qdii_quota_source_url/);
  assert.match(types, /fund_scale: number \| null/);
  assert.match(types, /fund_scale_source_url: string \| null/);
  assert.match(types, /manager_qdii_quota_usd: number \| null/);
  assert.match(types, /qdii_quota_source_url: string \| null/);
});

test("shows published tracking error with provenance and freshness", async () => {
  const source = await readFile(new URL("src/App.tsx", root), "utf8");
  const types = await readFile(new URL("src/types.ts", root), "utf8");
  assert.match(source, /公开年化跟踪误差/);
  assert.doesNotMatch(source, /60日跟踪误差/);
  assert.match(source, /tracking_error_source_url/);
  assert.match(source, /tracking_error_stale/);
  assert.match(source, /部分字段沿用上次有效值/);
  assert.match(types, /tracking_error_as_of: string \| null/);
  assert.match(types, /carried_fields: string\[\]/);
});

test("sorts funds by direct-channel limit or published tracking error before pagination", async () => {
  const source = await readFile(new URL("src/App.tsx", root), "utf8");
  assert.match(source, /type FundSort =/);
  assert.match(source, /function sortFunds/);
  assert.match(source, /rightValue - leftValue/);
  assert.match(source, /leftValue - rightValue/);
  assert.match(source, /aria-label={`按\$\{group\.title\}数据排序`}/);
  assert.match(source, /"off-exchange": "limit-descending"/);
  assert.match(source, /"exchange-traded": "default"/);
  assert.match(source, /return fund\.channel_daily_limit/);
  assert.match(source, /fund\.latest\?\.tracking_error_stale/);
  assert.match(source, /fund\.latest\?\.tracking_error/);
  assert.doesNotMatch(source, /channel_daily_limit \?\? fund\.latest\?\.daily_limit/);
  assert.match(source, /跟踪误差低 → 高/);
  assert.match(source, /跟踪误差高 → 低/);
  assert.match(source, /直销单日额度/);
  assert.match(source, /等待核实基金公司直销公告/);
  assert.match(source, /href=\{fund\.limit_source_url\} label="直销公告"/);
  assert.match(source, /sortFunds\([\s\S]*funds\.filter/);
  assert.match(source, /visibleFunds: group\.funds\.slice/);
  assert.match(source, /"off-exchange": 1/);
});
