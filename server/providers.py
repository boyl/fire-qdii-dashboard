from __future__ import annotations

import math
import re
from html import unescape
from io import BytesIO
from datetime import date, datetime, timezone
from typing import Any, Iterable
from urllib.parse import urljoin

import httpx
from pypdf import PdfReader

from .calculations import premium_rate


SAFE_QDII_PAGE = "https://www.safe.gov.cn/safe/2018/0425/16849.html"


def _clean(value: Any) -> Any:
    if value is None:
        return None
    try:
        if math.isnan(float(value)):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        stripped = value.strip()
        if stripped in {"", "---", "--", "nan", "None"}:
            return None
        return stripped
    return value


def _number(value: Any) -> float | None:
    value = _clean(value)
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None


def _money_amount(value: Any) -> float | None:
    text = _text(value)
    if not text:
        return None
    match = re.search(r"([0-9][\d,.]*)\s*(万|亿)?", text)
    if not match:
        return None
    number = float(match.group(1).replace(",", ""))
    multiplier = {"万": 10_000, "亿": 100_000_000}.get(match.group(2), 1)
    return number * multiplier


def _text(value: Any) -> str | None:
    value = _clean(value)
    return None if value is None else str(value)


def _date_text(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    text = text[:10]
    if len(text) == 5 and text[2] == "-":
        return f"{datetime.now().year}-{text}"
    return text


def _pick(row: dict[str, Any] | None, *names: str) -> Any:
    if not row:
        return None
    for name in names:
        if name in row and _clean(row[name]) is not None:
            return _clean(row[name])
    for key, value in row.items():
        if any(name in str(key) for name in names) and _clean(value) is not None:
            return _clean(value)
    return None


def _key_value_frame(frame: Any) -> dict[str, Any]:
    if frame is None or getattr(frame, "empty", True):
        return {}
    columns = list(frame.columns)
    if len(columns) < 2:
        return {}
    return {
        str(row[columns[0]]).strip(): row[columns[1]]
        for _, row in frame.iterrows()
    }


def _normalize_manager_name(value: Any) -> str:
    return re.sub(r"[\s（）()]", "", str(value or ""))


def _parse_qdii_quota_text(text: str) -> dict[str, float]:
    quotas: dict[str, float] = {}
    pattern = re.compile(
        r"^\d+\s+(.+?)\s+\d{4}\.\d{2}\.\d{2}\s+([0-9]+(?:\.[0-9]+)?)\s*$"
    )
    for line in text.splitlines():
        match = pattern.match(line.strip())
        if match:
            quotas[_normalize_manager_name(match.group(1))] = (
                float(match.group(2)) * 100_000_000
            )
    return quotas


def _parse_eastmoney_basic_html(text: str) -> dict[str, str]:
    scale_match = re.search(
        r">规模</a>\s*[：:]\s*([0-9][\d,.]*)\s*亿元",
        text,
        flags=re.IGNORECASE,
    )
    manager_match = re.search(
        r"管\s*理\s*人</span>\s*[：:]\s*<a[^>]*>([^<]+)</a>",
        text,
        flags=re.IGNORECASE,
    )
    tracking_error_match = re.search(
        r"年化跟踪误差[：:]?</a>\s*([0-9]+(?:\.[0-9]+)?)%",
        text,
        flags=re.IGNORECASE,
    )
    benchmark_match = re.search(
        r"跟踪标的[：:]?</a>\s*([^<|]+)",
        text,
        flags=re.IGNORECASE,
    )
    result: dict[str, str] = {}
    if scale_match:
        result["最新规模"] = f"{scale_match.group(1)}亿"
    if manager_match:
        result["基金公司"] = unescape(manager_match.group(1)).strip()
    if tracking_error_match:
        result["公开年化跟踪误差"] = tracking_error_match.group(1)
    if benchmark_match:
        result["公开跟踪标的"] = unescape(benchmark_match.group(1)).strip()
    return result


def _match_qdii_manager(
    value: Any, quotas: dict[str, float]
) -> tuple[str | None, float | None]:
    manager = _text(value)
    normalized = _normalize_manager_name(manager)
    if not normalized:
        return manager, None
    if normalized in quotas:
        return manager, quotas[normalized]
    candidates = [
        name
        for name in quotas
        if name.startswith(normalized) or normalized.startswith(name)
    ]
    if len(candidates) == 1:
        matched = candidates[0]
        return matched, quotas[matched]
    return manager, None


def _rows_by_code(frame: Any, candidates: Iterable[str]) -> dict[str, dict]:
    if frame is None or getattr(frame, "empty", True):
        return {}
    records = frame.to_dict(orient="records")
    output = {}
    for row in records:
        code = _pick(row, *candidates)
        if code is not None:
            output[str(code).zfill(6)] = row
    return output


def _series_from_frame(
    frame: Any, date_candidates: Iterable[str], value_candidates: Iterable[str]
) -> dict[str, float]:
    if frame is None or getattr(frame, "empty", True):
        return {}
    output = {}
    for row in frame.to_dict(orient="records"):
        raw_date = _pick(row, *date_candidates)
        value = _number(_pick(row, *value_candidates))
        if raw_date is not None and value is not None:
            output[str(raw_date)[:10]] = value
    return output


def _notice_limit(text: str) -> float | None:
    compact = re.sub(r"\s+", "", text or "")
    patterns = (
        r"该(?:分级)?基金份额的限制(?:申购)?金额(?:（单位：元）)?[:：]?([0-9][\d,.]*)(万|亿)?元?",
        r"限制申购(?:（[^）]*）|\([^)]*\))?金额(?:（单位：人民币元）)?[:：]?([0-9][\d,.]*)(万|亿)?元?",
        r"累计金额限制调整为[:：]?([0-9][\d,.]*)(万|亿)?元",
        r"业务限额为[:：]?([0-9][\d,.]*)(万|亿)?元",
        r"调整后限额(?:为)?[:：]?([0-9][\d,.]*)(万|亿)?元",
        r"限额为[:：]?([0-9][\d,.]*)(万|亿)?元",
    )
    for pattern in patterns:
        match = re.search(pattern, compact)
        if not match:
            continue
        value = float(match.group(1).replace(",", ""))
        multiplier = {"万": 10_000, "亿": 100_000_000}.get(match.group(2), 1)
        return value * multiplier
    return None


def _direct_notice_limit(text: str) -> tuple[float | None, bool]:
    compact = re.sub(r"\s+", "", text or "")
    direct_prefix = r"(?:本公司|基金公司|建信基金)?直销(?:机构|渠道|柜台|电子交易平台|平台)"
    direct_patterns = (
        direct_prefix
        + r".{0,300}?"
        + r"(?:金额应不超过|金额不超过|业务限额为|限额为|限制申购金额)"
        + r"[:：]?([0-9][\d,.]*)(万|亿)?元",
        direct_prefix
        + r".{0,300}?(?:累计)?(?:高于|超过)([0-9][\d,.]*)(万|亿)?元",
    )
    for pattern in direct_patterns:
        direct_match = re.search(pattern, compact)
        if direct_match:
            value = float(direct_match.group(1).replace(",", ""))
            multiplier = {"万": 10_000, "亿": 100_000_000}.get(
                direct_match.group(2), 1
            )
            return value * multiplier, True
    return _notice_limit(text), False


def _notice_effective_date(text: str) -> date | None:
    compact = re.sub(r"\s+", "", text or "")
    match = re.search(
        r"(?:起始日|自)(20\d{2})年(\d{1,2})月(\d{1,2})日",
        compact,
    )
    if not match:
        return None
    return date(*(int(part) for part in match.groups()))


class AKShareProvider:
    name = "AKShare / 东方财富"
    notice_source = "天天基金公告"

    @staticmethod
    def _ak():
        try:
            import akshare as ak
        except ImportError as exc:
            raise RuntimeError("尚未安装 AKShare，请先运行安装脚本") from exc
        return ak

    @staticmethod
    def _fetch_notice_limit(code: str) -> tuple[float | None, dict | None]:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": f"https://fundf10.eastmoney.com/jjgg_{code}.html",
        }
        with httpx.Client(
            timeout=12,
            follow_redirects=True,
            headers=headers,
        ) as client:
            response = client.get(
                "https://api.fund.eastmoney.com/f10/JJGG",
                params={
                    "fundcode": code,
                    "pageIndex": 1,
                    "pageSize": 30,
                    "type": 5,
                },
            )
            response.raise_for_status()
            notices = response.json().get("Data") or []
            for notice in notices:
                title = str(notice.get("TITLE") or "")
                if "申购" not in title or not any(
                    token in title for token in ("限额", "金额限制", "大额")
                ):
                    continue
                if "恢复大额申购" in title:
                    return None, {
                        "report_id": notice.get("ID"),
                        "title": title,
                        "notice_date": notice.get("PUBLISHDATEDesc"),
                        "result": "unlimited",
                    }
                report_id = notice.get("ID")
                if not report_id:
                    continue
                content_response = client.get(
                    "https://np-cnotice-fund.eastmoney.com/api/content/ann",
                    params={
                        "client_source": "web_fund",
                        "show_all": 1,
                        "art_code": report_id,
                    },
                )
                content_response.raise_for_status()
                content_data = content_response.json().get("data") or {}
                content = str(content_data.get("notice_content") or "")
                effective_date = _notice_effective_date(content)
                if effective_date and effective_date > date.today():
                    continue
                limit, direct_specific = _direct_notice_limit(content)
                if limit is not None and limit > 0:
                    return limit, {
                        "report_id": report_id,
                        "title": title,
                        "notice_date": content_data.get("notice_date"),
                        "effective_date": (
                            effective_date.isoformat() if effective_date else None
                        ),
                        "limit": limit,
                        "attachment": content_data.get("attach_url"),
                        "limit_channel": (
                            "基金公司直销渠道"
                            if direct_specific
                            else "基金公司直销渠道（全渠道公告）"
                        ),
                    }
                return None, {
                    "report_id": report_id,
                    "title": title,
                    "notice_date": content_data.get("notice_date"),
                    "effective_date": (
                        effective_date.isoformat() if effective_date else None
                    ),
                    "attachment": content_data.get("attach_url"),
                    "result": "unparsed",
                }
        return None, None

    @staticmethod
    def _fetch_qdii_quotas() -> tuple[dict[str, float], str | None, dict]:
        headers = {"User-Agent": "Mozilla/5.0"}
        with httpx.Client(
            timeout=20,
            follow_redirects=True,
            headers=headers,
        ) as client:
            page = client.get(SAFE_QDII_PAGE)
            page.raise_for_status()
            pdf_match = re.search(
                r'href=["\']([^"\']+\.pdf)["\']',
                page.text,
                flags=re.IGNORECASE,
            )
            if not pdf_match:
                raise RuntimeError("外汇局页面未提供 QDII 额度表")
            pdf_url = urljoin(str(page.url), pdf_match.group(1))
            response = client.get(pdf_url)
            response.raise_for_status()
        text = "\n".join(
            page.extract_text() or ""
            for page in PdfReader(BytesIO(response.content)).pages
        )
        quotas = _parse_qdii_quota_text(text)
        if not quotas:
            raise RuntimeError("未能解析 QDII 额度表")
        date_match = re.search(
            r'<meta\s+name=["\']PubDate["\']\s+content=["\']([^"\']+)',
            page.text,
            flags=re.IGNORECASE,
        )
        quota_date = date_match.group(1)[:10] if date_match else None
        return quotas, quota_date, {
            "page": SAFE_QDII_PAGE,
            "attachment": pdf_url,
            "quota_date": quota_date,
        }

    @staticmethod
    def _fetch_eastmoney_basic(code: str) -> dict[str, str]:
        with httpx.Client(
            timeout=12,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as client:
            response = client.get(f"https://fund.eastmoney.com/{code}.html")
            response.raise_for_status()
        basic = _parse_eastmoney_basic_html(response.text)
        if not basic:
            raise RuntimeError("未能解析基金规模与管理人")
        return basic

    def collect(self, watches: list[dict], mode: str = "full") -> dict[str, dict]:
        ak = self._ak()
        now = datetime.now(timezone.utc).isoformat()
        purchase_rows: dict[str, dict] = {}
        estimate_rows: dict[str, dict] = {}
        etf_rows: dict[str, dict] = {}
        lof_rows: dict[str, dict] = {}
        basic_rows: dict[str, dict] = {}
        basic_sources: dict[str, str] = {}
        basic_source_urls: dict[str, str] = {}
        basic_errors: dict[str, str] = {}
        public_metrics: dict[str, dict[str, str]] = {}
        public_metric_errors: dict[str, str] = {}
        qdii_quotas: dict[str, float] = {}
        qdii_quota_date: str | None = None
        qdii_quota_raw: dict | None = None
        batch_errors: list[str] = []

        if mode in {"morning", "full"}:
            try:
                purchase_rows = _rows_by_code(
                    ak.fund_purchase_em(), ("基金代码", "代码")
                )
            except Exception as exc:
                batch_errors.append(f"申购状态：{exc}")

        if mode in {"evening", "full"}:
            try:
                estimate_rows = _rows_by_code(
                    ak.fund_value_estimation_em(symbol="QDII"),
                    ("基金代码", "代码"),
                )
            except Exception as exc:
                batch_errors.append(f"净值估算：{exc}")

        exchange_codes = {
            str(watch.get("exchange_code") or "").zfill(6)
            for watch in watches
            if watch.get("exchange_code")
        }
        off_exchange_watches = [
            watch for watch in watches if not watch.get("exchange_code")
        ]
        if mode in {"evening", "full"}:
            for watch in watches:
                code = str(watch["fund_code"]).zfill(6)
                try:
                    public_metrics[code] = self._fetch_eastmoney_basic(code)
                except Exception as exc:
                    public_metric_errors[code] = str(exc)
        if exchange_codes and mode in {"evening", "full"}:
            try:
                etf_rows = _rows_by_code(ak.fund_etf_spot_em(), ("代码",))
            except Exception as exc:
                batch_errors.append(f"ETF 行情：{exc}")
            try:
                lof_rows = _rows_by_code(ak.fund_lof_spot_em(), ("代码",))
            except Exception as exc:
                batch_errors.append(f"LOF 行情：{exc}")
        if off_exchange_watches and mode in {"evening", "full"}:
            for watch in off_exchange_watches:
                code = str(watch["fund_code"]).zfill(6)
                try:
                    basic_rows[code] = _key_value_frame(
                        ak.fund_individual_basic_info_xq(symbol=code)
                    )
                    basic_sources[code] = "雪球基金"
                    basic_source_urls[code] = (
                        f"https://danjuanfunds.com/djapi/fund/{code}"
                    )
                except Exception as exc:
                    try:
                        basic_rows[code] = (
                            public_metrics.get(code)
                            or self._fetch_eastmoney_basic(code)
                        )
                        basic_sources[code] = "天天基金"
                        basic_source_urls[code] = (
                            f"https://fund.eastmoney.com/{code}.html"
                        )
                    except Exception as fallback_exc:
                        basic_errors[code] = f"{exc}; 天天基金回退：{fallback_exc}"
            try:
                (
                    qdii_quotas,
                    qdii_quota_date,
                    qdii_quota_raw,
                ) = self._fetch_qdii_quotas()
            except Exception as exc:
                batch_errors.append(f"QDII 外汇额度：{exc}")

        output: dict[str, dict] = {}
        for watch in watches:
            code = str(watch["fund_code"]).zfill(6)
            purchase = purchase_rows.get(code)
            estimate_row = estimate_rows.get(code)
            exchange_code = (
                str(watch.get("exchange_code")).zfill(6)
                if watch.get("exchange_code")
                else None
            )
            market = (
                etf_rows.get(exchange_code or "")
                or lof_rows.get(exchange_code or "")
                or None
            )
            errors = list(batch_errors)
            if code in basic_errors:
                errors.append(f"基金规模：{basic_errors[code]}")
            if code in public_metric_errors:
                errors.append(
                    f"公开年化跟踪误差：{public_metric_errors[code]}"
                )
            basic = basic_rows.get(code) or {}
            public_metric = public_metrics.get(code) or {}
            fund_values: dict[str, float] = {}
            nav = _number(
                _pick(
                    estimate_row,
                    "公布数据-单位净值",
                    "单位净值",
                )
            )
            business_date = _date_text(
                _pick(
                    purchase,
                    "最新净值/万份收益-报告时间",
                    "报告时间",
                )
            )

            if mode in {"evening", "full"}:
                try:
                    nav_frame = ak.fund_open_fund_info_em(
                        symbol=code, indicator="单位净值走势"
                    )
                    fund_values = _series_from_frame(
                        nav_frame, ("净值日期", "日期"), ("单位净值", "净值")
                    )
                    if fund_values:
                        latest_date = max(fund_values)
                        business_date = latest_date
                        nav = fund_values[latest_date]
                except Exception as exc:
                    errors.append(f"历史净值：{exc}")

            estimate = _number(
                _pick(estimate_row, "估算数据-估算值", "估算值")
            )
            market_price = _number(_pick(market, "最新价", "市价"))
            iopv = _number(_pick(market, "IOPV实时估值", "IOPV"))
            fund_manager = _text(basic.get("基金公司"))
            fund_scale = _money_amount(basic.get("最新规模"))
            fund_scale_source_url = basic_source_urls.get(code)
            if market:
                latest_shares = _number(_pick(market, "最新份额"))
                scale_value = nav or iopv or market_price
                if latest_shares is not None and scale_value is not None:
                    fund_scale = latest_shares * scale_value
                    market_prefix = (
                        "sh" if (exchange_code or "").startswith("5") else "sz"
                    )
                    fund_scale_source_url = (
                        f"https://quote.eastmoney.com/"
                        f"{market_prefix}{exchange_code}.html"
                    )
            fund_manager, manager_qdii_quota_usd = _match_qdii_manager(
                fund_manager,
                qdii_quotas,
            )
            premium, premium_basis = premium_rate(market_price, iopv, nav)
            estimate_error = (
                round((estimate - nav) / nav * 100, 4)
                if estimate is not None and nav not in (None, 0)
                else _number(_pick(estimate_row, "估算偏差"))
            )
            purchase_status = _text(_pick(purchase, "申购状态"))
            daily_limit = _number(_pick(purchase, "日累计限定金额"))
            limit_notice = None
            direct_daily_limit = None
            if (
                mode in {"morning", "full"}
                and not exchange_code
            ):
                try:
                    notice_limit, limit_notice = self._fetch_notice_limit(code)
                    if notice_limit is not None:
                        direct_daily_limit = notice_limit
                        if daily_limit is None or daily_limit <= 0:
                            daily_limit = notice_limit
                except Exception as exc:
                    errors.append(f"直销限额公告：{exc}")

            output[code] = {
                "fund_code": code,
                "name": _text(
                    _pick(
                        purchase or estimate_row or market,
                        "基金简称",
                        "基金名称",
                        "名称",
                    )
                ),
                "business_date": business_date,
                "estimate": estimate,
                "nav": nav
                or _number(_pick(purchase, "最新净值/万份收益", "最新净值")),
                "estimate_error": estimate_error,
                "market_price": market_price,
                "iopv": iopv,
                "premium": premium,
                "premium_basis": premium_basis,
                "tracking_error": _number(
                    public_metric.get("公开年化跟踪误差")
                ),
                "tracking_error_source_url": (
                    f"https://fundf10.eastmoney.com/tsdata_{code}.html"
                    if public_metric.get("公开年化跟踪误差")
                    else None
                ),
                "tracking_error_as_of": (
                    business_date
                    if public_metric.get("公开年化跟踪误差")
                    else None
                ),
                "tracking_error_method": (
                    "东方财富 Choice 公布年化跟踪误差"
                    if public_metric.get("公开年化跟踪误差")
                    else None
                ),
                "tracking_error_stale": False,
                "public_benchmark": public_metric.get("公开跟踪标的"),
                "purchase_status": purchase_status,
                "daily_limit": daily_limit,
                "channel_daily_limit": direct_daily_limit,
                "limit_channel": (
                    limit_notice.get("limit_channel") if limit_notice else None
                ),
                "limit_source_url": (
                    limit_notice.get("attachment") if limit_notice else None
                ),
                "limit_effective_date": (
                    limit_notice.get("effective_date") if limit_notice else None
                ),
                "fund_scale": fund_scale,
                "fund_scale_source_url": (
                    fund_scale_source_url if fund_scale is not None else None
                ),
                "fund_manager": fund_manager,
                "manager_qdii_quota_usd": manager_qdii_quota_usd,
                "qdii_quota_date": (
                    qdii_quota_date if manager_qdii_quota_usd is not None else None
                ),
                "qdii_quota_source_url": (
                    (qdii_quota_raw or {}).get("attachment")
                    if manager_qdii_quota_usd is not None
                    else None
                ),
                "source_time": now,
                "source": " + ".join(
                    [
                        self.name,
                        *([basic_sources[code]] if code in basic_sources else []),
                        *(
                            ["国家外汇管理局"]
                            if manager_qdii_quota_usd is not None
                            else []
                        ),
                        *(
                            [self.notice_source]
                            if limit_notice and daily_limit
                            else []
                        ),
                        *(
                            ["东方财富 Choice"]
                            if public_metric.get("公开年化跟踪误差")
                            else []
                        ),
                    ]
                ),
                "errors": errors,
                "raw": {
                    "purchase": purchase,
                    "estimate": estimate_row,
                    "market": market,
                    "basic": basic,
                    "public_metric": public_metric or None,
                    "qdii_quota": (
                        {
                            **(qdii_quota_raw or {}),
                            "fund_manager": fund_manager,
                            "quota_usd": manager_qdii_quota_usd,
                        }
                        if manager_qdii_quota_usd is not None
                        else None
                    ),
                    "limit_notice": limit_notice,
                },
            }
        return output
