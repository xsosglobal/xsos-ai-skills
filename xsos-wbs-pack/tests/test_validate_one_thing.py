import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_wbs_pack.py"


def load():
    spec = importlib.util.spec_from_file_location("validate_wbs_pack_one_thing", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V = load()


class OneThingTest(unittest.TestCase):
    def test_title_heuristic(self):
        self.assertEqual(V.title_multi_action("试块申请、投产、结论支持写错后撤回重做"), "、")
        self.assertEqual(V.title_multi_action("新增和修改供应商"), "和")
        self.assertIsNone(V.title_multi_action("BUG 转需求时带上提交人的图文"))
        # 引号里的名字、常用词里的「与/及」不算并列。
        self.assertIsNone(V.title_multi_action("试块类型增加「批 / 单个」属性"))
        self.assertIsNone(V.title_multi_action("选择讨论参与人"))
        self.assertIsNone(V.title_multi_action("消息及时提醒"))

    def test_check_one_thing_warns_only_for_unfinished(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp)
            (pack / "02-wbs.md").write_text(
                "| wp_id | title_cn | status |\n|---|---|---|\n"
                "| WP-BE-001 | 新增和修改供应商 | todo |\n"
                "| WP-BE-002 | 删除与恢复客户 | done |\n"
                "| WP-BE-003 | 导出报表 | todo |\n", encoding="utf-8")
            errors, warnings = V.check_one_thing(pack)
            self.assertEqual(errors, [])
            self.assertEqual(len(warnings), 1)
            self.assertIn("WP-BE-001", warnings[0])
            self.assertNotIn("WP-BE-002", warnings[0])
            self.assertNotIn("WP-BE-003", warnings[0])


if __name__ == "__main__":
    unittest.main()
