from __future__ import annotations

import unittest
from datetime import date

from server.providers import (
    _match_qdii_manager,
    _money_amount,
    _notice_effective_date,
    _notice_limit,
    _parse_eastmoney_basic_html,
    _parse_qdii_quota_text,
)


class ProviderFallbackTest(unittest.TestCase):
    def test_parses_single_share_limit_notice(self):
        content = """
        调整大额申购起始日 2026 年 7 月 21 日
        下属基金份额的代码 021000
        该基金份额的限制金额 200 元
        """
        self.assertEqual(_notice_limit(content), 200)
        self.assertEqual(_notice_effective_date(content), date(2026, 7, 21))

    def test_parses_limit_from_multi_share_notice_prose(self):
        content = """
        暂停大额申购起始日 2026 年 7 月 13 日
        本基金 F 类基金份额调整投资者单日单个基金账户申购，
        业务限额为 100.00 元。
        """
        self.assertEqual(_notice_limit(content), 100)
        self.assertEqual(_notice_effective_date(content), date(2026, 7, 13))

    def test_does_not_invent_missing_limit(self):
        self.assertIsNone(_notice_limit("本基金暂停申购，恢复时间另行公告。"))

    def test_parses_fund_scale_units(self):
        self.assertEqual(_money_amount("48.87亿"), 4_887_000_000)
        self.assertEqual(_money_amount("1,250万"), 12_500_000)

    def test_parses_safe_qdii_quota_table(self):
        text = """
        65 建信基金管理有限责任公司 2026.03.23 17.70
        70 大成基金管理有限公司 2026.03.23 15.60
        证券基金类合计 972.80
        """
        quotas = _parse_qdii_quota_text(text)
        self.assertEqual(
            quotas["建信基金管理有限责任公司"],
            1_770_000_000,
        )
        self.assertEqual(quotas["大成基金管理有限公司"], 1_560_000_000)

    def test_parses_eastmoney_basic_fallback(self):
        page = """
        <a href="/gmbd_021000.html">规模</a>：31.36亿元（2026-06-30）
        <span class="letterSpace01">管 理 人</span>：
        <a href="/company/80000220.html">南方基金</a>
        """
        self.assertEqual(
            _parse_eastmoney_basic_html(page),
            {"最新规模": "31.36亿", "基金公司": "南方基金"},
        )

    def test_matches_short_manager_name_to_safe_legal_name(self):
        quotas = {
            "南方基金管理股份有限公司": 6_080_000_000,
            "广发基金管理有限公司": 4_460_000_000,
        }
        manager, quota = _match_qdii_manager("南方基金", quotas)
        self.assertEqual(manager, "南方基金管理股份有限公司")
        self.assertEqual(quota, 6_080_000_000)


if __name__ == "__main__":
    unittest.main()
