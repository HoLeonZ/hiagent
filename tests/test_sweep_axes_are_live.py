"""附八十七 —— 网格**塌掉**时不许再印成敏感性表。

## 缺陷(实测,用的是**已经落盘的产物**,不是我重跑出来的)

`uptrend_pullback/results/sweep_v33_long.json`:

| 网格 | combo 数 | 不同结果数 |
|---|---|---|
| `fixed_tp_sl` | 30 | **1** |
| `loosen_signals` | 36 | **1** |

两条轴 100% 失效,而报表照样把它印成"每行一个参数取值"的敏感性表 —— 读者会据此得出
"这个参数不敏感"。两种原因不同:

1. `fixed_tp_sl` 变 `tp_pct`/`sl_pct`,而 base 里 `atr_tp_mult`/`atr_sl_mult` 都有值
   ⇒ 引擎 `use_atr` 为真时**按设计忽略**这两个键(base 自己注释了「占位,当 atr 模式时不使用」);
2. `loosen_signals` 的键漏了 `signal.` 前缀 ⇒ `_set` 写进 cfg **顶层**,而 `sweep()` 只把
   `cfg["signal"]` 传给信号函数 ⇒ 三个键**从来没被传进去**(已修,见附录)。

## 判据为什么落在"结果是否相同"

"这个键引擎认不认"要按引擎逐条推,且随引擎演进失效;"结果是否相同"是**观测**。
代价:真正的平台期也会被报出来 ⇒ 本模块只**报警**,不判违规。

## 本文件覆盖到哪、没覆盖到哪(如实声明)

* 覆盖:判据本身的语义与**牙齿**(合成的塌网格必须被认出、正常的不得误报);
  六个 uptrend sweep **确实接了**这条报警(AST 检查);
  以及**一次真跑**(v6,25 combo)证明接线没误报。
* **没**覆盖:一次**真跑里的正例**(v1 的 `fixed_tp_sl` 当场被打出来)。
  那条需要 ~7 分钟的 106-combo 全量跑,故只在本附录里做过一次、写在附录里,不放进套件。
  —— 别把"套件全绿"读成"正例也被守住了"。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from core.sweep_axes import (
    DEFAULT_METRIC_KEYS,
    collapsed_grid_warning,
    collapsed_grids,
    distinct_result_count,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
_UP_SWEEPS = [
    REPO_ROOT / "uptrend_pullback" / f"sweep_v33_long{s}.py"
    for s in ("", "_v2", "_v3", "_v4", "_v5", "_v6")
]
_KEYS = ["cagr", "sharpe"]


def test_distinct_result_count_ignores_non_metric_differences() -> None:
    rows = [{"cagr": 0.1, "sharpe": 0.5, "tp_pct": 0.2}, {"cagr": 0.1, "sharpe": 0.5, "tp_pct": 0.3}]
    assert distinct_result_count(rows, _KEYS) == 1, (
        "两个 combo 只有**被扫的参数**不同、结果逐位相同 ⇒ 应当算 1 个结果"
    )


def test_a_collapsed_grid_is_reported() -> None:
    inert = [{"cagr": 0.1, "sharpe": 0.5}] * 36
    assert collapsed_grids({"loosen_signals": inert}, _KEYS) == [("loosen_signals", 36)]
    warn = collapsed_grid_warning({"loosen_signals": inert}, _KEYS)
    assert "loosen_signals" in warn and "36" in warn


def test_a_live_grid_is_not_reported() -> None:
    live = [{"cagr": 0.1, "sharpe": 0.5}, {"cagr": 0.2, "sharpe": 0.6}]
    assert collapsed_grids({"fine_tune": live}, _KEYS) == []
    assert collapsed_grid_warning({"fine_tune": live}, _KEYS) == ""


def test_a_single_combo_grid_is_not_called_collapsed() -> None:
    """只有一个 combo 的网格本来就没打算比 —— 不算"塌"。"""
    assert collapsed_grids({"one": [{"cagr": 0.1, "sharpe": 0.5}]}, _KEYS) == []


def test_the_helper_has_teeth() -> None:
    """**牙齿**:把"整格相同"改成"只差一个非指标列"仍必须被认出;
    而"真的有两个不同结果"必须不得被认出。

    (没有这条,"没报警"无法区分"网格正常"与"判据坏了"。)
    """
    inert = [{"cagr": 0.1, "sharpe": 0.5, "tp_pct": v} for v in (0.1, 0.2, 0.3)]
    assert len(inert) == 3 and distinct_result_count(inert, _KEYS) == 1
    assert collapsed_grids({"g": inert}, _KEYS), "只差非指标列的整格相同没被认出"

    differing = [{"cagr": 0.1, "sharpe": 0.5}, {"cagr": 0.1, "sharpe": 0.500001}]
    assert not collapsed_grids({"g": differing}, _KEYS), "真有差异却报了警"


@pytest.mark.parametrize("path", _UP_SWEEPS, ids=lambda p: p.name)
def test_every_uptrend_sweep_wires_the_collapse_warning(path: Path) -> None:
    """六个 uptrend sweep 都必须把**它自己那批网格**交给这条报警。

    只检查"调用了"是不够的 —— 还要检查它把**全部**网格传进去(v1~v4 用 `results` 字典,
    v5/v6 用单个 `df`),否则漏一个网格就少一次报警。
    """
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "collapsed_grid_warning"
    ]
    assert calls, f"{path.name} 没有接 collapsed_grid_warning —— 网格塌了不会有人说话"

    arg = ast.unparse(calls[0].args[0])
    is_multi = "_d.to_dict" in arg or "results" in arg
    is_single = "df.to_dict" in arg
    assert is_multi or is_single, f"{path.name}: 传进去的不是网格字典({arg})"
    has_multi_grids = "results: dict" in src or "results[" in src
    if has_multi_grids:
        assert is_multi, (
            f"{path.name} 有多个网格(results 字典)却只把单个 df 交去检查 —— 别的网格塌了没人报"
        )



@pytest.mark.slow
def test_a_real_grid_with_an_inert_key_is_reported() -> None:
    """**真数据正例**:在真实网格里塞一个引擎不读的键,报警必须打出来。

    (补上本文档开头声明的缺口:上面几条只证明"判据语义对"与"接线存在",
     这一条证明它在**真的跑起来**的网格上会响。用 2 个 combo 的极小网格,
     不必等 v1 那 106-combo 的 7 分钟。)
    """
    import importlib
    from copy import deepcopy

    from tests.conftest import require_market_db

    require_market_db()
    from hiagent_config import DB_PATH
    from uptrend_pullback.data import load_panel
    from uptrend_pullback.presets import get_preset
    from uptrend_pullback.signals import compute_indicators
    from uptrend_pullback.universe import load_universe

    mod = importlib.import_module("uptrend_pullback.sweep_v33_long_v6")

    # base 取自**现存 preset**(而不是在手抄一份配置 —— 手抄的那份会随引擎漂移)
    base = deepcopy(dict(get_preset("v33_long_reverse_v19")))
    base["max_positions"] = 1
    from pathlib import Path
    universe = set(load_universe("mainboard_only", Path(DB_PATH), asof_date=mod.START))
    panel = load_panel(Path(DB_PATH), mod.START, mod.END, universe=universe)
    panel_ind = compute_indicators(panel)

    live = mod.sweep(base, {"max_hold": [8, 10]}, panel_ind)
    assert not live.empty, "夹具失效:活网格一个 combo 都没跑出来"
    assert collapsed_grid_warning({"live": live.to_dict("records")}, DEFAULT_METRIC_KEYS) == "", (
        "活网格被误报为塌掉"
    )

    inert = mod.sweep(base, {"universe": ["mainboard_only", "nonexistent_universe"]}, panel_ind)
    assert not inert.empty, "夹具失效:死网格一个 combo 都没跑出来"
    warn = collapsed_grid_warning({"inert": inert.to_dict("records")}, DEFAULT_METRIC_KEYS)
    assert "inert" in warn, (
        "引擎**不读**的键(`universe`,sweep 从不读它)造成的整格相同没有被报出来 —— "
        f"实际:\n{warn or '(空)'}"
    )

