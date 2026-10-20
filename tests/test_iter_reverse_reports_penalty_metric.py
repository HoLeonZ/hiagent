"""§5 守卫:`uptrend_pullback/iter_reverse.py` 是多 trial 搜索,必须报惩罚指标。

**发现**(audit 2026-10-15):该脚本做默认 100 次 Monte-Carlo 搜索、按综合分排序、
打印 TOP-K —— 而**完全没有** DSR / Bonferroni / n_trials。§5 verbatim:

  "**Penalty Metrics:** Evaluation scripts must output Deflated Sharpe Ratio (DSR)
   or apply Bonferroni corrections when reporting backtest results from
   multi-parameter sweeps."
  "**Banned In-Sample Grids:** Refuse requests to write simple grid-search scripts
   that return the 'best parameters based on max Sharpe'."

同仓库的姊妹脚本 `uptrend_pullback/sweep_v33_long.py` 是有的 —— 这个漏了。

**修法不是"改成 OOS"**(那是研究设计变更),而是把它**已经做过的选择**如实量化:
  · `observed` = 被选中那个配置的窗口中位 Sharpe(rank-1 那一行);
  · `n_trials`  = **实际评分的配置数**(§5 Iterative-Tuning Accounting 要累计试验数,
                  不是窗口数;用 `len(rows)` 而非 `--iter`,失败的迭代并未被评分);
  · 并显式声明 **selection in-sample** —— DSR 量化的是"从 k 个里挑最好"的虚高,
    **不能替代**样本外验证(要下结论须另跑 `wfv_eval.py`,换一段区间并声明
    `--window-role holdout` —— 本仓库没有代码强制的 train/test 划分)。

注:审计原文说它"在同一窗口选优并直接报告" —— 逐行核对后**不准确**:它用的是
`monthly_windows` 的 22 个滚动窗口。但"选优与报告用同一批窗口"这一实质问题成立。
"""
from __future__ import annotations

import copy
import contextlib
import importlib
import io
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "uptrend_pullback" / "iter_reverse.py"


def _fresh_exec_script() -> str:
    """静态检查用:脚本源码(去注释)。"""
    return "\n".join(
        l for l in SCRIPT.read_text(encoding="utf-8").splitlines()
        if not l.strip().startswith("#")
    )


def test_script_calls_a_penalty_metric() -> None:
    code = _fresh_exec_script()
    assert "deflated_sharpe_ratio" in code, "§5: 多 trial 搜索未输出 DSR"
    assert "bonferroni_correct" in code, "§5: 多 trial 搜索未做 Bonferroni 校正"


def test_n_returns_comes_from_the_run_not_an_estimate() -> None:
    """§5: T 取自**本次运行**(`n_daily_returns`),不得用「21 交易日/月 × 月数」估。

    ## 附七十八 自查:本条此前守的是**相反**的事,而且它已经空转了

    原用例 (`test_window_trading_days_matches_the_repo_convention`) 断言
    `WINDOW_TRADING_DAYS_PER_MONTH = 21` **存在且等于 21**,理由写的是"取自仓库既有口径
    (6 个月 = 126),不得另发明"—— 而那个"既有口径"126 本身就是附六十 修掉的一个猜。

    附六十六 把该常量删掉、改为取运行的 `n_daily_returns` 之后,**这条用例居然仍然通过** ——
    因为我在同一次修改里写的**更正注释**恰好含 `WINDOW_TRADING_DAYS_PER_MONTH = 21`
    这串字面量,而判据是 `re.search(...)` 找字符串。**守卫被注释满足了。**
    (套件当时是绿的;只有"回头量自己新加的东西"才把它翻出来。)

    现按新契约判,三条都用 AST(注释再也满足不了):
      (a) 那个估计常量**没有赋值**(提都不许提不算 —— 赋值才算);
      (b) 取值处确实**读取**了运行产物的 `n_daily_returns`;
      (c) 取不到时**抛错**(不兜底)。
    """
    import ast as _ast

    tree = _ast.parse(SCRIPT.read_text(encoding="utf-8"))

    # (a) 估计常量不得再被赋值
    assigned = {
        t.id for node in tree.body if isinstance(node, _ast.Assign)
        for t in node.targets if isinstance(t, _ast.Name)
    }
    assert "WINDOW_TRADING_DAYS_PER_MONTH" not in assigned, (
        "§5: 仍在用「每月交易日数 × 月数」估 T —— 那是附六十六 修掉的形状"
    )

    # (b) 必须从运行产物的键里读
    reads_key = any(
        isinstance(n, _ast.Subscript) and isinstance(n.slice, _ast.Constant)
        and n.slice.value == "n_daily_returns"
        for n in _ast.walk(tree)
    )
    assert reads_key, "§5: 没有从运行产物读取 n_daily_returns"

    # (c) 取不到必须抛错(而不是退回一个估计)
    raises_about_t = any(
        isinstance(n, _ast.Raise) and "n_daily_returns" in _ast.unparse(n)
        for n in _ast.walk(tree)
    )
    assert raises_about_t, "§5: 取不到 T 时没有 fail-fast(会退回估计值)"


def test_script_states_that_selection_is_in_sample() -> None:
    """DSR 不能替代样本外验证 —— 脚本必须自己说清楚。"""
    assert "in-sample" in SCRIPT.read_text(encoding="utf-8"), (
        "§5: TOP-K 是在同一批窗口上选出的,脚本必须显式声明,"
        "否则读者会把「挑出来的最好」当成「样本外验证过的最好」。"
    )


def test_search_reports_dsr_with_the_count_of_configs_tried(monkeypatch) -> None:
    """行为验证:把搜索桩化,断言输出的 `n_trials` = **试过的配置数**。

    关键设计:`--iter 4` 但**第 3 次迭代失败**(返回 `error`)→ 若按"评出分的配置数"算,
    n_trials 是 3;若按"试过多少"算,是 4。**两者不相等,测试才真的能区分两种口径。**

    (附八十二 更正:本用例的**判据**此处原为前者(`n_trials=3`),并写明了理由
     "用 `--iter`(=4)会把没被评分的迭代也算进去"。那个理由**与 §5 相反** ——
     §5 的原话是"每一次迭代都计入",崩掉的那次配置被采样、被送进评分器,是一次已付出的
     尝试。`--iter` 仍然**不是**正确答案(循环内的显式跳过/提前退出会让枚举数虚高),
     正确答案是"评出分 + 崩掉",两者都印出来。)

    (第一版没设失败迭代,于是 `len(rows) == args.iter`,把 `n_trials` 改成 `args.iter`
    仍然全绿 —— 那是一条**空转**的守卫。)
    """
    mod = importlib.import_module("uptrend_pullback.iter_reverse")
    from uptrend_pullback.presets import get_preset

    # 第 3 次返回 error(不计入评分);其余三次正常
    outcomes = [
        (0.30, 0.90), (1.85, 0.50), "ERROR", (0.70, 0.10),
    ]
    calls = {"n": 0}

    monkeypatch.setattr(mod, "sample_preset",
                        lambda base, rng: copy.deepcopy(get_preset("v33_long_reverse_v19")))

    def fake_score(cfg, windows, db, engine):
        i = calls["n"]; calls["n"] += 1
        item = outcomes[i]
        if item == "ERROR":
            return {"error": "synthetic failure", "windows": []}
        sh, sc = item
        return {"score": sc, "median_ret": 0.01, "mean_ret": 0.01, "worst_ret": -0.01,
                "best_ret": 0.02, "sharpe_med": sh, "avg_dd": 0.05, "worst_dd": 0.09,
                "n_pos": 1, "n_total": 1, "avg_trades": 3.0,
                # 附六十六:每个窗口必须带**引擎发布的**观察数(`n_daily_returns`)——
                # T 现在从它取(此前是 `21 × window_months` 的估计)。给空列表会让
                # iter_reverse 按 §5 fail-fast 抛错,那是刻意的。
                "windows": [{"start": "2024-09-01", "end": "2024-10-31",
                             "n_daily_returns": 42}]}

    monkeypatch.setattr(mod, "score_windows", fake_score)
    monkeypatch.setattr(sys, "argv", ["iter_reverse", "--iter", "4", "--quiet", "--out", ""])

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mod.main()
    out = buf.getvalue()

    assert "n_trials=4" in out, (
        "n_trials 应为**试过的配置数** 4(4 次迭代,其中 1 次评分时崩掉 —— 那次同样算试过)。"
        "§5 Iterative-Tuning Accounting:\"每一次迭代 —— 包括对评估窗口本身的改动 —— "
        "都递增 n_trials\";崩掉的那次配置被采样、被送进评分器,搜索为它花了预算。"
        "实际输出:\n" + "\n".join(l for l in out.splitlines() if "DSR" in l)
    )
    assert "崩掉 1" in out, (
        "少计时必须**印出来**(评出分 3 + 崩掉 1),否则读者会以为 n_trials 就是结果行数。"
    )
    # 被量化的是**被选中配置**的 Sharpe(score 第一 → sharpe 0.30),不是全场的 max
    assert "observed_sharpe=+0.300" in out, (
        "DSR 应当量化**被选中那个配置**的 Sharpe(与 n_trials=配置数 同一次选择),"
        "而不是把所有配置里最大的 Sharpe 拿来当 observed。"
    )
    assert "in-sample" in out


@pytest.mark.parametrize("other", ["sweep_v33_long.py", "sweep_v33_long_v2.py"])
def test_sibling_sweeps_also_keep_their_penalty_metric(other: str) -> None:
    """姊妹 sweep 脚本的惩罚指标不得被移除(它们是这条纪律的对照组)。"""
    code = (REPO_ROOT / "uptrend_pullback" / other).read_text(encoding="utf-8")
    assert "deflated_sharpe_ratio" in code
