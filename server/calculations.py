from __future__ import annotations

import math
import statistics
from datetime import date
from typing import Iterable, Mapping, Sequence

ASSET_KEYS = (
    "cash",
    "short_bond",
    "long_bond",
    "nasdaq100",
    "gold",
    "digital",
)


def portfolio_summary(
    amounts: Mapping[str, float],
    target_equity: float = 50,
    rebalance_band: float = 10,
) -> dict:
    values = {key: max(0.0, float(amounts.get(key, 0))) for key in ASSET_KEYS}
    total = sum(values.values())
    equity = values["nasdaq100"]
    lower = max(0.0, target_equity - rebalance_band)
    upper = min(100.0, target_equity + rebalance_band)
    ratio = equity / total * 100 if total else 0.0
    if not total:
        status = "empty"
    elif ratio < lower:
        status = "below"
    elif ratio > upper:
        status = "above"
    else:
        status = "inside"

    return {
        "total": round(total, 2),
        "equity_value": round(equity, 2),
        "equity_ratio": round(ratio, 4),
        "lower_bound": lower,
        "upper_bound": upper,
        "status": status,
        "distance_to_lower_pp": round(ratio - lower, 4),
        "distance_to_upper_pp": round(upper - ratio, 4),
        "transfer_to_lower": round(total * lower / 100 - equity, 2),
        "transfer_to_target": round(total * target_equity / 100 - equity, 2),
        "transfer_to_upper": round(total * upper / 100 - equity, 2),
        "target_equity": target_equity,
    }


def stress_portfolio(
    amounts: Mapping[str, float], scenarios: Sequence[Mapping]
) -> list[dict]:
    base = {key: max(0.0, float(amounts.get(key, 0))) for key in ASSET_KEYS}
    total_before = sum(base.values())
    output = []
    for scenario in scenarios:
        shocks = scenario.get("shocks", {})
        values = {
            key: max(
                0.0,
                base[key] * (1 + float(shocks.get(key, 0)) / 100),
            )
            for key in ASSET_KEYS
        }
        total_after = sum(values.values())
        loss = total_before - total_after
        output.append(
            {
                "name": str(scenario.get("name", "压力场景")),
                "total_before": round(total_before, 2),
                "total_after": round(total_after, 2),
                "loss": round(loss, 2),
                "loss_ratio": round(loss / total_before * 100, 4)
                if total_before
                else 0.0,
                "equity_ratio": round(
                    values["nasdaq100"] / total_after * 100, 4
                )
                if total_after
                else 0.0,
                "values": {key: round(value, 2) for key, value in values.items()},
                "weights": {
                    key: round(value / total_after * 100, 4)
                    if total_after
                    else 0.0
                    for key, value in values.items()
                },
            }
        )
    return output


def add_months(start: date, months: int) -> date:
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def sustainability_runway(
    initial_assets: float,
    annual_spending: Iterable[float],
    real_return: float,
    *,
    start_date: date | None = None,
    max_years: int = 100,
) -> list[dict]:
    initial_assets = max(0.0, float(initial_assets))
    real_return = float(real_return)
    start_date = start_date or date.today()
    annual_factor = 1 + real_return / 100
    monthly_rate = annual_factor ** (1 / 12) - 1 if annual_factor > 0 else -1.0
    max_months = max_years * 12
    output = []

    for raw_spending in annual_spending:
        spending = max(0.0, float(raw_spending))
        monthly_spending = spending / 12
        balance = initial_assets
        depleted_month: int | None = None
        if not initial_assets and spending > 0:
            depleted_month = 0
        elif spending > 0:
            for month in range(1, max_months + 1):
                balance -= monthly_spending
                if balance <= 0:
                    balance = 0
                    depleted_month = month
                    break
                balance *= 1 + monthly_rate
                if balance <= 0:
                    balance = 0
                    depleted_month = month
                    break

        sustainable = depleted_month is None
        output.append(
            {
                "annual_spending": round(spending, 2),
                "real_return": real_return,
                "sustainable": sustainable,
                "months": None if sustainable else depleted_month,
                "years": None
                if sustainable
                else round((depleted_month or 0) / 12, 2),
                "depletion_date": None
                if sustainable
                else add_months(start_date, depleted_month or 0).isoformat(),
                "ending_balance": round(balance, 2),
            }
        )
    return output


def premium_rate(
    market_price: float | None,
    iopv: float | None,
    nav: float | None,
) -> tuple[float | None, str | None]:
    if market_price is None:
        return None, None
    basis = iopv if iopv not in (None, 0) else nav
    basis_name = "IOPV" if iopv not in (None, 0) else "NAV"
    if basis in (None, 0):
        return None, None
    return round((float(market_price) - float(basis)) / float(basis) * 100, 4), basis_name


def tracking_error(
    fund_values: Mapping[str, float],
    benchmark_values: Mapping[str, float],
    *,
    min_samples: int = 30,
    window: int = 60,
) -> float | None:
    common_dates = sorted(set(fund_values).intersection(benchmark_values))
    differences = []
    for previous_date, current_date in zip(common_dates, common_dates[1:]):
        previous_fund = float(fund_values[previous_date])
        current_fund = float(fund_values[current_date])
        previous_benchmark = float(benchmark_values[previous_date])
        current_benchmark = float(benchmark_values[current_date])
        if previous_fund <= 0 or previous_benchmark <= 0:
            continue
        differences.append(
            current_fund / previous_fund
            - current_benchmark / previous_benchmark
        )
    if len(differences) < min_samples:
        return None
    differences = differences[-window:]
    if len(differences) < 2:
        return None
    return round(statistics.stdev(differences) * math.sqrt(252) * 100, 4)
