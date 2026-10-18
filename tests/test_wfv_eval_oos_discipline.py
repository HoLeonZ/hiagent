"""附七十四 —— `wfv_eval.py` 的 OOS 纪律:把"注释里的约定"变成**产物里的必需声明**

## 事实

`uptrend_pullback/wfv_eval.py` 的 docstring 首行原写「**§5 合规**的 preset 评估器 —
**WFV** + DSR」。而它的窗口来自 `core.walkforward.monthly_windows` —— 滚动、**无 train/test
划分**,默认 2 月窗 / 1 月步 ⇒ 相邻窗**重叠 50%**。§5 逐字要求的是:

> **Walk-Forward Validation:** Optimization logic must enforce WFV with strict
> **out-of-sample (OOS)** testing windows.

`wfv_eval` **没有任何** train/test 参数(实测:`grep train|test|split` 只命中两处注释),
OOS 完全靠注释里的**人工约定**("迭代期 用 train 段; 最终结论 用 holdout 段")。
后果:**搜索日志里分不出哪一行是结论期的** —— 而 §5 要的正是"结论必须来自 OOS"。

更糟的是它被**三处**当成"已存在的机制"引用(附七十四 记录):`iter_reverse.py` 的注释与
打印、以及一条测试的 docstring 都写着「见 `wfv_eval.py` 的 **train/test 划分**」——
**那个划分不存在**。(与附四十六/五十四 的"引用不存在的东西"同族。)

## 处置(与 `--n-trials` 同法:让调用方**必须**声明)

* `--window-role {iteration,holdout}` 设为**必需**参数,并写进 JSON 产物;
* 打印里说清"窗口是滚动**无划分**的 ⇒ 本次是**样本内**评估",以及该角色的含义;
* 解析器抽成 `build_parser()`,好让"哪些参数必需"能被**行为性**验证;
* 三处假引用改成实话(并说明本仓库**没有**代码强制的划分);
* 文档里的示例命令补上 `--window-role`(否则照抄会直接报错)。

**"要不要把划分做进代码"是待你定的口径问题**(登记)——它会让既往的搜索日志行失去可比性,
故不擅自改默认。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "uptrend_pullback" / "wfv_eval.py"
DOC_PATH = REPO_ROOT / "docs" / "uptrend_pullback_preset_search.md"


def _tool():
    import sys

    sys.path.insert(0, str(REPO_ROOT))
    from uptrend_pullback.wfv_eval import build_parser

    return build_parser


# ---------------------------------------------------------------------------
# 行为:"缺少声明"必须跑不起来
# ---------------------------------------------------------------------------


def test_window_role_is_required() -> None:
    """**缺 `--window-role` ⇒ 报错**,不许默默跑一个"不知角色"的评估。"""
    p = _tool()()
    with pytest.raises(SystemExit):
        p.parse_args(["--preset", "v33_long_reverse_v19", "--n-trials", "1"])
    # 反向:带上就通过
    a = p.parse_args(["--preset", "v33_long_reverse_v19", "--n-trials", "1",
                      "--window-role", "holdout"])
    assert a.window_role == "holdout"


def test_window_role_choices_are_constrained() -> None:
    """角色只能取两个值之一(自由文本会让"日志里能不能区分"这件事失效)。"""
    p = _tool()()
    with pytest.raises(SystemExit):
        p.parse_args(["--preset", "x", "--n-trials", "1", "--window-role", "maybe"])


def test_n_trials_is_still_required() -> None:
    """§5 迭代计数那一半的必需性不得被这次改动碰掉。"""
    p = _tool()()
    with pytest.raises(SystemExit):
        p.parse_args(["--preset", "x", "--window-role", "iteration"])


# ---------------------------------------------------------------------------
# 结构:角色进产物;打印里说清"无划分"
# ---------------------------------------------------------------------------


def test_record_carries_the_window_role() -> None:
    """JSON 记录必须带 `window_role` —— 搜索日志靠它区分迭代期与结论期。"""
    tree = ast.parse(TOOL_PATH.read_text(encoding="utf-8"))
    main = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    keys = {
        k.value
        for node in ast.walk(main) if isinstance(node, ast.Dict)
        for k in node.keys if isinstance(k, ast.Constant)
    }
    assert "window_role" in keys, "记录里没有 window_role"
    assert "n_trials" in keys, "记录里丢了 n_trials"


def test_print_says_the_windows_are_not_split() -> None:
    """打印必须**说清**这次评估是样本内的(滚动、无划分),否则读者会当成 OOS。"""
    src = TOOL_PATH.read_text(encoding="utf-8")
    assert "无划分" in src and "样本内" in src, (
        "打印里没有说明窗口是滚动无划分/样本内"
    )
    assert "window_role" in src


# ---------------------------------------------------------------------------
# 文档:照抄命令必须能跑
# ---------------------------------------------------------------------------


def test_doc_commands_include_the_required_flag() -> None:
    """文档里的 `wfv_eval` 示例命令必须带 `--window-role`(否则照抄报错)。

    (附七十四:参数变成必需之后,文档里那两条命令会直接失败 —— 这属"文档给出不可执行
    的指引",与本仓库早前修过的 `--save-trades` 死引用同类。)
    """
    text = DOC_PATH.read_text(encoding="utf-8")
    cmds = re.findall(r"python3 -m uptrend_pullback\.wfv_eval.*?(?=\n\n|\n#|\Z)",
                      text, re.S)
    assert cmds, "文档里没找到 wfv_eval 示例命令"
    for c in cmds:
        assert "--window-role" in c, f"示例命令缺 --window-role:\n{c}"


def test_doc_says_the_windows_are_in_sample() -> None:
    """文档必须写明滚动窗是**样本内**,不能只给命令不说口径。"""
    text = DOC_PATH.read_text(encoding="utf-8")
    assert "样本内" in text or "滚动无划分" in text
