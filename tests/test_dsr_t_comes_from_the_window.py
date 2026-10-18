"""附八十一 —— DSR 的 T / CAGR 的年化分母必须是**窗口内**的期数,不能是整张面板的长度。

## 缺陷(实测)

各引擎的 `load_panel()` 都把起点往前推一个暖机缓冲(`WARMUP_DAYS = 400`,
chase / uptrend / short_reversal 同构)⇒ `panel` 是 `[start − 400 天, end]`,**不是窗口**。
因此 `int(panel["date"].nunique())` 量的是**面板**长度。实测:

| | 窗口 2025-09-16..2026-09-16 | 面板(含 400 天暖机) |
|---|---|---|
| 交易日 | **243** | **510** |
| ⇒ T 高估 | | **2.10 倍** |

全库共 **8 处**同形状(`HEAD` 版本实测,普查工具逐处命中):

    chase_up/sweep.py:142                      n_returns    = panel['date'].nunique() (- 1)
    uptrend_pullback/sweep_v33_long.py:182     n_returns    = panel['date'].nunique()
    uptrend_pullback/sweep_v33_long_v2.py:214  n_returns    = panel['date'].nunique()
    uptrend_pullback/sweep_v33_long_v3.py:177  n_returns    = panel['date'].nunique()
    uptrend_pullback/sweep_v33_long_v4.py:177  n_returns    = panel['date'].nunique()
    uptrend_pullback/sweep_v33_long_v5.py:226  n_returns    = panel['date'].nunique()
    uptrend_pullback/sweep_v33_long_v6.py:207  n_returns    = panel['date'].nunique()
    short_reversal/engine.py:493               n_trading_days = panel['date'].nunique()

## 这一处为什么格外扎眼

`chase_up/sweep.py` 那句注释**自己量对了**:「实测窗口 2025-09 起的同类 sweep 只有
242~243 个交易日 ⇒ 高估 T 约 4%」—— 而**下一行**传的是 `panel.nunique() - 1` = 509。
注释里的正确数字和代码里的错误数字躺在同一个 hunk 里。这与 附六十 是同一种错法:
**为了"把猜的常数换成实测值"而写的一次修复,实测的是另一个量,于是把指标推得更乐观。**

## 为什么是门禁而不是只修 8 处

8 处是"手工 grep 一次"的结果,不是"这一类不会再出现"的保证。判据放进
`tests/_census_panel_length_as_window.py`,凡是把 `n_returns` / `n_trading_days`
当关键字传出去的地方,表达式子树里**不许**出现 `.nunique()` 或 `len(表名)`。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _census():
    spec = importlib.util.spec_from_file_location(
        "census_panel_length_as_window",
        REPO_ROOT / "tests" / "_census_panel_length_as_window.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_no_period_count_is_derived_from_the_whole_panel() -> None:
    """生产模块里,凡是传 `n_returns=` / `n_trading_days=` 的地方都不得数整张面板。"""
    mod = _census()
    hits: list[str] = []
    for path in sorted(REPO_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts or "tests" in path.relative_to(REPO_ROOT).parts:
            continue
        for ln, arg, expr in mod.find_panel_length_as_period(path):
            hits.append(f"{path.relative_to(REPO_ROOT)}:{ln} {arg} = {expr}")
    assert not hits, (
        "§5: 以下位置把**整张面板**的长度当成了**窗口内**的期数(含 400 天暖机,"
        "实测 T 高估 2.10 倍)。用 `core.walkforward.window_trading_days(panel, start, end)`:\n  "
        + "\n  ".join(hits)
    )


def test_the_gate_has_teeth(tmp_path: Path) -> None:
    """**牙齿**:种真形状必须被认出来;种合法形状不得误报。

    (没有这条,"0 命中"无法区分"代码干净"与"检查器坏了"。)
    """
    mod = _census()
    good = tmp_path / "good.py"
    good.write_text(
        "from core.walkforward import window_trading_days\n"
        "def f(panel, start, end, s):\n"
        "    a = deflated_sharpe_ratio(sr, 12, n_returns=window_trading_days(panel, start, end))\n"
        "    b = deflated_sharpe_ratio(sr, 12, n_returns=len(s))\n"          # 窗口内的收益序列 —— 合法
        "    c = attribute(rs, bs, n_periods=len(rs))\n"
        "    return a, b, c\n",
        encoding="utf-8",
    )
    assert mod.find_panel_length_as_period(good) == [], "合法形状被误报"

    for i, banned in enumerate([
        'n_returns=int(panel["date"].nunique())',
        'n_returns=int(panel["date"].nunique()) - 1',
        'n_trading_days=int(panel["date"].nunique())',
        'n_returns=len(panel)',
        'n_periods=len(df.dropna())',           # 表名启发式之外:这条**不该**被认出来,见下
    ]):
        bad = tmp_path / f"bad{i}.py"
        bad.write_text(f"def f(panel, df):\n    return deflated_sharpe_ratio(1.0, 2, {banned})\n",
                       encoding="utf-8")
        hits = mod.find_panel_length_as_period(bad)
        if i < 4:
            assert hits, f"没认出来:{banned}"
        else:
            # `len(df.dropna())` 是**已知漏报**(判据只看 `len(裸名字)`),如实钉在这里,
            # 免得以后有人把"没报"误读成"已覆盖"。
            assert not hits, f"判据变了(这条本应漏报),请更新本用例与工具 docstring:{hits}"
