"""csvpeek 的单元测试：python -m unittest discover -s tests -v"""

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import csvpeek  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


class TestDecode(unittest.TestCase):
    def test_utf8(self):
        text, encoding = csvpeek.decode_bytes("姓名,成绩\n张三,90\n".encode("utf-8"))
        self.assertEqual(encoding, "utf-8-sig")
        self.assertIn("张三", text)

    def test_gbk(self):
        # 中文 Windows 上 Excel 存出来的就是这种
        text, encoding = csvpeek.decode_bytes("姓名,成绩\n张三,90\n".encode("gbk"))
        self.assertEqual(encoding, "gb18030")
        self.assertIn("张三", text)

    def test_never_fails(self):
        text, encoding = csvpeek.decode_bytes(b"\xff\xfe\x00broken")
        self.assertIsInstance(text, str)
        self.assertEqual(encoding, "latin-1")


class TestDelimiter(unittest.TestCase):
    def test_comma(self):
        self.assertEqual(csvpeek.detect_delimiter("a,b,c\n1,2,3\n"), ",")

    def test_semicolon(self):
        self.assertEqual(csvpeek.detect_delimiter("a;b;c\n1;2;3\n"), ";")

    def test_tab(self):
        self.assertEqual(csvpeek.detect_delimiter("a\tb\tc\n1\t2\t3\n"), "\t")

    def test_fallback_when_sniffer_fails(self):
        # 只有一行表头时 Sniffer 经常懵，兜底逻辑要能数出来
        self.assertEqual(csvpeek.detect_delimiter("a|b|c"), "|")


class TestClassify(unittest.TestCase):
    def test_int(self):
        kind, numbers = csvpeek.classify_values(["1", "2", "3"])
        self.assertEqual(kind, "int")
        self.assertEqual(numbers, [1.0, 2.0, 3.0])

    def test_float(self):
        kind, _ = csvpeek.classify_values(["1.5", "2.5"])
        self.assertEqual(kind, "float")

    def test_thousands_separator(self):
        kind, numbers = csvpeek.classify_values(["1,234.5", "2,000"])
        self.assertEqual(kind, "float")
        self.assertEqual(numbers, [1234.5, 2000.0])

    def test_percent(self):
        kind, numbers = csvpeek.classify_values(["12%", "34%"])
        self.assertEqual(kind, "float")
        self.assertEqual(numbers, [12.0, 34.0])

    def test_date(self):
        kind, _ = csvpeek.classify_values(["2026-01-01", "2026/1/2"])
        self.assertEqual(kind, "date")

    def test_mixed_is_text(self):
        kind, _ = csvpeek.classify_values(["90", "缺考"])
        self.assertEqual(kind, "text")

    def test_empty(self):
        self.assertEqual(csvpeek.classify_values([]), ("text", []))


class TestProfile(unittest.TestCase):
    def setUp(self):
        rows = [
            ["学号", "姓名", "成绩", "备注"],
            ["2024110301", "张三", "92", ""],
            ["2024110302", "李四", "78", "补考"],
            ["2024110303", "王五", "NA", ""],
        ]
        self.profiles = csvpeek.profile_columns(rows)

    def test_id_is_not_a_number(self):
        student_id = self.profiles[0]
        self.assertEqual(student_id.kind, "id")
        self.assertEqual(student_id.numbers, [])

    def test_missing_counted(self):
        self.assertEqual(self.profiles[2].missing, 1)  # 成绩里的 NA
        self.assertEqual(self.profiles[3].missing, 2)  # 两条空的备注

    def test_unique_counted(self):
        self.assertEqual(self.profiles[1].unique, 3)


class TestLayout(unittest.TestCase):
    def test_display_width(self):
        self.assertEqual(csvpeek.display_width("abc"), 3)
        self.assertEqual(csvpeek.display_width("中文"), 4)
        self.assertEqual(csvpeek.display_width("a中"), 3)

    def test_truncate_by_width(self):
        self.assertEqual(csvpeek.truncate("abcdef", 4), "abc…")
        self.assertEqual(csvpeek.truncate("中文", 10), "中文")

    def test_every_line_has_same_width(self):
        """表格每一行的显示宽度必须一样，否则就歪了。"""
        text = csvpeek.render_table(["姓名", "成绩"], [["张三", "90"], ["李四", "100"]])
        widths = {csvpeek.display_width(line) for line in text.splitlines()}
        self.assertEqual(len(widths), 1, msg=f"宽度不一致：{widths}")


class TestOutput(unittest.TestCase):
    def test_markdown(self):
        text = csvpeek.render_markdown([["a", "b"], ["1", "2"]])
        self.assertIn("| a | b |", text)
        self.assertIn("| --- | --- |", text)

    def test_pretty_delimiter(self):
        self.assertIn("逗号", csvpeek.pretty_delimiter(","))
        self.assertIn("Tab", csvpeek.pretty_delimiter("\t"))


class TestCli(unittest.TestCase):
    def _run(self, argv):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = csvpeek.main(argv)
        return code, buffer.getvalue()

    def test_overview(self):
        code, output = self._run([str(EXAMPLES / "成绩单.csv")])
        self.assertEqual(code, 0)
        self.assertIn("编码", output)
        self.assertIn("列概览", output)

    def test_gbk_file_is_readable(self):
        code, output = self._run([str(EXAMPLES / "成绩单_gbk.csv")])
        self.assertEqual(code, 0)
        self.assertIn("gb18030", output)
        self.assertIn("成绩", output)

    def test_stats(self):
        code, output = self._run([str(EXAMPLES / "实验数据.csv"), "--stats"])
        self.assertEqual(code, 0)
        self.assertIn("中位数", output)

    def test_markdown_mode(self):
        code, output = self._run([str(EXAMPLES / "成绩单.csv"), "--md", "--head", "2"])
        self.assertEqual(code, 0)
        self.assertTrue(output.startswith("| 学号"))

    def test_missing_file(self):
        code, _ = self._run(["definitely-not-here.csv"])
        self.assertEqual(code, 2)

    def test_directory(self):
        code, _ = self._run([str(EXAMPLES)])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
