r"""§5 Penalty Metrics 守卫:**多参数网格/sweep 脚本必须报惩罚指标**。

## 缺陷(附一百零九)

§5 原文:「*Evaluation scripts must output Deflated Sharpe Ratio (DSR) or apply Bonferroni
corrections when reporting backtest results from multi-parameter sweeps.*」

`uptrend_pullback/grid.py` 跑 4/12/18 档网格、按「各年中位收益」排一张榜,**却一项都不报**;
而它的孪生兄弟 `short_reversal/grid_runner.py` 早已补上 DSR ⇒ **族内不对称,第三次**
(前两次:附一百零六/一百零七 的两个 phantom 工具、附一百零九 的分派规则)。

而应有的一条守卫**被注释满足了**:`tests/test_wfv_rigor_gap.py` 里那条
`test_sweep_dsr_test_coverage_catches_grid_runner` 断言的是
`re.search(r"\*\*?/grid\*?\.py", src)` —— 而那个字符串在
`tests/test_sweep_scripts_dsr.py` 里**只出现在一行注释**中(原话是
「额外 glob `**/grid*.py` 由 … 单独 verify(避免与 `uptrend_pullback/grid.py` 共触发新 RED)」)。
⇒ **判据认的是"提到",不是"做到"**,而那个"单独 verify"只钉了**一个**文件名。

## 本文件的两条判据

1. **类必须被枚举出来并逐一对账**(精确集合):引擎包内的 `grid*.py` / `sweep*.py` /
   `wf_sweep*.py` —— 改名或新增都要人看一眼再改表。
2. **每一个都必须报** DSR 或 Bonferroni。

两向验证:从任一脚本摘掉 DSR ⇒ 红;新种一个无 DSR 的 `grid_foo.py` ⇒ 红。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE_PACKAGES = ("chase_up", "uptrend_pullback", "short_reversal", "cycle_price_action")
PATTERNS = ("grid*.py", "sweep*.py", "wf_sweep*.py")

#: 精确集合(相对路径)。改名 / 新增 / 删除都要在这里同步 —— 这是**故意的**。
GRID_SWEEP_SCRIPTS = {
    "chase_up/sweep.py",
    "chase_up/sweep_all.py",
    "chase_up/wf_sweep_all.py",
    "cycle_price_action/sweep_thresholds.py",
    "short_reversal/grid_runner.py",
    "uptrend_pullback/grid.py",
    "uptrend_pullback/sweep_v33_long.py",
    "uptrend_pullback/sweep_v33_long_v2.py",
    "uptrend_pullback/sweep_v33_long_v3.py",
    "uptrend_pullback/sweep_v33_long_v4.py",
    "uptrend_pullback/sweep_v33_long_v5.py",
    "uptrend_pullback/sweep_v33_long_v6.py",
}


def grid_sweep_scripts() -> set[str]:
    """引擎包内所有**多参数网格 / sweep** 脚本(相对路径)。"""
    out: set[str] = set()
    for pkg in ENGINE_PACKAGES:
        base = REPO_ROOT / pkg
        if not base.is_dir():
            continue
        for pattern in PATTERNS:
            for p in base.glob(pattern):
                out.add(str(p.relative_to(REPO_ROOT)))
    return out


def test_the_class_is_the_enumerated_set() -> None:
    """判据 1:类集合必须与登记的精确集合相等(改名/新增都不能悄悄溜过去)。"""
    actual = grid_sweep_scripts()
    assert actual == GRID_SWEEP_SCRIPTS, (
        "§5 网格/sweep 脚本集合变了 —— 这会影响下面那条判据的覆盖面:\n"
        f"  实际多出: {sorted(actual - GRID_SWEEP_SCRIPTS)}\n"
        f"  实际缺少: {sorted(GRID_SWEEP_SCRIPTS - actual)}\n"
        "确认后同步 `GRID_SWEEP_SCRIPTS`。"
    )
    # 非空转 + 本批那个缺口必须在类里
    assert len(actual) >= 10, f"类异常小({len(actual)} 个)—— 本条可能已空转"
    assert "uptrend_pullback/grid.py" in actual, (
        "本批修的那个脚本不在类里 —— 说明类被划窄了"
    )


def _calls_penalty_metric(src: str) -> bool:
    """源码里是否**调用**了 DSR 或 Bonferroni(只看可执行调用,不看注释/docstring)。

    ⚠️ 第一版判据是正则 `deflated_sharpe_ratio\\s*\\(|bonferroni` —— 实测
    **把 `grid.py` 的 DSR 调用摘掉它照样绿**:因为那条正则的 `bonferroni` 分支命中了
    **本批我自己加的那句注释**("报 DSR 或 Bonferroni")⇒ **注释满足了判据**。
    这与 附一百零九 修的那个"被注释满足的覆盖面用例"是**同一个病**,而我在同批新写的守卫里
    又犯一次。故改为走 AST:找 `Call`,看被调的函数名。
    """
    import ast

    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
        if name == "deflated_sharpe_ratio" or "bonferroni" in name.lower():
            return True
    return False


def test_every_grid_or_sweep_script_reports_a_penalty_metric() -> None:
    """判据 2:每一个都必须**真的调用** DSR 或 Bonferroni(§5 Penalty Metrics)。"""
    bad = []
    for rel in sorted(grid_sweep_scripts()):
        src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        if not _calls_penalty_metric(src):
            bad.append(rel)
    assert not bad, (
        "§5 Penalty Metrics:以下脚本跑多参数网格/sweep 却**不报** DSR 或 Bonferroni:\n  "
        + "\n  ".join(bad)
        + "\n口径请与 `uptrend_pullback/sweep_v33_long.py` 一致:"
        "\n  observed = 成功配置里的最大 Sharpe;n_trials = **枚举出的**配置数;"
        "\n  n_returns = 评估过的交易日数(`core.walkforward.window_trading_days`,单源);"
        "\n  并打印一句 in-sample 声明(附九十六)。"
    )
