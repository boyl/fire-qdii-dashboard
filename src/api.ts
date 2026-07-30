import type {
  Alert,
  AssetAmounts,
  AssetSnapshot,
  FundSnapshot,
  FundWatch,
  Health,
  PortfolioSummary,
  Settings,
  StressResult,
  StressScenario,
  SustainabilityResult,
} from "./types";

const fieldNames: Record<string, string> = {
  fund_code: "基金代码",
  exchange_code: "场内代码",
  name: "基金名称",
  benchmark: "跟踪指数",
  category: "类型",
};

function errorDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (!item || typeof item !== "object") return null;
        const issue = item as { loc?: unknown[]; msg?: unknown };
        const field = String(issue.loc?.at(-1) ?? "");
        const label = fieldNames[field] || field;
        const reason =
          typeof issue.msg === "string" ? issue.msg : "格式不正确";
        return label ? `${label}：${reason}` : reason;
      })
      .filter(Boolean);
    if (messages.length) return messages.join("；");
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let message = `请求失败（${response.status}）`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      message = errorDetail(body.detail, message);
    } catch {
      // Keep the HTTP status when an upstream error did not return JSON.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const api = {
  getAssets: () => request<AssetSnapshot[]>("/api/assets"),
  saveAssets: (payload: AssetAmounts & { snapshot_date: string; note: string }) =>
    request<AssetSnapshot>("/api/assets", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getSummary: () => request<PortfolioSummary>("/api/portfolio/summary"),
  runStress: (scenarios: StressScenario[]) =>
    request<StressResult[]>("/api/portfolio/stress", {
      method: "POST",
      body: JSON.stringify({ scenarios }),
    }),
  runSustainability: (
    annualSpending: number[],
    realReturn: number,
    initialAssets?: number,
  ) =>
    request<SustainabilityResult[]>("/api/sustainability", {
      method: "POST",
      body: JSON.stringify({
        annual_spending: annualSpending,
        real_return: realReturn,
        initial_assets: initialAssets,
      }),
    }),
  getSettings: () => request<Settings>("/api/settings"),
  saveSettings: (settings: Settings) =>
    request<Settings>("/api/settings", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),
  getFunds: () => request<FundWatch[]>("/api/funds"),
  addFund: (payload: {
    fund_code: string;
    name?: string;
    exchange_code?: string;
    category: string;
    benchmark?: string;
    channel_daily_limit?: number;
    limit_channel?: string;
    limit_source_url?: string;
    limit_effective_date?: string;
  }) => {
    const normalized = {
      ...payload,
      name: payload.name?.trim() || undefined,
      exchange_code: payload.exchange_code?.trim() || undefined,
      benchmark: payload.benchmark?.trim() || undefined,
    };
    return request<FundWatch>("/api/funds", {
      method: "POST",
      body: JSON.stringify(normalized),
    });
  },
  deleteFund: (code: string) =>
    request<{ ok: boolean }>(`/api/funds/${code}`, { method: "DELETE" }),
  getFundHistory: (code: string) =>
    request<FundSnapshot[]>(`/api/funds/${code}/history`),
  correctSnapshot: (
    code: string,
    id: number,
    payload: Partial<FundSnapshot> & { correction_note: string },
  ) =>
    request<FundSnapshot>(`/api/funds/${code}/snapshots/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  sync: (mode: "morning" | "evening" | "full" = "full") =>
    request<{ ok: boolean; message: string }>("/api/sync", {
      method: "POST",
      body: JSON.stringify({ mode }),
    }),
  getAlerts: () => request<Alert[]>("/api/alerts"),
  readAlerts: (ids?: number[]) =>
    request<{ updated: number }>("/api/alerts/read", {
      method: "POST",
      body: JSON.stringify({ ids }),
    }),
  getHealth: () => request<Health>("/api/health"),
  restore: (payload: unknown) =>
    request<{ ok: boolean; restored: Record<string, number> }>("/api/restore", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
