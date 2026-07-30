import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import {
  assetKeys,
  type Alert,
  type AssetAmounts,
  type AssetKey,
  type AssetSnapshot,
  type FundSnapshot,
  type FundWatch,
  type Health,
  type PortfolioSummary,
  type Settings,
  type StressResult,
  type StressScenario,
  type SustainabilityResult,
} from "./types";

const assetMeta: Record<
  AssetKey,
  { label: string; short: string; color: string; description: string }
> = {
  cash: {
    label: "货币",
    short: "货币",
    color: "#68897f",
    description: "现金、货币基金",
  },
  short_bond: {
    label: "短债",
    short: "短债",
    color: "#91a99d",
    description: "短久期固收",
  },
  long_bond: {
    label: "中长债",
    short: "中长债",
    color: "#b8c6aa",
    description: "中长久期债券",
  },
  nasdaq100: {
    label: "纳指 100",
    short: "纳指",
    color: "#d0674d",
    description: "唯一计入权益比例",
  },
  gold: {
    label: "黄金",
    short: "黄金",
    color: "#d6ab57",
    description: "黄金及黄金基金",
  },
  digital: {
    label: "数字资产",
    short: "数字",
    color: "#766b86",
    description: "不计入权益比例",
  },
};

const zeroAssets = (): AssetAmounts => ({
  cash: 0,
  short_bond: 0,
  long_bond: 0,
  nasdaq100: 0,
  gold: 0,
  digital: 0,
});

const defaultScenarios: StressScenario[] = [
  {
    name: "温和回撤 · 纳指 -10%",
    shocks: { ...zeroAssets(), nasdaq100: -10, digital: -20 },
  },
  {
    name: "深度回撤 · 纳指 -30%",
    shocks: { ...zeroAssets(), nasdaq100: -30, digital: -50 },
  },
  {
    name: "极端回撤 · 纳指 -50%",
    shocks: { ...zeroAssets(), nasdaq100: -50, digital: -70 },
  },
];

const money = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  maximumFractionDigits: 0,
});
const number = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });

function formatMoney(value: number | null | undefined) {
  return value == null ? "—" : money.format(value);
}

function formatValue(value: number | null | undefined, digits = 4) {
  return value == null
    ? "—"
    : new Intl.NumberFormat("zh-CN", {
        minimumFractionDigits: 0,
        maximumFractionDigits: digits,
      }).format(value);
}

function formatPercent(value: number | null | undefined, digits = 1) {
  return value == null ? "—" : `${value.toFixed(digits)}%`;
}

function dailyLimitForFund(fund: FundWatch) {
  return fund.channel_daily_limit;
}

function formatDailyLimit(fund: FundWatch) {
  if (isExchangeTraded(fund)) return "不适用";
  const limit = dailyLimitForFund(fund);
  return limit == null
    ? "待核实"
    : formatMoney(limit);
}

function formatFundScale(value: number | null | undefined) {
  return value == null ? "未公布" : `${number.format(value / 100_000_000)} 亿元`;
}

function formatQdiiQuota(value: number | null | undefined) {
  return value == null ? "未公布" : `${number.format(value / 100_000_000)} 亿美元`;
}

function wasCarried(snapshot: FundSnapshot | null | undefined, field: string) {
  return snapshot?.carried_fields?.includes(field) ?? false;
}

function SourceLink({
  href,
  label = "来源",
}: {
  href: string | null | undefined;
  label?: string;
}) {
  if (!href) return null;
  return (
    <a
      className="source-link"
      href={href}
      target="_blank"
      rel="noreferrer"
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => event.stopPropagation()}
      aria-label={`${label}（在新标签页打开）`}
    >
      {label} ↗
    </a>
  );
}

function isExchangeTraded(fund: FundWatch) {
  return (
    fund.category.toUpperCase().includes("ETF") ||
    fund.latest?.purchase_status?.includes("场内交易") ||
    fund.exchange_code === fund.fund_code
  );
}

const FUND_PAGE_SIZE = 2;
type FundSort =
  | "default"
  | "limit-descending"
  | "limit-ascending"
  | "tracking-ascending"
  | "tracking-descending";

function sortableValue(fund: FundWatch, sort: FundSort) {
  if (sort.startsWith("limit-")) return dailyLimitForFund(fund);
  if (sort.startsWith("tracking-")) {
    return fund.latest?.tracking_error_stale
      ? null
      : fund.latest?.tracking_error;
  }
  return null;
}

function sortFunds(funds: FundWatch[], sort: FundSort) {
  if (sort === "default") return funds;
  return [...funds].sort((left, right) => {
    const leftValue = sortableValue(left, sort);
    const rightValue = sortableValue(right, sort);
    if (leftValue == null) return rightValue == null ? 0 : 1;
    if (rightValue == null) return -1;
    return sort.endsWith("descending")
      ? rightValue - leftValue
      : leftValue - rightValue;
  });
}

function localDate() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function App() {
  const [page, setPage] = useState<"fire" | "qdii">(
    window.location.hash === "#qdii" ? "qdii" : "fire",
  );
  const [settingsOpen, setSettingsOpen] = useState(false);

  const navigate = (next: "fire" | "qdii") => {
    window.location.hash = next;
    setPage(next);
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="brand" onClick={() => navigate("fire")} type="button">
          <span className="brand-mark">F</span>
          <span>
            <strong>FIRE CONTROL</strong>
            <small>LOCAL ASSET DESK</small>
          </span>
        </button>
        <nav className="main-nav" aria-label="主导航">
          <button
            className={page === "fire" ? "active" : ""}
            onClick={() => navigate("fire")}
            type="button"
          >
            资产仪表盘
          </button>
          <button
            className={page === "qdii" ? "active" : ""}
            onClick={() => navigate("qdii")}
            type="button"
          >
            QDII 记录器
          </button>
        </nav>
        <div className="top-actions">
          <span className="local-pill">
            <i />
            仅在本机保存
          </span>
          <button
            className="icon-button"
            aria-label="打开设置"
            title="设置"
            onClick={() => setSettingsOpen(true)}
            type="button"
          >
            ⚙
          </button>
        </div>
      </header>

      <main>
        {page === "fire" ? <FireDashboard /> : <QDIITracker />}
      </main>

      {settingsOpen && (
        <SettingsDialog onClose={() => setSettingsOpen(false)} />
      )}
    </div>
  );
}

function FireDashboard() {
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [history, setHistory] = useState<AssetSnapshot[]>([]);
  const [form, setForm] = useState<AssetAmounts>(zeroAssets);
  const [snapshotDate, setSnapshotDate] = useState(localDate());
  const [note, setNote] = useState("");
  const [scenarios, setScenarios] =
    useState<StressScenario[]>(defaultScenarios);
  const [stress, setStress] = useState<StressResult[]>([]);
  const [spending, setSpending] = useState<number[]>([120000, 180000, 240000]);
  const [realReturn, setRealReturn] = useState(2);
  const [sustainability, setSustainability] = useState<
    SustainabilityResult[]
  >([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [nextSummary, nextHistory] = await Promise.all([
        api.getSummary(),
        api.getAssets(),
      ]);
      setSummary(nextSummary);
      setHistory(nextHistory);
      if (nextSummary.snapshot) {
        const next = zeroAssets();
        assetKeys.forEach((key) => {
          next[key] = nextSummary.snapshot![key];
        });
        setForm(next);
      }
      setError("");
    } catch (caught) {
      setError((caught as Error).message);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!summary?.snapshot) {
      setStress([]);
      setSustainability([]);
      return;
    }
    void Promise.all([
      api.runStress(scenarios),
      api.runSustainability(spending, realReturn),
    ])
      .then(([nextStress, nextSustainability]) => {
        setStress(nextStress);
        setSustainability(nextSustainability);
      })
      .catch((caught) => setError((caught as Error).message));
  }, [summary, scenarios, spending, realReturn]);

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    try {
      await api.saveAssets({ ...form, snapshot_date: snapshotDate, note });
      await refresh();
      setMessage(`${snapshotDate} 的资产快照已保存`);
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const updateScenario = (
    scenarioIndex: number,
    key: AssetKey,
    value: number,
  ) => {
    setScenarios((current) =>
      current.map((scenario, index) =>
        index === scenarioIndex
          ? { ...scenario, shocks: { ...scenario.shocks, [key]: value } }
          : scenario,
      ),
    );
  };

  const statusText = summary
    ? {
        below: "低于区间",
        inside: "处于再平衡区间",
        above: "高于区间",
        empty: "等待录入",
      }[summary.status]
    : "载入中";

  return (
    <div className="page-wrap">
      <section className="hero-row">
        <div>
          <p className="eyebrow">PERSONAL CAPITAL ALLOCATION</p>
          <h1>你的 FIRE 资产，现在处在什么位置？</h1>
          <p className="hero-copy">
            六类资产统一折算成人民币。权益仅指纳指 100，50% 目标，
            40%–60% 为再平衡缓冲带。
          </p>
        </div>
        <div className="as-of">
          <span>最近快照</span>
          <strong>{summary?.snapshot?.snapshot_date ?? "尚未保存"}</strong>
        </div>
      </section>

      {error && <Banner tone="error">{error}</Banner>}
      {message && <Banner tone="success">{message}</Banner>}

      <section className="overview-grid">
        <article className="card total-card">
          <div className="card-label">总资产</div>
          <div className="hero-number">{formatMoney(summary?.total)}</div>
          <div className="allocation-bar" aria-label="资产配置比例">
            {summary?.snapshot &&
              summary.total > 0 &&
              assetKeys.map((key) => (
                <span
                  key={key}
                  style={{
                    width: `${(summary.snapshot![key] / summary.total) * 100}%`,
                    background: assetMeta[key].color,
                  }}
                  title={`${assetMeta[key].label} ${formatPercent((summary.snapshot![key] / summary.total) * 100)}`}
                />
              ))}
          </div>
          <div className="legend-grid">
            {assetKeys.map((key) => (
              <div key={key}>
                <i style={{ background: assetMeta[key].color }} />
                <span>{assetMeta[key].short}</span>
                <strong>
                  {summary?.snapshot && summary.total
                    ? formatPercent(
                        (summary.snapshot[key] / summary.total) * 100,
                      )
                    : "0.0%"}
                </strong>
              </div>
            ))}
          </div>
        </article>

        <article className="card equity-card">
          <div className="card-head">
            <div>
              <div className="card-label">权益比例</div>
              <div className="hero-number accent">
                {formatPercent(summary?.equity_ratio)}
              </div>
            </div>
            <span className={`status-chip ${summary?.status ?? "empty"}`}>
              {statusText}
            </span>
          </div>
          <div className="band-scale">
            <div className="band-track">
              <span className="safe-zone" />
              <span
                className="band-marker"
                style={{
                  left: `${Math.max(0, Math.min(100, summary?.equity_ratio ?? 0))}%`,
                }}
              />
            </div>
            <div className="band-labels">
              <span>0%</span>
              <span>40% 下限</span>
              <span>50% 目标</span>
              <span>60% 上限</span>
              <span>100%</span>
            </div>
          </div>
          <div className="boundary-grid">
            <div>
              <span>距下限</span>
              <strong>{formatPercent(summary?.distance_to_lower_pp)}</strong>
              <small>{formatMoney(summary?.transfer_to_lower)}</small>
            </div>
            <div className="target-cell">
              <span>调至目标</span>
              <strong>{formatMoney(summary?.transfer_to_target)}</strong>
              <small>正数增配，负数减配</small>
            </div>
            <div>
              <span>距上限</span>
              <strong>{formatPercent(summary?.distance_to_upper_pp)}</strong>
              <small>{formatMoney(summary?.transfer_to_upper)}</small>
            </div>
          </div>
        </article>
      </section>

      <section className="section-grid">
        <article className="card entry-card">
          <div className="section-title">
            <div>
              <p className="eyebrow">TODAY&apos;S SNAPSHOT</p>
              <h2>录入资产市值</h2>
            </div>
            <span>单位：人民币</span>
          </div>
          <form onSubmit={save}>
            <div className="asset-input-grid">
              {assetKeys.map((key) => (
                <label key={key} className="asset-field">
                  <span>
                    <i style={{ background: assetMeta[key].color }} />
                    {assetMeta[key].label}
                    <small>{assetMeta[key].description}</small>
                  </span>
                  <div className="money-input">
                    <b>¥</b>
                    <input
                      aria-label={`${assetMeta[key].label}市值`}
                      type="number"
                      inputMode="decimal"
                      min="0"
                      step="0.01"
                      value={form[key]}
                      onChange={(event) =>
                        setForm({
                          ...form,
                          [key]: Math.max(0, Number(event.target.value)),
                        })
                      }
                    />
                  </div>
                </label>
              ))}
            </div>
            <div className="form-footer">
              <label>
                快照日期
                <input
                  type="date"
                  value={snapshotDate}
                  onChange={(event) => setSnapshotDate(event.target.value)}
                  required
                />
              </label>
              <label className="note-field">
                备注
                <input
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder="可选：调仓、奖金到账…"
                  maxLength={200}
                />
              </label>
              <button className="primary-button" disabled={saving} type="submit">
                {saving ? "保存中…" : "保存今日快照"}
              </button>
            </div>
          </form>
        </article>

        <article className="card history-card">
          <div className="section-title">
            <div>
              <p className="eyebrow">HISTORY</p>
              <h2>历史快照</h2>
            </div>
            <span>{history.length} 条</span>
          </div>
          {history.length ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>日期</th>
                    <th>总资产</th>
                    <th>权益比例</th>
                    <th>备注</th>
                  </tr>
                </thead>
                <tbody>
                  {history.slice(0, 8).map((item) => {
                    const total = assetKeys.reduce(
                      (sum, key) => sum + item[key],
                      0,
                    );
                    return (
                      <tr key={item.id}>
                        <td>{item.snapshot_date}</td>
                        <td>{formatMoney(total)}</td>
                        <td>
                          {formatPercent(
                            total ? (item.nasdaq100 / total) * 100 : 0,
                          )}
                        </td>
                        <td>{item.note || "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              title="还没有历史快照"
              copy="保存第一组资产市值后，这里会形成你的本地资产时间线。"
            />
          )}
        </article>
      </section>

      <section className="card stress-card">
        <div className="section-title">
          <div>
            <p className="eyebrow">DOWNSIDE LAB</p>
            <h2>市场下跌后的仓位</h2>
          </div>
          <span>点击数值可调整各资产跌幅</span>
        </div>
        <div className="stress-grid">
          {scenarios.map((scenario, scenarioIndex) => {
            const result = stress[scenarioIndex];
            return (
              <article key={scenario.name} className="scenario-card">
                <div className="scenario-head">
                  <div>
                    <span>SCENARIO {scenarioIndex + 1}</span>
                    <h3>{scenario.name}</h3>
                  </div>
                  <strong>{formatMoney(result?.loss)}</strong>
                </div>
                <div className="shock-editor">
                  {assetKeys.map((key) => (
                    <label key={key}>
                      {assetMeta[key].short}
                      <div>
                        <input
                          aria-label={`${scenario.name} ${assetMeta[key].label}冲击`}
                          type="number"
                          min="-100"
                          max="300"
                          step="1"
                          value={scenario.shocks[key]}
                          onChange={(event) =>
                            updateScenario(
                              scenarioIndex,
                              key,
                              Number(event.target.value),
                            )
                          }
                        />
                        <span>%</span>
                      </div>
                    </label>
                  ))}
                </div>
                <div className="scenario-result">
                  <div>
                    <span>冲击后总资产</span>
                    <strong>{formatMoney(result?.total_after)}</strong>
                  </div>
                  <div>
                    <span>组合回撤</span>
                    <strong className="negative">
                      {result ? formatPercent(-result.loss_ratio) : "—"}
                    </strong>
                  </div>
                  <div>
                    <span>权益比例</span>
                    <strong>{formatPercent(result?.equity_ratio)}</strong>
                  </div>
                </div>
                <div className="mini-allocation">
                  {result &&
                    assetKeys.map((key) => (
                      <span
                        key={key}
                        style={{
                          width: `${result.weights[key]}%`,
                          background: assetMeta[key].color,
                        }}
                      />
                    ))}
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <section className="card sustain-card">
        <div className="section-title">
          <div>
            <p className="eyebrow">RUNWAY ESTIMATE</p>
            <h2>不同年度支出的资产续航</h2>
          </div>
          <span>按今日购买力估算</span>
        </div>
        <div className="sustain-layout">
          <div className="sustain-controls">
            <label>
              预期实际年化收益率
              <div className="suffix-input">
                <input
                  type="number"
                  min="-20"
                  max="20"
                  step="0.1"
                  value={realReturn}
                  onChange={(event) =>
                    setRealReturn(Number(event.target.value))
                  }
                />
                <span>%</span>
              </div>
            </label>
            <div>
              <span className="control-label">年度支出场景</span>
              {spending.map((value, index) => (
                <div className="spending-row" key={`${index}-${value}`}>
                  <span>¥</span>
                  <input
                    aria-label={`年度支出场景 ${index + 1}`}
                    type="number"
                    min="0"
                    step="1000"
                    value={value}
                    onChange={(event) =>
                      setSpending((current) =>
                        current.map((item, itemIndex) =>
                          itemIndex === index
                            ? Math.max(0, Number(event.target.value))
                            : item,
                        ),
                      )
                    }
                  />
                  {spending.length > 1 && (
                    <button
                      type="button"
                      aria-label={`删除支出场景 ${index + 1}`}
                      onClick={() =>
                        setSpending((current) =>
                          current.filter((_, itemIndex) => itemIndex !== index),
                        )
                      }
                    >
                      ×
                    </button>
                  )}
                </div>
              ))}
              <button
                className="text-button"
                type="button"
                onClick={() =>
                  setSpending((current) => [
                    ...current,
                    (current.at(-1) || 120000) + 60000,
                  ])
                }
              >
                ＋ 增加支出场景
              </button>
            </div>
          </div>
          <div className="runway-list">
            {sustainability.length ? (
              sustainability.map((item) => (
                <div className="runway-row" key={item.annual_spending}>
                  <div>
                    <span>每年支出</span>
                    <strong>{formatMoney(item.annual_spending)}</strong>
                  </div>
                  <div className="runway-meter">
                    <span
                      style={{
                        width: item.sustainable
                          ? "100%"
                          : `${Math.min(100, ((item.years || 0) / 100) * 100)}%`,
                      }}
                    />
                  </div>
                  <div className={item.sustainable ? "sustainable" : ""}>
                    <span>预计续航</span>
                    <strong>
                      {item.sustainable
                        ? "模型内可持续"
                        : `${number.format(item.years || 0)} 年`}
                    </strong>
                    <small>
                      {item.depletion_date
                        ? `约至 ${item.depletion_date}`
                        : "超过 100 年或余额不再下降"}
                    </small>
                  </div>
                </div>
              ))
            ) : (
              <EmptyState
                title="等待资产快照"
                copy="保存资产后即可估算不同支出水平下的续航。"
              />
            )}
          </div>
        </div>
        <p className="disclaimer">
          本模型按月模拟，未包含税费、交易成本、养老金、未来收入或随机收益波动，仅作个人规划参考，不构成投资建议。
        </p>
      </section>
    </div>
  );
}

function QDIITracker() {
  const [funds, setFunds] = useState<FundWatch[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [selected, setSelected] = useState<FundWatch | null>(null);
  const [history, setHistory] = useState<FundSnapshot[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<FundWatch | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [fundSorts, setFundSorts] = useState<Record<string, FundSort>>({
    "off-exchange": "limit-descending",
    "exchange-traded": "default",
  });
  const [fundPages, setFundPages] = useState<Record<string, number>>({
    "off-exchange": 1,
    "exchange-traded": 1,
  });

  const refresh = useCallback(async () => {
    try {
      const [nextFunds, nextAlerts, nextHealth] = await Promise.all([
        api.getFunds(),
        api.getAlerts(),
        api.getHealth(),
      ]);
      setFunds(nextFunds);
      setAlerts(nextAlerts);
      setHealth(nextHealth);
      setError("");
    } catch (caught) {
      setError((caught as Error).message);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const counts = {
      "off-exchange": funds.filter((fund) => !isExchangeTraded(fund)).length,
      "exchange-traded": funds.filter(isExchangeTraded).length,
    };
    setFundPages((current) => {
      const next = { ...current };
      let changed = false;
      Object.entries(counts).forEach(([key, count]) => {
        const lastPage = Math.max(1, Math.ceil(count / FUND_PAGE_SIZE));
        if ((next[key] ?? 1) > lastPage) {
          next[key] = lastPage;
          changed = true;
        }
      });
      return changed ? next : current;
    });
  }, [funds]);

  const syncNow = async () => {
    setSyncing(true);
    setMessage("");
    try {
      const result = await api.sync("full");
      setMessage(result.message);
      await refresh();
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setSyncing(false);
    }
  };

  const openHistory = async (fund: FundWatch) => {
    setSelected(fund);
    setHistory([]);
    setHistoryLoading(true);
    try {
      setHistory(await api.getFundHistory(fund.fund_code));
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setHistoryLoading(false);
    }
  };

  const unread = alerts.filter((alert) => !alert.read_at).length;
  const fundGroups = [
    {
      key: "off-exchange",
      eyebrow: "OFF-EXCHANGE",
      title: "场外基金",
      copy: "关注申购状态与每日限额",
      funds: sortFunds(
        funds.filter((fund) => !isExchangeTraded(fund)),
        fundSorts["off-exchange"],
      ),
    },
    {
      key: "exchange-traded",
      eyebrow: "EXCHANGE-TRADED",
      title: "场内 ETF",
      copy: "关注价格、IOPV 与溢价",
      funds: sortFunds(
        funds.filter(isExchangeTraded),
        fundSorts["exchange-traded"],
      ),
    },
  ]
    .filter((group) => group.funds.length > 0)
    .map((group) => {
      const pageCount = Math.ceil(group.funds.length / FUND_PAGE_SIZE);
      const currentPage = Math.min(fundPages[group.key] ?? 1, pageCount);
      const offset = (currentPage - 1) * FUND_PAGE_SIZE;
      return {
        ...group,
        currentPage,
        pageCount,
        visibleFunds: group.funds.slice(offset, offset + FUND_PAGE_SIZE),
      };
    });

  return (
    <div className="page-wrap">
      <section className="hero-row qdii-hero">
        <div>
          <p className="eyebrow">QDII ACCESS WATCH</p>
          <h1>限购变化，不再靠反复刷新。</h1>
          <p className="hero-copy">
            自动记录公开基金数据，保留申购状态、额度、净值、估值和场内溢价的本地时间线。
          </p>
        </div>
        <div className="qdii-actions">
          <button className="secondary-button" onClick={syncNow} disabled={syncing}>
            {syncing ? "同步中…" : "↻ 立即同步"}
          </button>
          <button className="primary-button" onClick={() => setShowAdd(true)}>
            ＋ 添加基金
          </button>
        </div>
      </section>

      {error && <Banner tone="error">{error}</Banner>}
      {message && <Banner tone="success">{message}</Banner>}

      <section className="health-strip">
        <div>
          <i className={health?.status === "ok" ? "ok" : ""} />
          <span>本地服务</span>
          <strong>{health?.status === "ok" ? "运行正常" : "等待连接"}</strong>
        </div>
        <div>
          <span>公开数据源</span>
          <strong>{health?.provider ?? "AKShare / 东方财富"}</strong>
        </div>
        <div>
          <span>最近同步</span>
          <strong>
            {health?.last_sync?.finished_at
              ? new Date(health.last_sync.finished_at).toLocaleString("zh-CN")
              : "尚未同步"}
          </strong>
        </div>
        <div>
          <span>未读提醒</span>
          <strong className={unread ? "alert-count" : ""}>{unread}</strong>
        </div>
      </section>

      <section className="qdii-layout">
        <div>
          <div className="section-title outside-title">
            <div>
              <p className="eyebrow">WATCHLIST</p>
              <h2>关注的基金</h2>
            </div>
            <span>{funds.length} 只</span>
          </div>
          {funds.length ? (
            <div className="fund-groups">
              {fundGroups.map((group) => (
                <section className="watch-group" key={group.key}>
                  <div className="watch-group-title">
                    <div>
                      <p className="eyebrow">{group.eyebrow}</p>
                      <h3>{group.title}</h3>
                      <span>{group.copy}</span>
                    </div>
                    <div className="watch-group-actions">
                      <label className="fund-sort">
                        <span>排序方式</span>
                        <select
                          aria-label={`按${group.title}数据排序`}
                          value={fundSorts[group.key]}
                          onChange={(event) => {
                            setFundSorts((current) => ({
                              ...current,
                              [group.key]: event.target.value as FundSort,
                            }));
                            setFundPages((current) => ({
                              ...current,
                              [group.key]: 1,
                            }));
                          }}
                        >
                          {group.key === "off-exchange" && (
                            <>
                              <option value="limit-descending">
                                直销额度高 → 低
                              </option>
                              <option value="limit-ascending">
                                直销额度低 → 高
                              </option>
                            </>
                          )}
                          <option value="tracking-ascending">
                            跟踪误差低 → 高
                          </option>
                          <option value="tracking-descending">
                            跟踪误差高 → 低
                          </option>
                          <option value="default">默认顺序</option>
                        </select>
                      </label>
                      <strong>{group.funds.length} 只</strong>
                    </div>
                  </div>
                  <div className="fund-grid">
                    {group.visibleFunds.map((fund) => (
                      <FundCard
                        key={fund.fund_code}
                        fund={fund}
                        onHistory={() => void openHistory(fund)}
                        onDelete={() => setPendingDelete(fund)}
                      />
                    ))}
                  </div>
                  {group.pageCount > 1 && (
                    <nav
                      className="fund-pagination"
                      aria-label={`${group.title}分页`}
                    >
                      <button
                        className="page-arrow"
                        type="button"
                        aria-label={`${group.title}上一页`}
                        disabled={group.currentPage === 1}
                        onClick={() =>
                          setFundPages((current) => ({
                            ...current,
                            [group.key]: group.currentPage - 1,
                          }))
                        }
                      >
                        ←
                      </button>
                      <div className="page-center">
                        <div className="page-indicator">
                          <small>PAGE</small>
                          <strong>
                            {String(group.currentPage).padStart(2, "0")}
                          </strong>
                          <span>
                            / {String(group.pageCount).padStart(2, "0")}
                          </span>
                        </div>
                        <div
                          className="fund-page-track"
                          role="group"
                          aria-label={`${group.title}选择页码`}
                        >
                          {Array.from(
                            { length: group.pageCount },
                            (_, index) => {
                              const pageNumber = index + 1;
                              return (
                                <button
                                  className={`page-step ${
                                    pageNumber === group.currentPage
                                      ? "active"
                                      : ""
                                  }`}
                                  type="button"
                                  key={pageNumber}
                                  aria-label={`第 ${pageNumber} 页`}
                                  aria-current={
                                    pageNumber === group.currentPage
                                      ? "page"
                                      : undefined
                                  }
                                  onClick={() =>
                                    setFundPages((current) => ({
                                      ...current,
                                      [group.key]: pageNumber,
                                    }))
                                  }
                                />
                              );
                            },
                          )}
                        </div>
                      </div>
                      <button
                        className="page-arrow"
                        type="button"
                        aria-label={`${group.title}下一页`}
                        disabled={group.currentPage === group.pageCount}
                        onClick={() =>
                          setFundPages((current) => ({
                            ...current,
                            [group.key]: group.currentPage + 1,
                          }))
                        }
                      >
                        →
                      </button>
                    </nav>
                  )}
                </section>
              ))}
            </div>
          ) : (
            <div className="fund-grid">
              <article className="card empty-fund-card">
                <EmptyState
                  title="添加第一只 QDII 基金"
                  copy="输入基金代码后，系统会在本机保存每日额度和净值变化。"
                />
                <button className="primary-button" onClick={() => setShowAdd(true)}>
                  添加基金
                </button>
              </article>
            </div>
          )}
        </div>

        <aside className="card alert-panel">
          <div className="section-title">
            <div>
              <p className="eyebrow">CHANGE ALERTS</p>
              <h2>额度提醒</h2>
            </div>
            {unread > 0 && (
              <button
                className="text-button"
                onClick={async () => {
                  await api.readAlerts();
                  await refresh();
                }}
              >
                全部已读
              </button>
            )}
          </div>
          <div className="alert-list">
            {alerts.length ? (
              alerts.slice(0, 12).map((alert) => (
                <button
                  className={`alert-item ${alert.read_at ? "" : "unread"}`}
                  key={alert.id}
                  onClick={async () => {
                    if (!alert.read_at) {
                      await api.readAlerts([alert.id]);
                      await refresh();
                    }
                  }}
                >
                  <i />
                  <span>
                    <strong>{alert.title}</strong>
                    <p>{alert.message}</p>
                    <small>
                      {new Date(alert.created_at).toLocaleString("zh-CN")}
                    </small>
                  </span>
                </button>
              ))
            ) : (
              <EmptyState
                title="暂无额度提醒"
                copy="限额提高或恢复申购后，提醒会出现在这里。"
              />
            )}
          </div>
          <div className="data-tools">
            <h3>本地数据</h3>
            <div>
              <a href="/api/export/json" download>
                导出 JSON
              </a>
              <a href="/api/export/csv" download>
                导出 CSV
              </a>
              <label>
                恢复备份
                <input
                  type="file"
                  accept="application/json,.json"
                  onChange={async (event) => {
                    const file = event.target.files?.[0];
                    if (!file) return;
                    try {
                      const payload = JSON.parse(await file.text()) as unknown;
                      await api.restore(payload);
                      setMessage("备份已恢复");
                      await refresh();
                    } catch (caught) {
                      setError(`恢复失败：${(caught as Error).message}`);
                    }
                    event.target.value = "";
                  }}
                />
              </label>
            </div>
          </div>
        </aside>
      </section>

      <p className="source-note">
        数据来自公开页面，可能延迟、缺失或因上游调整暂时不可用。工具会显示抓取时间和过期状态，并保留上一条有效记录。
      </p>

      {showAdd && (
        <AddFundDialog
          onClose={() => setShowAdd(false)}
          onSaved={async () => {
            setShowAdd(false);
            await refresh();
          }}
        />
      )}
      {selected && (
        <FundHistoryDialog
          fund={selected}
          history={history}
          loading={historyLoading}
          onClose={() => setSelected(null)}
          onCorrected={async () => {
            setHistory(await api.getFundHistory(selected.fund_code));
            await refresh();
          }}
        />
      )}
      {pendingDelete && (
        <DeleteFundDialog
          fund={pendingDelete}
          onClose={() => setPendingDelete(null)}
          onDeleted={async () => {
            setPendingDelete(null);
            setMessage(`已停止关注 ${pendingDelete.name || pendingDelete.fund_code}`);
            await refresh();
          }}
        />
      )}
    </div>
  );
}

function FundCard({
  fund,
  onHistory,
  onDelete,
}: {
  fund: FundWatch;
  onHistory: () => void;
  onDelete: () => void;
}) {
  const latest = fund.latest;
  const status = latest?.purchase_status || "等待同步";
  const exchangeTraded = isExchangeTraded(fund);
  const effectiveLimit = dailyLimitForFund(fund);
  const relaxed =
    status.includes("开放") ||
    (effectiveLimit != null && effectiveLimit > 0);
  return (
    <article
      className={`card fund-card ${
        exchangeTraded ? "exchange-traded" : "off-exchange"
      }`}
      role="button"
      tabIndex={0}
      aria-label={`查看 ${fund.name || fund.fund_code} 详情`}
      onClick={onHistory}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onHistory();
        }
      }}
    >
      <div className="fund-head">
        <div>
          <span className="fund-code">{fund.fund_code}</span>
          <h3>{fund.name || `基金 ${fund.fund_code}`}</h3>
          <p>
            {fund.category}
            {fund.exchange_code ? ` · 场内 ${fund.exchange_code}` : ""}
          </p>
        </div>
        <div className="fund-status-stack">
          <span
            className={`venue-chip ${
              exchangeTraded ? "exchange-traded" : "off-exchange"
            }`}
          >
            {exchangeTraded ? "场内交易" : "场外申购"}
          </span>
          <span className={`purchase-status ${relaxed ? "open" : ""}`}>
            {status}
          </span>
        </div>
      </div>
      <div className="limit-display">
        <span>{exchangeTraded ? "场内最新价" : "直销单日额度"}</span>
        <strong>
          {exchangeTraded
            ? formatValue(latest?.market_price)
            : formatDailyLimit(fund)}
        </strong>
        <div className="metric-source-row">
          <small>
            {fund.limit_channel
              ? `${fund.limit_channel}${
                  fund.limit_effective_date
                    ? ` · 生效于 ${fund.limit_effective_date}`
                    : ""
                }`
              : latest?.source_time
              ? `采集于 ${new Date(latest.source_time).toLocaleString("zh-CN")}`
              : "等待核实基金公司直销公告"}
            {latest?.stale ? " · 数据已过期" : ""}
            {latest?.carried_fields?.length
              ? " · 部分字段沿用上次有效值"
              : ""}
          </small>
          {!exchangeTraded && (
            <SourceLink href={fund.limit_source_url} label="直销公告" />
          )}
        </div>
      </div>
      <div className="fund-metrics">
        <div>
          <span>{exchangeTraded ? "IOPV" : "估值"}</span>
          <strong>
            {formatValue(exchangeTraded ? latest?.iopv : latest?.estimate)}
          </strong>
        </div>
        <div>
          <span>净值</span>
          <strong>{formatValue(latest?.nav)}</strong>
        </div>
        <div>
          <span>场内溢价</span>
          <strong
            className={
              latest?.premium != null && latest.premium > 0 ? "negative" : ""
            }
          >
            {formatPercent(latest?.premium, 2)}
          </strong>
        </div>
        <div>
          <span>公开年化跟踪误差</span>
          <strong>{formatPercent(latest?.tracking_error, 2)}</strong>
          <div className="metric-source-row metric-compact-source">
            <small>
              {latest?.tracking_error_stale
                ? "沿用上次有效值"
                : latest?.tracking_error_as_of
                ? `截至 ${latest.tracking_error_as_of}`
                : "等待公开数据"}
            </small>
            <SourceLink href={latest?.tracking_error_source_url} />
          </div>
        </div>
      </div>
      <div
        className={`fund-profile-strip ${exchangeTraded ? "single" : ""}`}
      >
        <div>
          <span>基金规模</span>
          <strong>{formatFundScale(latest?.fund_scale)}</strong>
          <div className="metric-source-row">
            <small>
              {exchangeTraded ? "按最新份额与净值估算" : "最近公开规模"}
              {wasCarried(latest, "fund_scale") ? " · 沿用上次有效值" : ""}
            </small>
            <SourceLink href={latest?.fund_scale_source_url} />
          </div>
        </div>
        {!exchangeTraded && (
          <div title="基金管理人整体累计获批额度，不代表本基金剩余可用额度">
            <span>管理人 QDII 外汇额度</span>
            <strong>{formatQdiiQuota(latest?.manager_qdii_quota_usd)}</strong>
            <small>
              {latest?.fund_manager || "管理人未公布"}
              {latest?.qdii_quota_date
                ? ` · 截至 ${latest.qdii_quota_date}`
                : ""}
              {wasCarried(latest, "manager_qdii_quota_usd")
                ? " · 沿用上次有效值"
                : ""}
            </small>
            <SourceLink href={latest?.qdii_quota_source_url} />
          </div>
        )}
      </div>
      <div className="fund-foot">
        <span>
          {fund.benchmark ? `基准：${fund.benchmark}` : "未设置跟踪指数"}
        </span>
        <div>
          <button
            onClick={(event) => {
              event.stopPropagation();
              onHistory();
            }}
          >
            查看详情 →
          </button>
          <button
            className="danger-text"
            onClick={(event) => {
              event.stopPropagation();
              onDelete();
            }}
            aria-label="删除关注"
          >
            ×
          </button>
        </div>
      </div>
    </article>
  );
}

function AddFundDialog({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    fund_code: "",
    name: "",
    exchange_code: "",
    category: "QDII",
    benchmark: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  return (
    <Dialog title="添加关注基金" eyebrow="NEW WATCH" onClose={onClose}>
      <form
        className="dialog-form"
        onSubmit={async (event) => {
          event.preventDefault();
          setSaving(true);
          try {
            await api.addFund(form);
            onSaved();
          } catch (caught) {
            setError((caught as Error).message);
            setSaving(false);
          }
        }}
      >
        {error && <Banner tone="error">{error}</Banner>}
        <div className="two-col">
          <label>
            基金代码 *
            <input
              placeholder="例如 000834"
              pattern="\d{6}"
              maxLength={6}
              value={form.fund_code}
              onChange={(event) =>
                setForm({ ...form, fund_code: event.target.value.trim() })
              }
              required
              autoFocus
            />
          </label>
          <label>
            场内代码
            <input
              placeholder="ETF / LOF 可填写"
              pattern="\d{6}"
              maxLength={6}
              value={form.exchange_code}
              onChange={(event) =>
                setForm({ ...form, exchange_code: event.target.value.trim() })
              }
            />
          </label>
        </div>
        <label>
          基金名称
          <input
            placeholder="留空时首次同步自动补充"
            value={form.name}
            maxLength={80}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
          />
        </label>
        <div className="two-col">
          <label>
            类型
            <select
              value={form.category}
              onChange={(event) =>
                setForm({ ...form, category: event.target.value })
              }
            >
              <option>QDII</option>
              <option>ETF</option>
              <option>LOF</option>
              <option>ETF联接</option>
            </select>
          </label>
          <label>
            跟踪标的（可选）
            <input
              placeholder="留空则首次同步自动补充"
              value={form.benchmark}
              maxLength={80}
              onChange={(event) =>
                setForm({ ...form, benchmark: event.target.value })
              }
            />
          </label>
        </div>
        <p className="form-hint">
          年化跟踪误差与跟踪标的均读取公开数据，并展示来源、截止日期及过期状态。
        </p>
        <div className="dialog-actions">
          <button className="secondary-button" type="button" onClick={onClose}>
            取消
          </button>
          <button className="primary-button" disabled={saving} type="submit">
            {saving ? "保存中…" : "添加并关注"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function DeleteFundDialog({
  fund,
  onClose,
  onDeleted,
}: {
  fund: FundWatch;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");

  return (
    <Dialog title="确认停止关注" eyebrow="SECOND CONFIRMATION" onClose={onClose}>
      {error && <Banner tone="error">{error}</Banner>}
      <div className="delete-confirmation">
        <span>即将停止关注</span>
        <strong>{fund.name || `基金 ${fund.fund_code}`}</strong>
        <small>基金代码 {fund.fund_code}</small>
        <p>
          确认后，该基金将从关注列表移除并停止每日同步。已有历史记录仍保留在本地备份中。
        </p>
      </div>
      <div className="dialog-actions">
        <button
          className="secondary-button"
          type="button"
          disabled={deleting}
          onClick={onClose}
        >
          取消
        </button>
        <button
          className="danger-button"
          type="button"
          disabled={deleting}
          onClick={async () => {
            setDeleting(true);
            setError("");
            try {
              await api.deleteFund(fund.fund_code);
              await onDeleted();
            } catch (caught) {
              setError((caught as Error).message);
              setDeleting(false);
            }
          }}
        >
          {deleting ? "处理中…" : "确认删除"}
        </button>
      </div>
    </Dialog>
  );
}

function FundHistoryDialog({
  fund,
  history,
  loading,
  onClose,
  onCorrected,
}: {
  fund: FundWatch;
  history: FundSnapshot[];
  loading: boolean;
  onClose: () => void;
  onCorrected: () => void;
}) {
  const [editing, setEditing] = useState<FundSnapshot | null>(null);
  const [note, setNote] = useState("");
  const [values, setValues] = useState<Partial<FundSnapshot>>({});
  const latest = fund.latest;

  return (
    <Dialog
      title={`${fund.name || fund.fund_code} · 历史记录`}
      eyebrow={fund.fund_code}
      onClose={onClose}
      wide
    >
      <div className="fund-detail-summary">
        <div className="fund-detail-primary">
          <span>当前申购状态</span>
          <strong>{latest?.purchase_status || "等待同步"}</strong>
          <small>
            {latest?.source_time
              ? `采集于 ${new Date(latest.source_time).toLocaleString("zh-CN")}`
              : "尚无采集数据"}
            {latest?.stale ? " · 数据已过期" : ""}
          </small>
          {latest?.source && <small>来源：{latest.source}</small>}
        </div>
        <div>
          <span>直销单日额度</span>
          <strong>{formatDailyLimit(fund)}</strong>
          {fund.limit_channel && (
            <div className="metric-source-row">
              <small>
                {fund.limit_channel}
                {fund.limit_effective_date
                  ? ` · ${fund.limit_effective_date} 生效`
                  : ""}
              </small>
              <SourceLink href={fund.limit_source_url} label="直销公告" />
            </div>
          )}
        </div>
        <div>
          <span>估值 / 净值</span>
          <strong>
            {formatValue(latest?.estimate)} / {formatValue(latest?.nav)}
          </strong>
          <small>估值偏差 {formatPercent(latest?.estimate_error, 2)}</small>
        </div>
        <div>
          <span>场内溢价</span>
          <strong>{formatPercent(latest?.premium, 2)}</strong>
          <small>
            {latest?.premium_basis
              ? `口径：${latest.premium_basis}`
              : "暂无计算口径"}
          </small>
        </div>
        <div>
          <span>公开年化跟踪误差</span>
          <strong>{formatPercent(latest?.tracking_error, 2)}</strong>
          <div className="metric-source-row">
            <small>
              {latest?.tracking_error_method || "等待公开数据"}
              {latest?.tracking_error_as_of
                ? ` · 截至 ${latest.tracking_error_as_of}`
                : ""}
              {latest?.tracking_error_stale ? " · 沿用上次有效值" : ""}
            </small>
            <SourceLink href={latest?.tracking_error_source_url} />
          </div>
        </div>
      </div>
      <div
        className={`fund-detail-profile ${
          isExchangeTraded(fund) ? "single" : ""
        }`}
      >
        <div>
          <span>基金规模</span>
          <strong>{formatFundScale(latest?.fund_scale)}</strong>
          <div className="metric-source-row">
            <small>
              {isExchangeTraded(fund)
                ? "最新份额 × 净值估算"
                : "最近公开披露规模"}
            </small>
            <SourceLink href={latest?.fund_scale_source_url} />
          </div>
        </div>
        {!isExchangeTraded(fund) && (
          <div title="该数字为基金管理人整体累计获批额度，不是本基金的剩余可用额度">
            <span>管理人 QDII 外汇额度</span>
            <strong>{formatQdiiQuota(latest?.manager_qdii_quota_usd)}</strong>
            <small>
              {latest?.fund_manager || "管理人未公布"}
              {latest?.qdii_quota_date
                ? ` · 截至 ${latest.qdii_quota_date}`
                : ""}
              {" · 不代表本基金剩余额度"}
            </small>
            <SourceLink href={latest?.qdii_quota_source_url} />
          </div>
        )}
      </div>
      <div className="detail-section-heading">
        <div>
          <p className="eyebrow">SNAPSHOT HISTORY</p>
          <h3>历史快照</h3>
        </div>
        <span>{history.length} 条</span>
      </div>
      {loading ? (
        <EmptyState title="正在读取记录" copy="请稍候…" />
      ) : history.length ? (
        <div className="table-scroll dialog-table">
          <table>
            <thead>
              <tr>
                <th>业务日期</th>
                <th>申购状态</th>
                <th>基金规模</th>
                <th>管理人外汇额度</th>
                <th>估值</th>
                <th>净值</th>
                <th>场内价格</th>
                <th>溢价</th>
                <th>公开年化跟踪误差</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {history.map((item) => (
                <tr key={item.id} className={item.stale ? "stale-row" : ""}>
                  <td>
                    {item.business_date || "—"}
                    {item.corrected && <small className="audit-tag">已修正</small>}
                  </td>
                  <td>
                    {item.purchase_status || "—"}
                  </td>
                  <td>
                    <div className="table-source-cell">
                      <span>{formatFundScale(item.fund_scale)}</span>
                      <SourceLink href={item.fund_scale_source_url} />
                    </div>
                  </td>
                  <td>
                    <div className="table-source-cell">
                      <span>{formatQdiiQuota(item.manager_qdii_quota_usd)}</span>
                      <SourceLink href={item.qdii_quota_source_url} />
                    </div>
                  </td>
                  <td>{formatValue(item.estimate)}</td>
                  <td>{formatValue(item.nav)}</td>
                  <td>{formatValue(item.market_price)}</td>
                  <td>{formatPercent(item.premium, 2)}</td>
                  <td>
                    <div className="table-source-cell">
                      <span>
                        {formatPercent(item.tracking_error, 2)}
                        {item.tracking_error_stale ? " · 过期" : ""}
                      </span>
                      <SourceLink href={item.tracking_error_source_url} />
                    </div>
                  </td>
                  <td>
                    <button
                      className="text-button"
                      onClick={() => {
                        setEditing(item);
                        setValues(item);
                        setNote(item.correction_note || "");
                      }}
                    >
                      修正
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="暂无采集记录" copy="点击“立即同步”获取第一条快照。" />
      )}
      {editing && (
        <form
          className="correction-box"
          onSubmit={async (event) => {
            event.preventDefault();
            await api.correctSnapshot(fund.fund_code, editing.id, {
              estimate:
                values.estimate === null ? undefined : Number(values.estimate),
              nav: values.nav === null ? undefined : Number(values.nav),
              market_price:
                values.market_price === null
                  ? undefined
                  : Number(values.market_price),
              daily_limit:
                values.daily_limit === null
                  ? undefined
                  : Number(values.daily_limit),
              fund_scale:
                values.fund_scale === null
                  ? undefined
                  : Number(values.fund_scale),
              manager_qdii_quota_usd:
                values.manager_qdii_quota_usd === null
                  ? undefined
                  : Number(values.manager_qdii_quota_usd),
              fund_manager: values.fund_manager,
              qdii_quota_date: values.qdii_quota_date,
              purchase_status: values.purchase_status,
              correction_note: note,
            });
            setEditing(null);
            onCorrected();
          }}
        >
          <div className="section-title">
            <h3>修正 {editing.business_date || "本条记录"}</h3>
            <button type="button" onClick={() => setEditing(null)}>
              ×
            </button>
          </div>
          <div className="correction-grid">
            {(
              [
                ["estimate", "估值"],
                ["nav", "净值"],
                ["market_price", "场内价格"],
                ["daily_limit", "单日限额"],
                ["fund_scale", "基金规模（人民币元）"],
                ["manager_qdii_quota_usd", "管理人 QDII 额度（美元）"],
              ] as const
            ).map(([key, label]) => (
              <label key={key}>
                {label}
                <input
                  type="number"
                  step="0.0001"
                  value={(values[key] as number | null) ?? ""}
                  onChange={(event) =>
                    setValues({
                      ...values,
                      [key]: event.target.value
                        ? Number(event.target.value)
                        : null,
                    })
                  }
                />
              </label>
            ))}
            <label>
              申购状态
              <input
                value={values.purchase_status || ""}
                onChange={(event) =>
                  setValues({ ...values, purchase_status: event.target.value })
                }
              />
            </label>
            <label>
              基金管理人
              <input
                value={values.fund_manager || ""}
                onChange={(event) =>
                  setValues({ ...values, fund_manager: event.target.value })
                }
              />
            </label>
            <label>
              QDII 额度日期
              <input
                type="date"
                value={values.qdii_quota_date || ""}
                onChange={(event) =>
                  setValues({ ...values, qdii_quota_date: event.target.value })
                }
              />
            </label>
            <label>
              修正说明 *
              <input
                required
                value={note}
                onChange={(event) => setNote(event.target.value)}
                placeholder="说明数据来源或修正原因"
              />
            </label>
          </div>
          <button className="primary-button">保存修正</button>
        </form>
      )}
    </Dialog>
  );
}

function SettingsDialog({ onClose }: { onClose: () => void }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    void api.getSettings().then(setSettings);
  }, []);

  return (
    <Dialog title="本地工具设置" eyebrow="SETTINGS" onClose={onClose}>
      {settings ? (
        <form
          className="dialog-form"
          onSubmit={async (event) => {
            event.preventDefault();
            setSettings(await api.saveSettings(settings));
            setMessage("设置已保存");
          }}
        >
          {message && <Banner tone="success">{message}</Banner>}
          <div className="two-col">
            <label>
              权益目标
              <div className="suffix-input">
                <input
                  type="number"
                  min="1"
                  max="99"
                  value={settings.target_equity}
                  onChange={(event) =>
                    setSettings({
                      ...settings,
                      target_equity: Number(event.target.value),
                    })
                  }
                />
                <span>%</span>
              </div>
            </label>
            <label>
              再平衡缓冲带
              <div className="suffix-input">
                <input
                  type="number"
                  min="1"
                  max="40"
                  value={settings.rebalance_band}
                  onChange={(event) =>
                    setSettings({
                      ...settings,
                      rebalance_band: Number(event.target.value),
                    })
                  }
                />
                <span>±%</span>
              </div>
            </label>
          </div>
          <div className="two-col">
            <label>
              早间同步时间
              <input
                type="time"
                value={settings.morning_sync}
                onChange={(event) =>
                  setSettings({ ...settings, morning_sync: event.target.value })
                }
              />
            </label>
            <label>
              晚间同步时间
              <input
                type="time"
                value={settings.evening_sync}
                onChange={(event) =>
                  setSettings({ ...settings, evening_sync: event.target.value })
                }
              />
            </label>
          </div>
          <label className="switch-row">
            <input
              type="checkbox"
              checked={settings.notifications_enabled}
              onChange={(event) =>
                setSettings({
                  ...settings,
                  notifications_enabled: event.target.checked,
                })
              }
            />
            <span>
              启用 macOS 系统通知
              <small>通知失败时仍会保留应用内提醒</small>
            </span>
          </label>
          <p className="form-hint">
            修改同步时间后，重启本地服务生效。服务始终只绑定 127.0.0.1。
          </p>
          <div className="dialog-actions">
            <button className="secondary-button" type="button" onClick={onClose}>
              关闭
            </button>
            <button className="primary-button" type="submit">
              保存设置
            </button>
          </div>
        </form>
      ) : (
        <EmptyState title="正在读取设置" copy="请稍候…" />
      )}
    </Dialog>
  );
}

function Dialog({
  title,
  eyebrow,
  onClose,
  wide,
  children,
}: {
  title: string;
  eyebrow: string;
  onClose: () => void;
  wide?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className={`dialog ${wide ? "wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <p className="eyebrow">{eyebrow}</p>
            <h2>{title}</h2>
          </div>
          <button aria-label="关闭" onClick={onClose}>
            ×
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}

function Banner({
  tone,
  children,
}: {
  tone: "error" | "success";
  children: React.ReactNode;
}) {
  return <div className={`banner ${tone}`}>{children}</div>;
}

function EmptyState({ title, copy }: { title: string; copy: string }) {
  return (
    <div className="empty-state">
      <span>◎</span>
      <strong>{title}</strong>
      <p>{copy}</p>
    </div>
  );
}

export default App;
