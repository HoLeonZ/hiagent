"""附七十一 —— `sharpe_kind` 必须**渲染出来**,而不只是"随数据发布"。

## 背景

`tools/run_all_backtests_html.py` 的跨策略排名段落早就写着:

> ⚠ 跨策略可比性(2026-10-15 更正):… ② **Sharpe 在三个引擎里不是同一个量** ——
> chase_up / uptrend_pullback 是 `daily_returns_annualized`,short_reversal 是
> `per_trade_ratio_approx`;故「按 Sharpe 排序」**跨策略没有意义** …
> (每行的 `sharpe_kind` 已随数据发布)

那句"已随数据发布"**字面为真**(kind 写在行数据里、也进了 JSON),但 **HTML 里从不显示它** ——
于是那条警示指向的是读者**在页面上看不见**的东西。缺的是**渲染**这一步,不是数据。

## 处置

Sharpe 格渲染成「数字 + 量纲小标签」(全名放 `title`,悬停可见);未知 kind **原样显示**
而不是留空 —— 留空会让"没有量纲信息"与"量纲恰好为空"分不开(本仓库反复吃过"静默的零"的亏)。
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


def _row(preset: str, kind: str | None, sharpe: float = 1.0) -> dict:
    return {
        "preset": preset, "cagr": 0.10, "sharpe": sharpe, "sharpe_kind": kind,
        "max_dd": -0.05, "win_rate": 0.5, "trades": 10,
    }


def test_kind_is_rendered_in_the_per_strategy_table() -> None:
    """逐策略表:两个引擎的不同量纲都要**看得见**。"""
    mod = _load_tool()
    html = mod._render_table([
        _row("chase_v11", "daily_returns_annualized"),
        _row("v44_ratio02_buf07", "per_trade_ratio_approx"),
    ])
    assert "日年化" in html, f"未渲染 chase 的量纲标签:{html[:200]}"
    assert "逐笔近似" in html, "未渲染 short_reversal 的量纲标签"
    # 全名放 title(悬停可见),读者能核到原始 kind 字符串
    assert "sharpe_kind = daily_returns_annualized" in html
    assert "sharpe_kind = per_trade_ratio_approx" in html


def test_kind_is_rendered_in_the_cross_strategy_rank() -> None:
    """跨策略排名表:那句警示说的正是这张表,量纲必须在这张表上可见。"""
    mod = _load_tool()
    report = {
        "strategies": [
            {"name": "chase_up", "title": "追涨",
             "rows": [_row("chase_v11", "daily_returns_annualized", 2.0)]},
            {"name": "short_reversal", "title": "做空反转",
             "rows": [_row("v44_ratio02_buf07", "per_trade_ratio_approx", 1.5)]},
        ],
    }
    html = mod._render_cross_strategy(report)
    assert "跨策略排名" in html
    assert "日年化" in html and "逐笔近似" in html, (
        "跨策略排名表里没有量纲标注 —— 读者仍只能看到一个跨引擎不可比的数字"
    )


def test_unknown_kind_is_shown_not_blanked() -> None:
    """未知 kind ⇒ 原样显示(留空会让"无量纲信息"与"量纲为空"分不开)。"""
    mod = _load_tool()
    html = mod._render_table([_row("x", "some_new_kind_v9")])
    assert "some_new_kind_v9" in html


def test_missing_kind_renders_plain_number_without_a_tag() -> None:
    """没有 kind ⇒ 只剩数字,不出现空标签。"""
    mod = _load_tool()
    html = mod._render_table([_row("x", None)])
    assert "kind" not in html.split("<tbody>")[1].split("</tbody>")[0]


def test_sharpe_cell_keeps_the_td_for_css() -> None:
    """**回归守卫(记我自己的错)**:量纲标签必须只进 `<td>` 的**内容**。

    第一版我把 `<td>` 一起包进了 `_sharpe_cell` 返回的字符串,于是 CSS 里的
    `td.num` / `td.good` / `td.bad` **全部失效** —— 选择器对的是 `td`,而它变成了 `span`。
    """
    mod = _load_tool()
    cell = mod._sharpe_cell(1.0, "daily_returns_annualized")
    assert "<td" not in cell and "<span class='num" not in cell, (
        "_sharpe_cell 不应自带 <td>/num 包装(会把调用方的 td class 挤掉)"
    )
    html = mod._render_table([_row("chase_v11", "daily_returns_annualized")])
    assert "<td class='num good'>" in html or "<td class='num neutral'>" in html or \
           "<td class='num bad'>" in html, "Sharpe 格的 td class 丢了 —— CSS 会失效"


def _report(rows_by_strategy: list[tuple[str, str, list[dict]]]) -> dict:
    """按**生产端真正的 schema**造 report(见 `run_all_backtests_html.py` 的返回处)。

    (第一版夹具是我手写的,漏了 `engine` 键 ⇒ `render_html` 直接 KeyError ——
    这正说明"整页渲染"这一层值得单独守:它会把 schema 缺键当场暴露出来。)
    """
    return {
        "started_at": "2026-10-18T12:00:00",
        "elapsed_seconds": 12.3,
        "start": "2025-09-08",
        "end": "2026-09-08",
        "db_path": "/tmp/x.duckdb",
        "strategies": [
            {"name": n, "title": t, "engine": "pandas", "description": "d", "rows": rs}
            for n, t, rs in rows_by_strategy
        ],
        "error_count": 0,
    }


def test_full_page_render_carries_kind_and_css() -> None:
    """整页渲染:量纲标签、`title` 全名、以及 `.kind` 的 CSS 都必须在。"""
    mod = _load_tool()
    html = mod.render_html(_report([
        ("chase_up", "追涨", [_row("chase_v11", "daily_returns_annualized", 2.0)]),
        ("short_reversal", "做空反转",
         [_row("v44_ratio02_buf07", "per_trade_ratio_approx", 1.5)]),
    ]))
    assert "span.kind" in html, "CSS 里没有 .kind 规则 —— 标签会没有样式"
    assert "日年化" in html and "逐笔近似" in html
    assert "sharpe_kind = daily_returns_annualized" in html
    assert "<td class='num good'>" in html, "Sharpe 格的 td class 丢了(CSS 会失效)"
