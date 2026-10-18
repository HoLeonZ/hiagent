"""附八十二 —— `n_trials` 必须数"**试过多少**",不是"**跑出了多少个结果**"。

## 契约

`dna_stats/deflated.py::deflated_sharpe_ratio` 的 docstring:`n_trials` = "Number of
independent strategy configurations **tested**"。CLAUDE.md §5 Iterative-Tuning
Accounting 的原话是「**每一次**迭代都计入」——**崩掉的那次、没信号的那次,也是一次迭代**。

## 缺陷(全库 10 处,三种形状)

| 形状 | 位置 | 被漏掉的"试过" |
|---|---|---|
| `if entries.empty: continue`(**不落行**) | 6 个 `uptrend_pullback/sweep_v33_long*.py` 的 `sweep()` | **没产出信号的配置** |
| 失败行落进 `df` 但被 `dropna()` 剔 | `chase_up/sweep.py` | **抛异常的配置** |
| 失败 preset 进 `failed` 而**没进 `rows`** | `chase_up/sweep_all.py` | **抛异常的 preset** |
| `mean_sharpe` 全 NaN 被 `dropna()` 剔 | `chase_up/wf_sweep_all.py` | 所有窗口都失败的 preset |
| 显式 `r.get("error") is None` 过滤 | `short_reversal/grid_runner.py` | **抛异常的配置** |

方向一致 —— **少计 ⇒ E[max] 偏小 ⇒ DSR 偏乐观**(而 §5 的惩罚指标恰恰要用在"看起来不错"的结果上)。

**`observed = max(...)` 取成功者的最大是**对**的**:选择只在有数的配置间发生。
错的是把**同一批被筛过的集合**又拿去当 `n_trials`。

## 为什么要机械判据

这 10 处分散在 3 个引擎、9 个文件里,而**每一处单看都很自然**("我拿有效的那些算"听起来
毫无问题)。判据放进 `tests/_census_n_trials_drops_failures.py`:凡是 `n_trials=` 的表达式,
不得含 `.dropna()` / `.isna()` / 与 `"error"` 的比较 / `.get("error")`,也不得是
`len(NAME)` 而 NAME 在同一函数内被赋成上述形状(**浅数据流** —— 上一批的教训:
只看调用点表达式会漏掉"先算好再传"的形状)。

**如实声明的漏报**:跨函数的赋值链;用别的名字表达同一件事(如 `ok = [r for r in rows
if r["ok"]]`);以及 `chase_up/sweep_all.py` 那种"失败项根本不在这个集合里"的语义型漏计
(静态判据看不见,只能靠读)。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _census():
    spec = importlib.util.spec_from_file_location(
        "census_n_trials_drops_failures",
        REPO_ROOT / "tests" / "_census_n_trials_drops_failures.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_no_n_trials_is_computed_over_a_filtered_set() -> None:
    """生产模块里,凡是传 `n_trials=` 的地方都不得先把跑失败的配置筛掉。"""
    mod = _census()
    hits: list[str] = []
    for path in sorted(REPO_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts or "tests" in path.relative_to(REPO_ROOT).parts:
            continue
        for ln, expr in mod.find_n_trials_that_drop_failures(path):
            hits.append(f"{path.relative_to(REPO_ROOT)}:{ln} n_trials ← {expr}")
    assert not hits, (
        "§5: 以下位置的 `n_trials` 先把跑失败的配置筛掉了 —— 少计 ⇒ DSR 偏乐观。"
        "`n_trials` 要数**试过多少**(网格枚举数 / 全部落盘行数):\n  " + "\n  ".join(hits)
    )


def test_the_gate_has_teeth(tmp_path: Path) -> None:
    """**牙齿**:三种真形状必须被认出来;合法形状不得误报。"""
    mod = _census()

    good = tmp_path / "good.py"
    good.write_text(
        "import itertools\n"
        "def f(df, sharpes, grid, grids):\n"
        "    a = deflated_sharpe_ratio(1.0, n_trials=len(list(itertools.product(*grid.values()))))\n"
        "    b = deflated_sharpe_ratio(1.0, n_trials=len(df))\n"
        "    c = deflated_sharpe_ratio(1.0, n_trials=sum(len(g) for g in grids))\n"
        "    return a, b, c\n",
        encoding="utf-8",
    )
    assert mod.find_n_trials_that_drop_failures(good) == [], "合法形状被误报"

    bad1 = tmp_path / "bad1.py"          # 直接 dropna
    bad1.write_text(
        "def f(df):\n    return deflated_sharpe_ratio(1.0, n_trials=len(df['sharpe'].dropna()))\n",
        encoding="utf-8",
    )
    bad2 = tmp_path / "bad2.py"          # 浅数据流:先算好再传
    bad2.write_text(
        "def f(df):\n    sharpes = df['sharpe'].dropna()\n"
        "    return deflated_sharpe_ratio(1.0, n_trials=len(sharpes))\n",
        encoding="utf-8",
    )
    bad3 = tmp_path / "bad3.py"          # 显式剔除 error 行
    bad3.write_text(
        "def f(rows):\n    s = [float(r['Sharpe']) for r in rows if r.get('error') is None]\n"
        "    return deflated_sharpe_ratio(1.0, n_trials=len(s))\n",
        encoding="utf-8",
    )
    for p in (bad1, bad2, bad3):
        assert mod.find_n_trials_that_drop_failures(p), f"没认出来:{p.name}"
