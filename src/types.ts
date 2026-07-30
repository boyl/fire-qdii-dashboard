export const assetKeys = [
  "cash",
  "short_bond",
  "long_bond",
  "nasdaq100",
  "gold",
  "digital",
] as const;

export type AssetKey = (typeof assetKeys)[number];
export type AssetAmounts = Record<AssetKey, number>;

export interface AssetSnapshot extends AssetAmounts {
  id: number;
  snapshot_date: string;
  note: string;
  created_at: string;
  updated_at: string;
}

export interface Settings {
  target_equity: number;
  rebalance_band: number;
  morning_sync: string;
  evening_sync: string;
  notifications_enabled: boolean;
}

export interface PortfolioSummary {
  snapshot: AssetSnapshot | null;
  total: number;
  equity_value: number;
  equity_ratio: number;
  lower_bound: number;
  upper_bound: number;
  status: "below" | "inside" | "above" | "empty";
  distance_to_lower_pp: number;
  distance_to_upper_pp: number;
  transfer_to_lower: number;
  transfer_to_target: number;
  transfer_to_upper: number;
  target_equity: number;
}

export interface StressScenario {
  name: string;
  shocks: AssetAmounts;
}

export interface StressResult {
  name: string;
  total_before: number;
  total_after: number;
  loss: number;
  loss_ratio: number;
  equity_ratio: number;
  values: AssetAmounts;
  weights: AssetAmounts;
}

export interface SustainabilityResult {
  annual_spending: number;
  real_return: number;
  sustainable: boolean;
  months: number | null;
  years: number | null;
  depletion_date: string | null;
  ending_balance: number;
}

export interface FundSnapshot {
  id: number;
  fund_code: string;
  business_date: string | null;
  estimate: number | null;
  nav: number | null;
  estimate_error: number | null;
  market_price: number | null;
  iopv: number | null;
  premium: number | null;
  premium_basis: string | null;
  tracking_error: number | null;
  tracking_error_source_url: string | null;
  tracking_error_as_of: string | null;
  tracking_error_method: string | null;
  tracking_error_stale: boolean;
  purchase_status: string | null;
  daily_limit: number | null;
  fund_scale: number | null;
  fund_scale_source_url: string | null;
  fund_manager: string | null;
  manager_qdii_quota_usd: number | null;
  qdii_quota_date: string | null;
  qdii_quota_source_url: string | null;
  source_time: string;
  source: string;
  stale: boolean;
  corrected: boolean;
  correction_note: string | null;
  carried_fields: string[];
}

export interface FundWatch {
  id: number;
  fund_code: string;
  name: string;
  exchange_code: string | null;
  category: string;
  benchmark: string | null;
  channel_daily_limit: number | null;
  limit_channel: string | null;
  limit_source_url: string | null;
  limit_effective_date: string | null;
  active: boolean;
  created_at: string;
  latest: FundSnapshot | null;
}

export interface Alert {
  id: number;
  fund_code: string;
  title: string;
  message: string;
  event_type: string;
  created_at: string;
  read_at: string | null;
}

export interface SyncRun {
  id: number;
  mode: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  items_total: number;
  items_succeeded: number;
  error: string | null;
}

export interface Health {
  status: string;
  database: string;
  provider: string;
  scheduler_running: boolean;
  next_jobs: Array<{ id: string; next_run: string | null }>;
  last_sync: SyncRun | null;
}
