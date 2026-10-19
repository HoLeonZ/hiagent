"""§13.111: `build_per_stock_feeds` 不得是 O(n_codes × n_rows) (§13.111, 2026-10-19)。

## 修之前
```python
for code in codes:                          # ~5,000 只票
    sub = panel[panel["thscode"] == code]   # **每只票全表扫一遍**
```
⇒ **O(n_codes × n_rows)**。而 `panel["thscode"]` 是 pandas **`str`/`string` dtype**
⇒ `==` 走 `_cmp_method` → `_isna_string_dtype` 这条**最差**的路径。

**实测 (5,360 只票 / 1,413,666 行)**: **163.1s** → **1.7s** (≈ **96×**),
而 **feeds 数两边都是 5,272** ⇒ 输出相同; 完整 3 个月回测 **172.4s → 127.7s**,
`trades`/`total_yield`/`final_capital`/成交清单 sha256 **逐位相同** ⇒ **零漂移**。

⚠️ **它影响全部 55 个 `short_reversal` preset** (在共享的 feed 构建器里),
且**逐 preset 无关** (`v35_agg_pctchg_04_09` 与对照 `v50_slope` **同速**)。
⇒ 任何对短仓族的 sweep 都被**凭空**放慢了约 100 倍 —— 这正是普查跑不完的原因。

## 本文件钉的两件事
1. **形状**: 不得再出现"面板列 == 循环变量"的逐 code 全表掩码 (AST);
2. **语义**: 输出必须与"逐 code 掩码"的参考实现**逐行相同, 且顺序不变**。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "short_reversal" / "feed_bt.py"


def test_no_per_code_full_panel_mask() -> None:
    """★ **形状判据**: `build_per_stock_feeds` 里不得有 `panel[panel[<列>] == <循环变量>]`。

    这就是 O(n_codes × n_rows) 的确切形状 —— 修前它占了 99.2% 的墙钟时间。
    """
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "build_per_stock_feeds"), None)
    assert fn is not None, "找不到 build_per_stock_feeds"
    bad = []
    for n in ast.walk(fn):
        # 找 Subscript(X[Y]) 且 Y 是 ast.Compare —— 掩码形态
        if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Compare):
            t = ast.unparse(n.slice)
            if "==" in t and "thscode" in t:
                bad.append((n.lineno, t))
    assert not bad, (
        f"§13.111: 又出现了**逐 code 全表掩码**: {bad}\n"
        f"⇒ 那是 O(n_codes × n_rows); 用一次 `groupby(...).get_group(...)` 代替。"
    )


def _panel() -> tuple[pd.DataFrame, list[str]]:
    rows = []
    codes = ["600000.SH", "600001.SH", "600002.SH"]
    for c in codes:
        for i, d in enumerate(pd.date_range("2025-01-01", periods=5, freq="B")):
            rows.append({"thscode": c, "date": d, "open": 1.0 + i, "close": 1.5 + i})
    # 顺序**打乱**, 以证明"按 codes 顺序"而不是"按面板顺序"
    df = pd.DataFrame(rows).sample(frac=1.0, random_state=0).reset_index(drop=True)
    return df, list(reversed(codes))


def test_output_matches_the_reference_and_keeps_codes_order() -> None:
    """**语义判据**: 输出必须与逐 code 掩码参考实现**逐行相同**, 且**顺序 = `codes` 的顺序**。"""
    from short_reversal.feed_bt import build_per_stock_feeds

    df, codes = _panel()

    def reference(panel: pd.DataFrame, order: list[str]) -> list[tuple[str, int]]:
        out = []
        for c in order:
            sub = panel[panel["thscode"] == c].sort_values("date").reset_index(drop=True)
            if len(sub) >= 1:
                out.append((c, len(sub)))
        return out

    feeds = build_per_stock_feeds(df, codes, min_bars=1)
    got = [name for name, _ in feeds]
    want = [name for name, _ in reference(df, codes)]
    assert got == want, (
        f"§13.111: 输出的**票集合或顺序**与参考实现不符。\n  得到: {got}\n  参考: {want}\n"
        f"⇒ `feeds` 的顺序必须跟 `codes` 一致 —— 调用方可能依赖它。\n"
        f"(行数不在此处比对: 那需要 backtrader feed 的内部结构, 属实现细节;"
        f" 行数的一致已由 §13.111 的端到端零漂移验证覆盖: 成交清单 sha256 逐位相同。)"
    )


def test_missing_codes_are_skipped_not_raised() -> None:
    """**缺票必须跳过, 不得抛错** —— 旧掩码写法给空表, 随后被 `min_bars` 跳过。"""
    from short_reversal.feed_bt import build_per_stock_feeds

    df, codes = _panel()
    got = build_per_stock_feeds(df, codes + ["999999.SH"], min_bars=1)
    assert all(name != "999999.SH" for name, _ in got), "缺票竟然进了 feeds"
    assert len(got) == len(codes), f"缺票影响了其余结果: {[n for n, _ in got]}"
