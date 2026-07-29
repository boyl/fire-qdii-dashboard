from __future__ import annotations

import unittest
from datetime import date

from server.providers import _notice_effective_date, _notice_limit


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


if __name__ == "__main__":
    unittest.main()
