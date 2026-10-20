"""`tools/run_all_backtests_html.py` 的渲染守卫(此前**无任何测试**)。

两类问题:

**1 · §0/§2:「无法定义」不得被换成 0 参与排名**

`cycle_price_action` 的 `cagr` / `sharpe` / `max_dd` 是 `None` —— 横截面研究
(每股一个独立账户)里这三个量**无法定义**(见 `cycle_price_action/metrics.py` 的口径说明)。
该工具原先用 `metrics.get("sharpe") or 0.0` 把它们换成 `0.0`,后果有两层:

  · 渲染层:页面上显示 `0.00`,与"真的等于零"无法区分;
  · 排名层:它会带着这个**假数字**进入「按 Sharpe / CAGR / max_dd 的跨策略 TOP-8 榜」。

现改为保持 `None` —— `_fmt_pct` / `_fmt_num` 本就把 None 渲染成「—」,而
`render_rank` 本来就过滤 `None`,于是它自然地**退出排名**而不是以 0 参赛。

**2 · §2:`sharpe` 跨引擎不是同一个量**

`chase_up` / `uptrend_pullback` 是日收益年化 Sharpe;`short_reversal` 是逐笔比率近似;
`cycle` 无定义(见审计附十一)。故「按 Sharpe 排序」**跨策略没有意义** —— 该工具
现在把每行的 `sharpe_kind` 带进产物,并在排名区块顶部写明这一点。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tools" / "run_all_backtests_html.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("run_all_backtests_html", TOOL_PATH)
    assert spec and spec.loader, f"无法加载 {TOOL_PATH}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(preset: str, *, cagr, sharpe, max_dd, kind) -> dict:
    return {
        "preset": preset, "trades": 5, "win_rate": 0.5,
        "cagr": cagr, "sharpe": sharpe, "max_dd": max_dd,
        "final_equity": 1_000_000.0, "total_return": 0.0, "avg_hold_days": 3.0,
        "sharpe_kind": kind,
    }


def _report() -> dict:
    def strat(name, engine, row):
        return {"name": name, "title": name, "engine": engine,
                "description": "synthetic", "rows": [row]}

    return {
        "strategies": [
            # cycle:三个量都「无法定义」
            strat("cycle_price_action", "CyclePriceAction",
                  _row("v1", cagr=None, sharpe=None, max_dd=None, kind=None)),
            strat("chase_up", "ChaseUp",
                  _row("v5", cagr=0.12, sharpe=0.42, max_dd=0.2,
                       kind="daily_returns_annualized")),
        ],
        "elapsed_seconds": 1.0, "started_at": "2026-10-16 00:00:00",
        "error_count": 0, "start": "2025-09-08", "end": "2026-09-08",
        "db_path": "/tmp/synthetic.duckdb",
    }


def test_module_imports() -> None:
    """零测试的工具至少要能被导入(冒烟)。"""
    assert callable(_load_tool().render_html)


def test_undefined_metrics_render_without_crashing() -> None:
    """None 不得让渲染崩溃(此前 `abs(cagr)` / `cagr < 0` 会 TypeError)。"""
    html = _load_tool().render_html(_report())
    assert "—" in html, "「无法定义」未渲染为占位符"


def test_undefined_metrics_do_not_enter_cross_strategy_rankings() -> None:
    """§0/§2:被换成 0.0 的假数字不得以任何名次进入跨策略榜。

    这是本条修复的**要害** —— 排名榜会被当作结论读,而一个「无法定义」的量
    在其中占一个名次,比不显示它危险得多。
    """
    tool = _load_tool()
    cross = tool._render_cross_strategy(_report())
    assert "v1" not in cross, (
        "cycle 的「无法定义」(None)仍以某个名次出现在跨策略榜里 —— "
        "它应当是「不参与排名」,而不是被换成 0 参赛。"
    )
    assert "v5" in cross, "对照组(chase_up,指标有定义)应当出现在榜上(否则本条空转)"


def test_sharpe_kind_is_published_and_incomparability_is_stated() -> None:
    """§2:`sharpe` 的定义随产物发布,且排名区块顶部写明跨策略不可比。"""
    tool = _load_tool()
    html = tool.render_html(_report())
    cross = tool._render_cross_strategy(_report())
    assert "daily_returns_annualized" in html, "sharpe_kind 未随产物发布"
    assert "per_trade_ratio_approx" in cross or "不是同一个量" in cross, (
        "跨策略排名区块未说明「Sharpe 在各引擎不是同一个量」—— "
        "读者会把不可比的数字当成可比。"
    )


def test_tool_derives_paths_from_file_not_hardcoded() -> None:
    """§0 可复现性:不得出现硬编码绝对路径(审计在别的脚本里抓到过这一条)。"""
    src = TOOL_PATH.read_text(encoding="utf-8")
    assert "/Users/" not in src, "工具里出现了硬编码的绝对路径"


def test_tool_writes_only_into_gitignored_results_dir() -> None:
    """§7:产物目录必须是 gitignore 覆盖的 `results/`。"""
    src = TOOL_PATH.read_text(encoding="utf-8")
    assert 'OUT_DIR = REPO / "results"' in src, (
        "产物目录不再是 gitignore 覆盖的 results/ —— §7 要求运行产物不入库"
    )


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_non_finite_renders_as_placeholder(bad: float) -> None:
    """§0:nan / inf 也必须渲染为占位符,不得写进 HTML。"""
    report = _report()
    report["strategies"][1]["rows"][0]["cagr"] = bad
    html = _load_tool().render_html(report)
    assert "nan" not in html.lower().replace("—", ""), "nan 泄漏进了 HTML"
    assert "inf" not in html.lower().replace("—", ""), "inf 泄漏进了 HTML"
