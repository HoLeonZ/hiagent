"""§4 做空可行性: **逐 bar** 的 ST/风险警示 (不可融券) 检查。

为什么必须逐 bar: A 股 ST/风险警示股涨跌停 ±5% 且不在融资融券名单 ⇒ 不可做空。
**静态宇宙过滤只剔掉约 2% 的成交** —— 因为该状态在窗口内随时间变化 (一只票可能在
窗口中途才被实施风险警示)。逐 bar 判定的命中率是 **7.1%** (v50_slope, W2 实测:
140 笔中剔掉 10 笔)。

判据: 信号日之前 `st_lookback_bars` 根 bar 内出现过"封死 ±5%" ——
`|单日涨跌幅| ≈ 5%` 且 `high == low` (全天一个价)。非风险警示的主板股几乎不可能
出现 `high == low`, 故信噪比很高。PIT: 只回看已发生的 bar。

**性能影响 (据实记录, 不夸大)**: 该过滤**不是绩效杠杆** —— W2 上 CAGR +30.5% → +47.2%、
Calmar 0.8 → 1.4, 但 IND 上 CAGR -25.7% → -36.8% (更差)、HOLD 基本不变。
它的价值在于**让回测只算下得出去的成交**, 而不是让策略更好。
"""
from __future__ import annotations

import ast
from pathlib import Path

from short_reversal.replay_strategy_v3 import Phase3V3Strategy as S

SRC = (Path(__file__).parent.parent / "short_reversal" / "replay_strategy_v3.py").read_text(
    encoding="utf-8"
)


def test_filter_is_opt_in_and_off_by_default() -> None:
    assert S.params.require_shortable_st_filter is False
    assert S.params.st_lookback_bars == 60


def _st_node() -> ast.FunctionDef:
    """取出引擎里 `_suspected_st_now` 的**函数节点**(按 AST,不按文本切片)。

    ⚠️ 2026-10-22 (附一百八十七): 本文件此前用文本切片取函数体:

        body = SRC[SRC.index("def _suspected_st_now") : SRC.index("def _conviction", i)]

    而那个结束标记**已失效** —— 方法现在叫 `_conviction_key`(且位置在 `_suspected_st_now`
    **之前**)⇒ `SRC.index` 抛 **ValueError**, 两条用例**在断言之前就炸**, 而它们**要断言的性质
    当时全都成立**(实测: `for i in range(1, upper + 1)` / 无当日下标 / `d.close[-i - 1]` /
    `hi == lo` / `0.05` 逐条都在)。

    ⇒ **把"文本切片 + 子串 in"换成 AST**: 取节点, 再断言**性质**(下标符号 / 常数 / 比较),
    改名与重排都不会再让它假红。
    """
    for node in ast.walk(ast.parse(SRC)):
        if isinstance(node, ast.FunctionDef) and node.name == "_suspected_st_now":
            return node
    raise AssertionError("引擎里找不到 `_suspected_st_now` —— 它被改名或删除了")


def test_check_only_looks_backwards() -> None:
    """PIT 结构断言: 检查函数只使用负偏移 (-1 及更早), 不得读当日高开低收。"""
    node = _st_node()
    loops = [c for c in ast.walk(node)
             if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
             and c.func.id == "range"]
    assert loops, "找不到回看循环 —— 判据会变成空转"
    starts = {c.args[0].value for c in loops
              if c.args and isinstance(c.args[0], ast.Constant)}
    assert 1 in starts and 0 not in starts, (
        f"回看必须从 -1 开始(不含当日): range 起点实测 {sorted(starts)}"
    )
    # 所有 `d.<attr>[idx]` 的下标必须是负偏移(或含负号)
    def _negative(sl: ast.AST) -> bool:
        if isinstance(sl, ast.UnaryOp) and isinstance(sl.op, ast.USub):
            return True
        if isinstance(sl, ast.BinOp):
            return _negative(sl.left) or _negative(sl.right)
        return False

    offenders = []
    for sub in ast.walk(node):
        if (isinstance(sub, ast.Subscript)
                and isinstance(sub.value, ast.Attribute)
                and isinstance(sub.value.value, ast.Name)
                and sub.value.value.id == "d"
                and not _negative(sub.slice)):
            offenders.append(ast.unparse(sub))
    assert not offenders, f"PIT 违规: 读到当日(非负下标) {offenders}"


def test_sealed_band_matches_five_percent() -> None:
    """判据必须锚在 ±5% 停板, 且要求 high == low (封死)。"""
    node = _st_node()
    assert any(isinstance(c, ast.Compare)
               and any(isinstance(op, ast.Eq) for op in c.ops)
               for c in ast.walk(node)), "判据必须比较 high 与 low(封死停板)"
    floats = {round(c.value, 6) for c in ast.walk(node)
              if isinstance(c, ast.Constant) and isinstance(c.value, float)}
    assert 0.05 in floats, f"停板幅度必须锚在 5%, 实测浮点常数 {sorted(floats)}"


def test_engine_plumbs_both_keys() -> None:
    eng = (Path(__file__).parent.parent / "short_reversal" / "engine.py").read_text(
        encoding="utf-8"
    )
    assert 'require_shortable_st_filter=cfg.get("require_shortable_st_filter", False)' in eng
    assert 'st_lookback_bars=cfg.get("st_lookback_bars", 60)' in eng
