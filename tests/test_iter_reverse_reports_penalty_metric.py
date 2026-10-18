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
    **不能替代**样本外验证(要下结论须另跑 `wfv_eval.py` 的 train/test)。

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


def test_window_trading_days_matches_the_repo_convention() -> None:
    """`n_returns` 用的 21 交易日/月必须取自仓库既有口径(6 个月 = 126),不得另发明。"""
    code = SCRIPT.read_text(encoding="utf-8")
    m = re.search(r"WINDOW_TRADING_DAYS_PER_MONTH\s*=\s*(\d+)", code)
    assert m, "未定义 WINDOW_TRADING_DAYS_PER_MONTH"
    assert int(m.group(1)) == 21, (
        "21 = 126/6(仓库 walk-forward 家族的既有口径)。改动它等于改 DSR 的 SE 项。"
    )


def test_script_states_that_selection_is_in_sample() -> None:
    """DSR 不能替代样本外验证 —— 脚本必须自己说清楚。"""
    assert "in-sample" in SCRIPT.read_text(encoding="utf-8"), (
        "§5: TOP-K 是在同一批窗口上选出的,脚本必须显式声明,"
        "否则读者会把「挑出来的最好」当成「样本外验证过的最好」。"
    )


def test_search_reports_dsr_with_the_scored_config_count(monkeypatch) -> None:
    """行为验证:把搜索桩化,断言输出的 `n_trials` = **实际评分的配置数**。

    关键设计:`--iter 4` 但**第 3 次迭代失败**(返回 `error`)→ 实际评分的配置数是 3。
    这样 `len(rows)`(=3)与 `args.iter`(=4)**不相等**,测试才真的能区分两种口径。

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

    assert "n_trials=3" in out, (
        "n_trials 应为**实际评分的配置数** 3(4 次迭代中有 1 次失败)—— "
        "用 `--iter`(=4)会把没被评分的迭代也算进去。实际输出:\n"
        + "\n".join(l for l in out.splitlines() if "DSR" in l)
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
