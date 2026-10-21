"""附九十五 + 附一百三十三 —— CLAUDE.md §7(工件卫生)的两条机械不变量。

## §7 说什么

> * **Results Stay Local**: `results/`, trades.csv, metrics JSON, and generated reports
>   MUST remain gitignored. Committing them is a contract violation — **a fresh clone
>   must contain zero historical performance claims.**
> * **No Numbers in Docs**: READMEs and design docs MUST NOT embed historical metrics
>   (CAGR/Sharpe/win-rate tables). They document *how to reproduce*, never *what was
>   once observed*.

本节实测(附九十五):**两条都做到了** —— 但**没有任何守卫**。本文件把"做到了"钉成"不许退化"。

## 附一百三十三:这条文档守卫的**面**比它自己声明的窄,而它对**表格**结构性失明(均实测)

附九十五 的 docstring 写着「全库 5 个 markdown(**含** `chase_up/README.md`)**没有任何一行**
同时出现『指标名 + 数值』」。那是**手工量过一次**的结论;而 `docs_with_metric_values()` 的扫描面
是 `README.md` + `docs/*.md`(**非递归**)。今天实测:

| 项 | 数 |
|---|---|
| 被 git 跟踪的 markdown | **4** |
| 旧扫描面盖住 | **2**(`README.md`、`docs/uptrend_pullback_preset_search.md`)|
| **盖不住** | **2** —— 其中就有 docstring 点名的 `chase_up/README.md` |

⇒ 同一个「面」缺陷的又一例:判据**实际覆盖的范围**与它**自陈的范围**不一致。往
`chase_up/README.md` 里贴一张 Sharpe 表,守卫**不会红**。(旧文写"5 个"而今是 4 个 ——
差的是一份被移出 `docs/` 的文档,见 `README.md` 里「历史审计报告已从 `docs/` 移除」那句:
又一次证明**手写的计数会漂** —— 与同批发现的"审计报告文首漂移"是同一种病。)

同批量掉三个**口径**问题(第三个是注入验出来的,不是推出来的):

1. **整数百分号漏报**:`_VALUE` 只认小数 ⇒ §7 点名的 win-rate tables 里 ``胜率 62%`` 这种
   **根本不报**。已补 ``\\d+\\s*%``。
2. **章节号会被当成小数**(**既有**假报向量,非本批引入):全库文档有 **24 行**含 `§N.M` 型引用,
   而「夏普的定义见 §4.1」会被**今天**的守卫判红。已先把 `§N.M` 从行内剥掉再匹配。
3. **对表格结构性失明**:逐行判"指标名与数值同现"对 markdown 表格**永远看不到** ——
   指标名在**表头行**、数值在**数据行**,二者永不同现。而 §7 点名的恰恰是
   「CAGR/Sharpe/win-rate **tables**」。**注入实测**:往 `chase_up/README.md` 贴一张
   ``| 策略 | Sharpe | 年化 |`` / ``| v3 | 1.42 | 23.5% |`` 的表,**逐行口径全绿**。
   已改为**按表格块判**(块内任一行有指标名、任一行有数值 ⇒ 报红);
   全库 6 个表格块在新口径下报红 **0** ⇒ 不引入假报。

放宽的宽度是**量出来**的,不是拍出来的:候选口径在当前 3 个文档上**四种组合全部 0 行**
(窄/宽词汇 × 小数/百分号)⇒ 放宽面与数值形态**不引入任何假报**。

## 一处**张力**,如实记下而不是悄悄绕过

`docs/audits/strategy-discipline-audit.md`(**审计报告**)**满是数字** —— 那正是本审计的证据。
它与 §7 并不冲突,理由是 §7 自己那句:「Any number that cannot be regenerated from current
code plus one command is treated as stale and deleted.」报告里每个数都附了**复现方式** ⇒
它们是**可再生的证据**,不是「曾经观测到的成绩」。

**故按路径显式排除**(见 `_EXCLUDED_DOCS`),而不是靠「它恰好不在 `docs/*.md` 这一层」这种偶然
—— 后者在 `main` 上已经不成立(报告就在 `docs/audits/` 下)。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: §7 点名的产物类:这些东西**不许被 git 跟踪**。
ARTIFACT_PATTERNS = (
    "chase_up/results/", "uptrend_pullback/results/",
    "short_reversal/results/", "cycle_price_action/results/", "results/",
    "trades.csv", "*_trades.csv",
)

#: `results/` 下的占位文件是允许的(空目录进不了 git)。
_ALLOWED_TRACKED = {"cycle_price_action/results/.gitkeep"}

#: 文档扫描器**要扫的面** = `git ls-files '*.md'` 减去这两个:
#:   * `CLAUDE.md` —— 它是**规范**,不是设计文档;引 §2 时出现的数字是政策常量;
#:   * 审计报告 —— **证据**,每个数都附复现方式(见文件头「张力」那一节)。
_EXCLUDED_DOCS = frozenset({
    "CLAUDE.md",
    "docs/audits/strategy-discipline-audit.md",
})

_METRIC = re.compile(
    r"CAGR|Sharpe|夏普|胜率|回撤|max.?dd|win.?rate|"
    r"年化|收益|超额|信息比|Calmar|alpha|盈亏比",
    re.I,
)
#: 数值 = **带小数点的数** 或 **整数百分号**。
#: 不认裸整数 —— 裸整数会把 `§3` 这类章节号一并吃进去(全库实测量过)。
_VALUE = re.compile(r"-?\d+\.\d+|\d+\s*%")
#: 章节引用(`§4` / `§4.1`)先剥掉:否则 `见 §4.1` 里的 "4.1" 会被当成一个绩效数值。
_SECTION_REF = re.compile(r"§\s*\d+(?:\.\d+)*")
#: markdown 表格行。
_TABLE_ROW = re.compile(r"^\s*\|")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT,
                          capture_output=True, text=True, check=True).stdout


def tracked_artifacts() -> list[str]:
    """被 git 跟踪、且落在 §7 产物模式里的文件(排除占位与已登记的文档例外)。"""
    files = _git("ls-files").splitlines()
    out = []
    for f in files:
        if f in _ALLOWED_TRACKED:
            continue
        if f.endswith(".gitkeep"):
            continue
        if any(f == p.rstrip("/") or f.startswith(p) or Path(f).match(p)
               for p in ARTIFACT_PATTERNS):
            out.append(f)
    return out


def doc_files() -> list[str]:
    """扫描器的**面**:所有被跟踪的 markdown,减去 `_EXCLUDED_DOCS`。

    从 `git ls-files` **派生**,而不是写死一个 glob —— 这样新加的策略 README
    (`xxx/README.md`)与更深的 `docs/*/*.md` **自动**进面。
    (附一百三十三 的病根正是「面写死了」:漏掉的 2 个里有一个还被 docstring 声称查过了。)
    """
    return sorted(f for f in _git("ls-files", "*.md").splitlines()
                  if f not in _EXCLUDED_DOCS)


def _normalized(line: str) -> str:
    """剥掉章节引用后的行 —— 已定的匹配口径。"""
    return _SECTION_REF.sub("", line)


def _block_reports(block: list[str]) -> bool:
    """一个块(单行,或**一整张表格**)= 报红?

    * 单行:该行同时有指标名与数值(与附九十五 同一口径);
    * 表格:**块内**任一行有指标名、**任一行**有数值 —— 因为 §7 点名的就是
      win-rate **tables**,而表里指标名在表头行、数值在数据行。
    """
    lines = [_normalized(line) for line in block]
    return (any(_METRIC.search(line) for line in lines)
            and any(_VALUE.search(line) for line in lines))


def docs_with_metric_values() -> list[str]:
    """README / 设计文档里「指标名 + 数值」的块。表格按**整块**报,行内按**单行**报。"""
    out: list[str] = []
    for rel in doc_files():
        p = REPO_ROOT / rel
        if not p.is_file():
            continue
        lines = p.read_text(encoding="utf-8").splitlines()
        for start, block in _enumerate_blocks(lines):
            if _block_reports(block):
                kind = "表格" if len(block) > 1 else "行"
                out.append(f"{rel}:{start}({kind},{len(block)} 行)  {block[0].strip()[:80]}")
    return out


def _enumerate_blocks(lines: list[str]) -> list[tuple[int, list[str]]]:
    """把连续的表格行聚成**一块**、非表格行各自成一块(单行),并带上**起始行号**。

    块切分是"表格口径"的承重件:表格块必须整块判,否则指标名与数值分居两行就永远碰不到。
    """
    numbered: list[tuple[int, list[str]]] = []
    current: list[str] = []
    start = 1
    for index, line in enumerate(lines, 1):
        if _TABLE_ROW.match(line):
            if not current:
                start = index
            current.append(line)
        else:
            if current:
                numbered.append((start, current))
                current = []
            numbered.append((index, [line]))
    if current:
        numbered.append((start, current))
    return numbered


def test_no_result_artifact_is_tracked_by_git() -> None:
    """§7:结果类产物永不入库 —— 新克隆必须**零历史绩效**。"""
    bad = tracked_artifacts()
    assert not bad, (
        "§7 VIOLATION: 以下结果类产物被 git 跟踪(新克隆会带上历史绩效):\n  "
        + "\n  ".join(bad)
        + "\n把它们从索引里移除并补进 .gitignore。"
    )


def test_the_artifact_patterns_are_actually_ignored() -> None:
    """§7 点名的每一类产物都必须**真的**被 .gitignore 覆盖。

    (只测"当前没有被跟踪"不够 —— 一个**新**产物明天就可能被提交;
     这一条钉的是"规则还在"。)
    """
    probes = {
        "chase_up/results/x.json": "chase_up/results/",
        "results/x.csv": "results/",
        "trades.csv": "trades.csv",
        "chase_up/results/v1_trades.csv": "*_trades.csv",
    }
    not_ignored = []
    for probe, why in probes.items():
        r = subprocess.run(["git", "check-ignore", "-q", probe], cwd=REPO_ROOT)
        if r.returncode != 0:
            not_ignored.append(f"{probe}(应由 {why} 覆盖)")
    assert not not_ignored, (
        "§7: 以下产物**不会被忽略**(明天提交就会被带进库):\n  " + "\n  ".join(not_ignored)
    )


def test_design_docs_embed_no_metric_values() -> None:
    """§7:README / 设计文档只写**怎么复现**,不写**曾经观测到什么**。"""
    bad = docs_with_metric_values()
    assert not bad, (
        "§7 VIOLATION: 以下文档位置把**指标名**与**数值**写在了一起:\n  "
        + "\n  ".join(bad)
        + "\n文档要写明复现命令,数字留给产物(gitignored)。"
    )


def test_the_doc_scanner_surface_equals_the_documented_population() -> None:
    """**面自洽**(取代旧的「至少扫到 2 个文档」)。

    旧断言只要求 `>= 2`,而面被写死成 2 个 ⇒ **面缩窄时它照样绿** —— 附一百三十三 实测的
    正是这个:面只盖 2/4,断言却认为一切正常。这一版钉的是**等式**:总体(被跟踪的 markdown)
    里除排除项外的每一个,都必须在面上。
    """
    all_md = sorted(_git("ls-files", "*.md").splitlines())
    assert len(all_md) >= 3, f"只找到 {len(all_md)} 个 markdown —— 仓库面目全非?"
    surface = doc_files()
    assert surface, "扫描面是空的 —— 下面那条会恒真"
    missing = [f for f in all_md if f not in _EXCLUDED_DOCS and f not in surface]
    assert not missing, f"这些文档在总体里、却不在扫描面上(面又缩窄了):{missing}"
    unexpected = [f for f in surface if f in _EXCLUDED_DOCS]
    assert not unexpected, f"排除项竟然进了面:{unexpected}"


def test_the_line_verdict_has_teeth() -> None:
    """**牙齿**:该报的三种形态必须报;该放过的两种必须放过。

    (与扫描器**共用** `_block_reports`,所以它钉的就是线上那条口径,不是一份副本。)
    """
    assert _block_reports(["本策略 Sharpe 1.42,年化 23.5%,回撤 8.9%。"]), "小数形态漏了"
    assert _block_reports(["胜率 62%,盈亏比 1.8。"]), "整数百分号形态漏了"
    assert _block_reports(["本策略年化收益 23%,超额 8%。"]), "词汇面漏了"
    assert not _block_reports(
        ["本策略的 Sharpe 与 CAGR 由 `python3 -m ...` 一条命令复现,本文不写数值。"]
    ), "没有数值却报红"
    assert not _block_reports(
        ["夏普的定义与窗口口径见 §4.1,这里只说明怎么复现。"]
    ), "章节号 §4.1 被当成了数值"


def test_the_table_verdict_has_teeth() -> None:
    """**表格**:指标名在表头、数值在数据行 —— 逐行口径对这种形态**结构性失明**。

    (这不是推出来的:往 `chase_up/README.md` 注入一张 Sharpe 表,逐行口径**全绿**。)
    """
    sharpe_table = [
        "| 策略 | Sharpe | 年化 |",
        "| --- | --- | --- |",
        "| v3 | 1.42 | 23.5% |",
    ]
    assert _block_reports(sharpe_table), "一张 Sharpe 表被放过了 —— 表格口径失效"

    parameters_table = [
        "| 策略 | Sharpe 窗口 | 说明 |",
        "| --- | --- | --- |",
        "| v3 | 252 | 见 §2 |",
    ]
    assert not _block_reports(parameters_table), "表头只有指标名、数值全是参数,却被判红"

    # 块切分是承重件:空行/正文混排时,表格行必须聚成**一块**。
    numbered = _enumerate_blocks(["前文", "", *sharpe_table, "", "后文"])
    tables = [b for _, b in numbered if len(b) > 1]
    assert len(tables) == 1, f"表格没被聚成一块:{numbered}"
    assert len(tables[0]) == 3, f"表格块行数不对:{tables[0]}"
    assert [start for start, b in numbered if len(b) > 1] == [3], (
        f"表格块的起始行号应是表头那一行(3),实得 "
        f"{[start for start, b in numbered if len(b) > 1]}"
    )
