"""声明的产物必须真的产出: `equity_curve.csv` / `cash_walk.csv`。

缺陷 (2026-10-17): `main.py` 写这两个文件的开关是
    eq_rows = m.get("equity_curve")
    if eq_rows: _write_equity_curve(...)
而 `_metrics_from_holder()` **从不把 `holder["equity_curve"]` 拷进返回的 metrics**
⇒ 开关恒为假 ⇒ 两个文件**从未被写出**, 尽管注释写着 "§2/§3 Tick 51 GREEN"。
(strategy 一直在累积那串数据, 只是没人把它带出来。)

**发现过程本身值得记**: 本轮想核对 `max_dd` 与权益曲线是否一致, 结果短侧**根本没有
这份产物**; 我在同目录里读到了 **chase_up** 留下的同名文件 (两个引擎写**同一套列名**
`date,cash,position_value,total_equity,drawdown`), 于是把 chase_up 的 85.95% 回撤
当成了 short_reversal 的, 先报了一个错误的"不一致"。**文件名不携带引擎身份。**

更正后的事实 (用短侧自己的曲线): 报告 max_dd 72.61% **与曲线逐位一致**;
但 Sharpe 口径确实不同 —— 同一次运行 日口径(+0.2618) vs 报告逐笔(-2.3858)。
"""
from __future__ import annotations

from pathlib import Path

import pytest

ENGINE = (Path(__file__).parent.parent / "short_reversal" / "engine.py").read_text(
    encoding="utf-8"
)


def test_metrics_carry_the_equity_curve() -> None:
    """metrics 必须带出 equity_curve —— 否则 main.py 的写盘开关恒为假。"""
    assert '"equity_curve": holder.get("equity_curve", [])' in ENGINE


@pytest.mark.skipif(
    not Path("/tmp/sr_iso3/equity_curve.csv").exists(), reason="需要本地回测产物"
)
def test_artifact_matches_reported_max_dd() -> None:
    """报告的 max_dd 必须等于曲线上的最大回撤 (同一次运行内)。"""
    import json

    import pandas as pd

    eq = pd.read_csv("/tmp/sr_iso3/equity_curve.csv")
    te = pd.to_numeric(eq["total_equity"], errors="coerce")
    dd = float((1 - te / te.cummax()).max())
    m = json.loads(Path("/tmp/sr_iso3/m.json").read_text())
    assert abs(dd - m["max_dd"]) < 1e-9, f"曲线回撤 {dd} vs 报告 {m['max_dd']}"
