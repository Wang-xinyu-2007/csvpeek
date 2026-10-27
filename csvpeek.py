#!/usr/bin/env python3
"""csvpeek —— 把一个 CSV 文件「看一眼」。

拿到任何表格（教务系统导出的成绩、问卷星导出的问卷、实验数据、Kaggle 数据集），
先跑一遍它，你会立刻知道：多少行多少列、编码是什么、分隔符是什么、
每列是什么类型、缺了多少值、前几行长什么样。

用法：
    python csvpeek.py 数据.csv                 # 概览 + 前 10 行
    python csvpeek.py 数据.csv --stats         # 每列的统计
    python csvpeek.py 数据.csv --md            # 输出 Markdown 表格（直接粘进报告）
    python csvpeek.py 数据.csv --head 30       # 多看几行
    python csvpeek.py 数据.csv --encoding gbk  # 手动指定编码

只用标准库，不需要 pip install 任何东西。
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

__version__ = "1.0.0"

# 按顺序尝试；gb18030 是 gbk 的超集，能用 gbk 就一定能用 gb18030
ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "big5", "latin-1")

# 这些写法都当成"空值"
MISSING_TOKENS = {"", "na", "n/a", "null", "none", "-", "—", "无", "nan"}

DATE_PATTERN = re.compile(r"^\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?$")
INT_PATTERN = re.compile(r"^[+-]?\d+$")

# 这些列名里的数字是"编号"，不是"可以求平均的量"。
# 学号、订单号、邮编：长得像数字，但算均值毫无意义（还会把前导零弄丢）。
ID_NAME_PATTERN = re.compile(r"(号|编号|代码|邮编|电话|手机|id|Id|ID|uuid)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# 1. 读文件：编码和分隔符都要自动识别
# ---------------------------------------------------------------------------

def decode_bytes(raw: bytes) -> tuple[str, str]:
    """把字节解码成文本，返回 (文本, 实际用的编码)。

    中文世界的 CSV 只有两种：Excel 存的（GBK）和别人给你的（UTF-8）。
    latin-1 兜底：它永远不会失败，至少能让你看到内容大致长什么样。
    """
    for encoding in ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace"), "latin-1"


def detect_delimiter(text: str) -> str:
    """猜分隔符：逗号、分号、制表符、竖线。

    先用 csv.Sniffer 猜，猜不出来就数一数哪个符号在第一行里出现得最多
    （这个兜底很实用：只有一行表头的文件 Sniffer 经常猜错）。
    """
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except csv.Error:
        pass

    header = sample.splitlines()[0] if sample.splitlines() else ""
    counts = {d: header.count(d) for d in ",;\t|"}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def read_rows(text: str, delimiter: str) -> list[list[str]]:
    """解析成二维列表。空行直接丢掉。"""
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    return rows


# ---------------------------------------------------------------------------
# 2. 列画像：这一列是什么类型、缺了多少、有哪些值
# ---------------------------------------------------------------------------

@dataclass
class ColumnProfile:
    name: str
    kind: str = "text"        # int / float / date / text
    missing: int = 0
    unique: int = 0
    values: list[str] = field(default_factory=list)   # 非空值的原始字符串
    numbers: list[float] = field(default_factory=list)

    @property
    def numeric(self) -> bool:
        return self.kind in ("int", "float")


def is_missing(cell: str) -> bool:
    return cell.strip().lower() in MISSING_TOKENS


def classify_values(values: list[str]) -> tuple[str, list[float]]:
    """判断一列的类型，顺便把能转成数字的值转出来。"""
    numbers: list[float] = []
    all_int = True
    all_float = True
    all_date = True

    for value in values:
        text = value.strip()
        if INT_PATTERN.match(text):
            numbers.append(float(text))
            all_float = all_float and True
            continue
        all_int = False

        # "1,234.5" 这种带千分位的也认
        cleaned = text.replace(",", "").replace("%", "").replace(" ", "")
        try:
            numbers.append(float(cleaned))
        except ValueError:
            all_float = False

        if not DATE_PATTERN.match(text):
            all_date = False

    if not values:
        return "text", []
    if all_int and len(numbers) == len(values):
        return "int", numbers
    if all_float and len(numbers) == len(values):
        return "float", numbers
    if all_date:
        return "date", []
    return "text", []


def profile_columns(rows: list[list[str]]) -> list[ColumnProfile]:
    """给每一列拍个"证件照"。"""
    if not rows:
        return []

    header = rows[0]
    width = max(len(row) for row in rows)
    profiles: list[ColumnProfile] = []

    for index in range(width):
        name = header[index].strip() if index < len(header) and header[index].strip() else f"第{index + 1}列"
        cells = [row[index] if index < len(row) else "" for row in rows[1:]]
        present = [cell for cell in cells if not is_missing(cell)]

        kind, numbers = classify_values(present)

        # "学号" 这一列全是整数，但它不是数量——求平均没有意义，当成 id 处理
        if kind == "int" and ID_NAME_PATTERN.search(name):
            kind = "id"
            numbers = []

        profiles.append(ColumnProfile(
            name=name,
            kind=kind,
            missing=len(cells) - len(present),
            unique=len({cell.strip() for cell in present}),
            values=present,
            numbers=numbers,
        ))
    return profiles


# ---------------------------------------------------------------------------
# 3. 排版：中文字符占两格，必须按显示宽度对齐
# ---------------------------------------------------------------------------

def display_width(text: str) -> int:
    """字符串在终端里占几格。

    'a' 占 1 格，'中' 占 2 格。用 len() 对齐的话，中文表格会歪得没法看。
    """
    total = 0
    for char in text:
        total += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return total


def truncate(text: str, limit: int) -> str:
    """太长就截断，末尾留一个省略号（按显示宽度算，不是按字符数）。"""
    if display_width(text) <= limit:
        return text
    kept = ""
    width = 0
    for char in text:
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        if width > limit - 1:
            break
        kept += char
    return kept + "…"


def render_table(headers: list[str], rows: list[list[str]], limit: int = 24) -> str:
    """按显示宽度对齐的纯文本表格。"""
    cells = [[truncate(str(cell), limit) for cell in row] for row in rows]
    widths = [display_width(header) for header in headers]
    for row in cells:
        for index, cell in enumerate(row):
            if index < len(widths):
                widths[index] = max(widths[index], display_width(cell))

    lines = []
    lines.append("  ".join(pad(header, widths[i]) for i, header in enumerate(headers)))
    lines.append("  ".join("-" * width for width in widths))
    for row in cells:
        lines.append("  ".join(
            pad(row[i] if i < len(row) else "", widths[i]) for i in range(len(headers))
        ))
    return "\n".join(lines)


def pad(text: str, width: int) -> str:
    """补空格到指定显示宽度（左对齐）。"""
    return text + " " * max(0, width - display_width(text))


def pad_left(text: str, width: int) -> str:
    """补空格到指定显示宽度（右对齐，数字用）。"""
    return " " * max(0, width - display_width(text)) + text


# ---------------------------------------------------------------------------
# 4. 三种输出
# ---------------------------------------------------------------------------

def render_overview(rows: list[list[str]], profiles: list[ColumnProfile],
                    meta: dict, head: int) -> str:
    lines = []
    add = lines.append

    add(f"文件    {meta['path']}")
    add(f"大小    {meta['size'] / 1024:.1f} KB")
    add(f"编码    {meta['encoding']}")
    add(f"分隔符  {pretty_delimiter(meta['delimiter'])}")
    add(f"规模    {len(rows) - 1} 行 × {len(profiles)} 列")
    add("")

    add("【列概览】")
    table_rows = []
    for index, profile in enumerate(profiles, start=1):
        table_rows.append([
            str(index), profile.name, profile.kind,
            str(profile.missing), str(profile.unique),
            profile.values[0] if profile.values else "",
        ])
    add(render_table(["#", "列名", "类型", "缺失", "唯一值", "示例"], table_rows))
    add("")

    if head > 0 and len(rows) > 1:
        shown = min(head, len(rows) - 1)
        add(f"【前 {shown} 行】")
        add(render_table(rows[0], rows[1:shown + 1]))
    return "\n".join(lines)


def render_stats(profiles: list[ColumnProfile]) -> str:
    """每列的统计：数值列给均值/中位数，其它列只给缺失和唯一值。"""
    headers = ["列名", "类型", "缺失", "唯一值", "最小", "中位数", "最大", "平均"]
    rows = []
    for profile in profiles:
        row = [profile.name, profile.kind, str(profile.missing), str(profile.unique)]
        if profile.numeric and profile.numbers:
            ordered = sorted(profile.numbers)
            middle = len(ordered) // 2
            median = (ordered[middle] if len(ordered) % 2
                      else (ordered[middle - 1] + ordered[middle]) / 2)
            row += [
                f"{ordered[0]:g}", f"{median:g}", f"{ordered[-1]:g}",
                f"{sum(ordered) / len(ordered):.2f}",
            ]
        else:
            row += ["", "", "", ""]
        rows.append(row)

    # 数字列右对齐更好看
    lines = [render_table(headers, rows)]
    lines.append("")
    lines.append("提示：类型是 text 但看起来像数字的列，说明里面混了「元」「%」这类脏东西，")
    lines.append("      清洗之前先看看是什么——这正是数据分析的第一步。")
    return "\n".join(lines)


def render_markdown(rows: list[list[str]], limit: int = 0) -> str:
    """输出 Markdown 表格，可以直接粘到报告、GitHub 或作业里。"""
    if not rows:
        return ""
    headers = rows[0]
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows[1:]:
        cells = []
        for index in range(len(headers)):
            cell = row[index] if index < len(row) else ""
            cells.append(truncate(cell, limit) if limit else cell)
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def pretty_delimiter(delimiter: str) -> str:
    names = {",": ", （逗号）", ";": "; （分号）", "\t": "Tab（制表符）", "|": "| （竖线）"}
    return names.get(delimiter, repr(delimiter))


# ---------------------------------------------------------------------------
# 5. 命令行
# ---------------------------------------------------------------------------

def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="csvpeek",
        description="看一眼 CSV：规模、编码、分隔符、列类型、缺失值、前几行。",
        epilog="示例：python csvpeek.py 成绩单.csv --stats",
    )
    parser.add_argument("path", help="CSV 文件路径")
    parser.add_argument("--head", type=int, default=10, metavar="N",
                        help="预览前 N 行（默认 10，0 表示不预览）")
    parser.add_argument("--stats", action="store_true", help="显示每列的统计")
    parser.add_argument("--md", action="store_true", help="输出 Markdown 表格")
    parser.add_argument("--encoding", default=None, help="手动指定编码（默认自动识别）")
    parser.add_argument("--delimiter", default=None, help="手动指定分隔符（默认自动识别）")
    parser.add_argument("--version", action="version", version=f"csvpeek {__version__}")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    path = Path(args.path)

    if not path.exists():
        print(f"csvpeek: 文件不存在：{path}", file=sys.stderr)
        return 2
    if path.is_dir():
        print(f"csvpeek: 这是个目录，请给一个 .csv 文件：{path}", file=sys.stderr)
        return 2

    raw = path.read_bytes()
    if not raw.strip():
        print(f"csvpeek: 文件是空的：{path}", file=sys.stderr)
        return 2

    if args.encoding:
        try:
            text = raw.decode(args.encoding)
            encoding = args.encoding
        except (UnicodeDecodeError, LookupError) as exc:
            print(f"csvpeek: 用 {args.encoding} 解码失败：{exc}", file=sys.stderr)
            return 2
    else:
        text, encoding = decode_bytes(raw)

    delimiter = args.delimiter or detect_delimiter(text)
    rows = read_rows(text, delimiter)

    if len(rows) < 2:
        print("csvpeek: 只有表头没有数据行，或者根本不是 CSV", file=sys.stderr)
        return 2

    if args.md:
        print(render_markdown(rows[: args.head + 1] if args.head else rows))
        return 0

    profiles = profile_columns(rows)
    meta = {"path": path, "size": len(raw), "encoding": encoding, "delimiter": delimiter}

    if args.stats:
        print(render_stats(profiles))
    else:
        print(render_overview(rows, profiles, meta, args.head))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
