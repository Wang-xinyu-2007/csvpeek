# csvpeek

拿到任何 CSV，先跑它看一眼：**多少行、什么编码、什么分隔符、每列什么类型、缺了多少值、前几行长什么样。**

零依赖——只用 Python 标准库，`python csvpeek.py 文件.csv` 直接跑，不用 `pip install` 任何东西。

![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)
![Tests](https://github.com/Wang-xinyu-2007/csvpeek/actions/workflows/tests.yml/badge.svg)

---

## CSV 是什么

**就是一个用逗号隔开的纯文本表格。** 没有样式、没有公式，用记事本就能打开：

```csv
学号,姓名,课程,成绩
2024110301,林知远,数学分析,92
2024110302,陈屿,数学分析,78
```

- 第一行是**表头**（列名），后面每行一条记录；
- 用 Excel 打开就是一张表，用记事本打开就是上面这几行字——同一份数据，两种看法；
- 教务系统导出的成绩、问卷星导出的问卷、实验仪器导出的数据、Kaggle 数据集，**全是 CSV**。

**但真实世界的 CSV 一点都不整齐**，你会踩到这些坑：

| 坑 | 现象 |
| --- | --- |
| 编码 | 中文 Windows 的 Excel 存 CSV 默认是 **GBK**，Python 按 UTF-8 读就报错或乱码 |
| 分隔符 | 有的是逗号 `,`，有的是分号 `;`（欧洲习惯），有的是 Tab |
| 类型 | 学号 `2024110301` 是数字，但**求平均没有意义**；成绩里混进一个"缺考"，整列就变文本 |
| 缺失 | 空单元格、`NA`、`-`、`无`，各家用各家的写法 |

`csvpeek` 就是先帮你把这些看清楚。**分析数据的第一步永远是「看一眼数据长什么样」**，不是直接写代码。

---

## 快速开始

```bash
git clone https://github.com/Wang-xinyu-2007/csvpeek.git
cd csvpeek

# 看一个文件
python csvpeek.py examples/成绩单.csv

# 看每列的统计
python csvpeek.py examples/成绩单.csv --stats

# 转成 Markdown 表格，直接粘进作业/报告
python csvpeek.py examples/成绩单.csv --md
```

`examples/` 里放了三个文件：

- `成绩单.csv`：UTF-8，逗号分隔
- `成绩单_gbk.csv`：同样的内容，**GBK 编码**（模拟 Excel 存出来的样子）
- `实验数据.csv`：**分号分隔**，还有缺失值

---

## 用法

| 命令 | 作用 |
| --- | --- |
| `python csvpeek.py 文件.csv` | 概览 + 前 10 行 |
| `--head 30` | 预览 30 行（`0` 表示不预览） |
| `--stats` | 每列的统计（缺失、唯一值、最小、中位数、最大、平均） |
| `--md` | 输出 Markdown 表格 |
| `--encoding gbk` | 手动指定编码（自动识别失败时用） |
| `--delimiter ';'` | 手动指定分隔符 |
| `--help` | 所有参数 |

---

## 输出长什么样

```text
$ python csvpeek.py examples/成绩单.csv

文件     examples/成绩单.csv
大小     0.5 KB
编码     utf-8-sig
分隔符   , （逗号）
规模     12 行 × 5 列

【列概览】
#  列名  类型  缺失  唯一值  示例
-  ----  ----  ----  ------  ----------
1  学号  id    0     4       2024110301
2  姓名  text  0     4       林知远
3  课程  text  0     3       数学分析
4  学分  int   0     3       5
5  成绩  int   0     12      92

【前 10 行】
学号        姓名    课程      学分  成绩
----------  ------  --------  ----  ----
2024110301  林知远  数学分析  5     92
2024110301  林知远  高等代数  4     88
...
```

注意两件事：

1. **学号的类型是 `id`，不是 `int`** —— 它长得像数字，但算平均分没有意义，前导零也会丢；
2. **中文列名对齐了** —— 终端里一个汉字占两格，用 `len()` 对齐会歪掉，这里按显示宽度算。

```text
$ python csvpeek.py examples/成绩单_gbk.csv
编码     gb18030        <- 自动识别出来的，不用你操心
```

```text
$ python csvpeek.py examples/实验数据.csv --stats

列名      类型   缺失  唯一值  最小   中位数  最大   平均
--------  -----  ----  ------  -----  ------  -----  ------
编号      text   0     7
温度      float  1     6       23.5   24      25     24.15
压力      float  1     5       101.1  101.3   101.5  101.30
测量时间  date   0     3
备注      text   5     2
```

---

## 它是怎么做到的

| 判断 | 做法 |
| --- | --- |
| **编码** | 依次尝试 `utf-8-sig` → `utf-8` → `gb18030` → `big5` → `latin-1`，第一个不报错的就是它 |
| **分隔符** | 先让 `csv.Sniffer` 猜；猜不出来就数第一行里哪个符号出现最多（只有表头的文件 Sniffer 经常猜错） |
| **列类型** | 整列都是整数 → `int`；能转成小数 → `float`；长得像日期 → `date`；否则 `text` |
| **编号列** | 列名里带「号 / 编号 / 代码 / id」的整数列标记成 `id`，不参与统计 |
| **中文对齐** | `unicodedata.east_asian_width` 判断字符占 1 格还是 2 格 |

---

## 项目结构

```text
csvpeek/
├── csvpeek.py          # 全部实现（约 400 行，只用标准库）
├── tests/
│   └── test_csvpeek.py # 28 个单元测试
├── examples/
│   ├── 成绩单.csv
│   ├── 成绩单_gbk.csv   # 故意用 GBK 存的
│   └── 实验数据.csv     # 故意用分号分隔的
├── README.md
└── LICENSE
```

---

## 跑测试

```bash
python -m unittest discover -s tests -v
```

覆盖：UTF-8 / GBK / 乱码兜底、逗号 / 分号 / Tab / 猜不出时的兜底、整数 / 小数 / 千分位 / 百分号 / 日期 / 混合类型、
学号识别、缺失值统计、中文宽度对齐、Markdown 输出、文件不存在和给目录时的错误码。

---

## 已知限制

- 不做流式读取，几百万行的文件会占满内存（日常表格够用）
- 类型判断是启发式的：一列里混了 1% 的脏数据，整列会被判成 `text`
- 不解析引号里的换行等极端 CSV 写法（标准库 `csv` 模块会处理，但预览会错行）
- 只读不写：不改你的数据，也不生成新文件

---

## 许可

[MIT](LICENSE)
