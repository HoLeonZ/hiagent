"""§5 守卫:chase_up 的**单一窗口**选优脚本必须声明"这是样本内选择"。

`chase_up/sweep.py` 与 `chase_up/sweep_all.py` 都在**一个**窗口
(`--start 2025-09-19 → --end 2026-09-19`)上给一批配置排序,并报告 DSR。

它们**做对了**的部分(先记下来,免得读者以为整条都不合格):
  · `observed = max(sharpes)` 配 `n_trials = 试过的配置数` —— 同一次搜索、同一个折减对象 ✓
    (附八十二 更正:原先此处写的是 `n_trials = len(sharpes)`,即**只数跑成功的那批**;
     而 §5 要求"每一次迭代都计入" —— 抛异常的、没产出信号的也是一次迭代。
     现在 `n_trials` 数**全部落盘行**,并把它与成功数之差**印出来**。两者故意不等,
     但仍同源于同一次搜索:`observed` 只在有数的配置间取 max,折减按试过的个数。);
  · `n_returns=252` —— 对 **12 个月**窗口而言是 `21 × 12`,与 walk-forward 家族的
    既有口径(6 个月 = 126)**一致** ✓,不是缺陷(这一点我核对过,免得误报)。

它们**缺**的那一步:选优是**样本内**的,而输出里**只字未提**。§5 要求
"Optimization logic must enforce Walk-Forward Validation (WFV) with strict
out-of-sample (OOS) testing windows";DSR 量化的是"从 k 个里挑最好"的虚高,
**不能替代**样本外验证。而本仓库**已经有**滚动窗口版本
(`chase_up/wf_sweep_all.py`)—— 所以读者没有任何理由把这个榜当成 OOS 结论,
脚本必须自己说清楚。
"""
from __future__ import annotations

import contextlib
import importlib
import io
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = {
    "sweep": REPO_ROOT / "chase_up" / "sweep.py",
    "sweep_all": REPO_ROOT / "chase_up" / "sweep_all.py",
}


@pytest.mark.parametrize("name,path", sorted(SCRIPTS.items()))
def test_single_window_sweep_discloses_in_sample_selection(name: str, path: Path) -> None:
    src = path.read_text(encoding="utf-8")
    assert "in-sample" in src, (
        f"§5: {name} 在单一窗口上选优,却未声明这是**样本内选择** —— "
        "读者会把「挑出来的最好」当成「样本外验证过的最好」。"
    )


@pytest.mark.parametrize("name,path", sorted(SCRIPTS.items()))
def test_single_window_sweep_points_at_the_walk_forward_sibling(name: str, path: Path) -> None:
    """必须把读者引向本仓库**已有**的滚动窗口版本,而不是让他自己想。"""
    src = path.read_text(encoding="utf-8")
    assert "wf_sweep_all" in src, (
        f"§5: {name} 未指向滚动窗口版本 `chase_up/wf_sweep_all.py` —— "
        "那正是把「单窗选优」升级为「walk-forward」的现成路径。"
    )


#: 「试过多少个」的表达式 —— 必须是**全部落盘行**(成功 + 失败),不是"跑成功的那批"。
#: 改动理由见 `tests/test_n_trials_counts_failures.py`(附八十二)。
_TRIED_EXPR = {
    "sweep": "_n_tried = int(len(df))",
    "sweep_all": "_n_tried = int(len(rows) + len(failed))",
}


def _assert_max_and_n_trials_describe_the_same_search(src: str, name: str) -> None:
    """`observed` 与 `n_trials` 必须描述**同一次搜索**。

    * `observed = max(sharpes)` —— 选择只在**有数的**配置之间发生(m 个);
    * `n_trials` —— 折减用的是**试过的**个数 k ≥ m(§5:每一次迭代都计入,
      含抛异常的与没产出信号的)。

    两者**故意不等**,但必须同源于**同一次搜索**:`n_trials` 不得小于成功数
    (那会把"从 m 个里挑"说成"从更少的里面挑",虚高),也不得凭空来自别处。
    """
    code = "\n".join(
        l for l in src.splitlines() if not l.strip().startswith("#")
    )
    assert "observed = max(sharpes)" in code, f"{name}: observed 不再是 max(sharpes)"
    assert _TRIED_EXPR[name] in code, (
        f"{name}: `n_trials` 不再数「试过多少」—— 期望 `{_TRIED_EXPR[name]}`"
        "(§5:每一次迭代都计入,含失败的)"
    )
    assert "n_trials=_n_tried" in code, f"{name}: n_trials 没有用 _n_tried"
    assert "_n_ok = int(len(sharpes))" in code, f"{name}: 没有把成功数算出来对比"
    assert "if _n_tried != _n_ok:" in code, (
        f"{name}: 少计发生时没有**印出来** —— 读者会以为 n_trials 就是结果行数"
    )


@pytest.mark.parametrize("name,path", sorted(SCRIPTS.items()))
def test_max_and_n_trials_describe_the_same_search(name: str, path: Path) -> None:
    _assert_max_and_n_trials_describe_the_same_search(
        path.read_text(encoding="utf-8"), name
    )


def test_the_pairing_check_has_teeth() -> None:
    """**牙齿**:把 `n_trials` 退回"只数成功的那些",必须被认出来。"""
    good = (
        "observed = max(sharpes)\n"
        "_n_tried = int(len(df))\n"
        "_n_ok = int(len(sharpes))\n"
        "dsr = deflated_sharpe_ratio(observed_sharpe=observed, n_trials=_n_tried)\n"
        "if _n_tried != _n_ok:\n    pass\n"
    )
    _assert_max_and_n_trials_describe_the_same_search(good, "sweep")   # 不得误报

    regressed = good.replace("_n_tried = int(len(df))", "_n_tried = int(len(sharpes))")
    with pytest.raises(AssertionError):
        _assert_max_and_n_trials_describe_the_same_search(regressed, "sweep")

    silent = good.replace("if _n_tried != _n_ok:", "if False:")
    with pytest.raises(AssertionError):
        _assert_max_and_n_trials_describe_the_same_search(silent, "sweep")


def test_sweep_all_prints_the_disclosure(monkeypatch, tmp_path) -> None:
    """行为验证(而非只看源码):把预设表与回测桩化,断言警示**真的被打印**。"""
    import numpy as np
    import pandas as pd

    from chase_up.backtest import compute_metrics

    mod = importlib.import_module("chase_up.sweep_all")

    eq = pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=30, freq="B"),
        "equity": np.linspace(1e6, 1.05e6, 30),
        "holdings": np.full(30, 5e5),
    })
    tr = pd.DataFrame({
        "net_pnl": [1000.0, -200.0], "net_return": [0.01, -0.002],
        "hold_days": [5, 3], "exit_reason": ["TP", "SL"],
    })
    base = compute_metrics(tr, eq)          # 用真实指标字典,避免缺键

    monkeypatch.setattr(mod, "PRESETS", {"p1": {}, "p2": {}, "p3": {}})

    def fake(name, start, end, db, verify=True):
        m = dict(base)
        m["sharpe"] = {"p1": 0.4, "p2": 1.9, "p3": 0.6}[name]
        return {"metrics": m}

    monkeypatch.setattr(mod, "run_backtrader_backtest", fake)
    # 产物写进 pytest 的 tmp_path —— 测试不得往仓库树里落文件(§7 精神)
    monkeypatch.setattr(sys, "argv", [
        "sweep_all", "--out", str(tmp_path),
        "--db-path", "/dev/null", "--no-verify",
    ])

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mod.main()
    out = buf.getvalue()
    assert "§5 DSR" in out, "未打印 DSR"
    assert "in-sample" in out, "未打印「样本内选择」警示(仅写在源码里不算)"
    assert "wf_sweep_all" in out, "警示未指向滚动窗口版本"
