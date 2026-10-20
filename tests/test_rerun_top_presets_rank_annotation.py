"""附七十二 —— `rerun_top_presets.py` 的 TOP-5:跨引擎 Sharpe 不可比 + 旧快照混排

## 缺陷(实测)

1. **四个行构造器都不带 `sharpe_kind`**(同族的 `run_all_backtests_html.py` 带 —— 它甚至在
   报告里写着"Sharpe 在三个引擎里不是同一个量")。于是这个工具的榜上没有任何量纲信息。
2. 它把**四个引擎**的 preset 一起按 Sharpe 排出 **TOP-5** 并写进报告 JSON(`"top5"`)。
   而其中 short_reversal / cycle 的行是 **`2026-10-08` 旧快照**("Reused 10-08 snapshot"),
   打印时只有**小节标题**写了 reused,榜上**逐行不标** —— 读者分不清哪几行与今天重跑的行同源。
   这段快照早于其后的引擎修复(例如 §4 跳空止损成交价的修复把 short_reversal 的结果动了 ~40%),
   故"新鲜行 vs 快照行"并列比较本身就不成立。
3. §5 语境:这是一份**按 max Sharpe 选出来的 top-5**,还会落进产物。

## 处置

* 行里带上 `sharpe_kind` 与 `data_vintage`;
* 排名与打印抽成纯函数 `rank_presets()` / `format_top5()`,后者**必须**印出两条可比性警示
  (跨引擎 Sharpe 不可比;`[旧快照]` 行与新鲜行不同源)与逐行的量纲/版本标注;
* 未知 kind / vintage **原样显示**而不是留空(留空分不开"没有信息"与"信息为空")。
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tools" / "rerun_top_presets.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("rerun_top_presets", TOOL_PATH)
    assert spec and spec.loader, f"无法加载 {TOOL_PATH}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(preset, sharpe, cagr=0.1, dd=-0.05, kind="daily_returns_annualized",
         vintage="fresh", trades=10):
    return {"preset": preset, "sharpe": sharpe, "cagr": cagr, "max_dd": dd,
            "sharpe_kind": kind, "data_vintage": vintage, "trades": trades}


# ---------------------------------------------------------------------------
# 行为:排序与标注
# ---------------------------------------------------------------------------


def test_rank_orders_by_sharpe_then_cagr_then_dd() -> None:
    mod = _load_tool()
    rows = [
        _row("a", 1.0, 0.10, -0.05),
        _row("b", 2.0, 0.05, -0.09),
        _row("c", 2.0, 0.20, -0.30),
        _row("d", 2.0, 0.20, -0.10),
    ]
    got = [r["preset"] for r in mod.rank_presets(rows)]
    assert got == ["d", "c", "b", "a"]


def test_rank_handles_none_without_crashing() -> None:
    """cycle 的 sharpe/cagr/max_dd 是 None;排序必须仍然确定。"""
    mod = _load_tool()
    rows = [_row("ok", 1.0), _row("cyc", None, cagr=None, dd=None)]
    got = mod.rank_presets(rows)
    assert got[0]["preset"] == "ok" and len(got) == 2


def test_top5_prints_the_two_comparability_caveats() -> None:
    """榜必须自带两条警示:跨引擎 Sharpe 不可比;旧快照行与新鲜行不同源。"""
    mod = _load_tool()
    lines = mod.format_top5([_row("x", 1.0)], [], [], [], [])
    text = "\n".join(lines)
    assert "不是同一个量" in text, "缺少『跨引擎 Sharpe 不可比』的警示"
    assert "旧快照" in text, "缺少『旧快照 vs 今日重跑』的说明"


def test_top5_marks_kind_and_vintage_per_line() -> None:
    """逐行必须有量纲与数据版本,否则榜会被误读。"""
    mod = _load_tool()
    lines = mod.format_top5([
        _row("p1", 2.0, kind="daily_returns_annualized", vintage="fresh"),
        _row("p2", 1.5, kind="per_trade_ratio_approx",
             vintage=mod.OLD_SNAPSHOT_TAG),
    ], [], [], [], [])
    body = [l for l in lines if l.startswith("  #")]
    assert len(body) == 2
    assert "[日年化]" in body[0] and "[今日重跑]" in body[0]
    assert "[逐笔近似]" in body[1] and "[旧快照]" in body[1]


def test_unknown_kind_and_vintage_are_shown_not_blanked() -> None:
    mod = _load_tool()
    lines = mod.format_top5([
        _row("p", 1.0, kind="brand_new_kind", vintage="2027-01-01-snapshot"),
    ], [], [], [], [])
    body = [l for l in lines if l.startswith("  #")][0]
    assert "brand_new_kind" in body, "未知量纲被吞掉了"
    assert "旧快照" in body, "非 fresh 的版本应标成旧快照(而不是留空)"


# ---------------------------------------------------------------------------
# 结构:行构造器必须带量纲与版本;main 必须走 format_top5
# ---------------------------------------------------------------------------


def _row_literals(tree: ast.Module) -> list[set[str]]:
    """返回所有"像行"的 dict 字面量的键集合(含 preset 键的那些)。"""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
            if "preset" in keys:
                out.append(keys)
    return out


def test_every_row_literal_carries_kind_and_vintage() -> None:
    """四个构造器(含快照加载器)的行都必须带 `sharpe_kind` + `data_vintage`。

    (结构性判据 —— 这些函数会真跑回测,单测里跑不起;行为证据在 `format_top5` 那几条上。)
    """
    tree = ast.parse(TOOL_PATH.read_text(encoding="utf-8"))
    rows = _row_literals(tree)
    assert len(rows) >= 4, f"只找到 {len(rows)} 个行字面量,选择器可能失效"
    for keys in rows:
        assert {"sharpe_kind", "data_vintage"} <= keys, (
            f"有行缺少量纲/版本:{sorted(keys)}"
        )


def test_main_prints_via_format_top5() -> None:
    """`main()` 必须用 `format_top5` —— 否则警示会被漏掉(它此前是内联 print)。"""
    tree = ast.parse(TOOL_PATH.read_text(encoding="utf-8"))
    main = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    calls = {n.func.id for n in ast.walk(main)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "format_top5" in calls, "main() 未使用 format_top5"
