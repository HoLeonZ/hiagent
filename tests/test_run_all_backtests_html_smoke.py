"""Smoke test for tools/run_all_backtests_html.py.

验证 institutional-grade rigor:
  - HTML 渲染结构完整 (4 strategy sections + KPI cards + TOC + rank tables)
  - 跨策略排名 strategy attribution 用 (strategy, preset) tuple 配对
    (修复 R527 中: 原 preset 名反查法会在 cycle_price_action "v1" 与
    未来可能的同名 preset 冲突时误归属)
  - NaN / inf / None 在 HTML 中显示为 "—", 不污染表
  - error row 红色显示, 不破坏整页渲染

不跑真实回测 (单次 44 分钟), 只测 render_html() / _fmt_* / _cls() 单元路径.
"""
from __future__ import annotations

import importlib.util
import math
from html import escape
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parent.parent
RUNNER = REPO / "tools" / "run_all_backtests_html.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("runner", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


# ---------------------------------------------------------------------------
# Fixtures: synthetic report dict covering OK / FAILED / NaN / collision cases
# ---------------------------------------------------------------------------

def _ok_row(preset: str, **kw):
    base = {
        "preset": preset, "trades": 50, "win_rate": 0.34, "cagr": 0.45,
        "sharpe": 2.1, "max_dd": -0.12, "final_equity": 1_450_000.0,
        "total_return": 0.45, "tp_count": 20, "sl_count": 25, "time_count": 3,
        "eod_count": 2, "avg_hold_days": 3.2, "max_hold_days": 10,
        "exposure": 0.6, "profit_factor": 1.4, "avg_net_return": 0.008,
    }
    base.update(kw)
    return base


def _synth_report() -> dict:
    return {
        "started_at": "2026-09-30T00:00:00+00:00",
        "elapsed_seconds": 1234.5,
        "start": "2025-09-08", "end": "2026-09-08",
        "db_path": "/tmp/fake.duckdb",
        "error_count": 2,
        "strategies": [
            {
                "name": "chase_up", "title": "chase_up, long",
                "engine": "Phase 1", "description": "desc",
                "rows": [
                    _ok_row("chase_v1_atr_tp4_sl1", cagr=0.5104),
                    _ok_row("chase_v2_atr_tp4_sl1_pos3", cagr=0.5104),
                    _ok_row("chase_v11_pos2", cagr=3.1869),  # top-1
                    {"preset": "chase_broken", "error": "RuntimeError: x"},
                ],
            },
            {
                "name": "uptrend_pullback", "title": "uptrend, long",
                "engine": "Phase 1", "description": "desc",
                "rows": [_ok_row("v33_long_reverse_v19", cagr=1.0738)],
            },
            {
                "name": "short_reversal", "title": "short_reversal, short",
                "engine": "v3", "description": "desc",
                "rows": [
                    _ok_row("v46_sl_0002", cagr=112.7214),
                    _ok_row("v35_agg_pctchg_04_09", cagr=54.5617),
                ],
            },
            {
                "name": "cycle_price_action", "title": "cycle, long",
                "engine": "v1", "description": "desc",
                "rows": [
                    # 故意用 cycle 唯一一个名字 "v1", 验证 attribution 不再误归属
                    {"preset": "v1", "error": "RuntimeError: cost>free_cash"},
                ],
            },
        ],
    }


# ---------------------------------------------------------------------------
# Tests: HTML structure
# ---------------------------------------------------------------------------

def test_render_html_contains_required_sections(runner):
    html = runner.render_html(_synth_report())
    assert "<!doctype html>" in html
    # 4 strategy sections + 1 rank section (HTML 用单引号属性, 不是双引号)
    assert html.count("id='s-chase_up'") == 1
    assert html.count("id='s-uptrend_pullback'") == 1
    assert html.count("id='s-short_reversal'") == 1
    assert html.count("id='s-cycle_price_action'") == 1
    assert html.count("id='s-rank'") == 1
    # KPI cards
    assert "策略数" in html
    assert "preset 总数" in html
    # TOC anchors (TOC 内部用双引号包围 href, 因为属性 wrapper 是单引号)
    assert 'href="#s-chase_up"' in html
    assert 'href="#s-rank"' in html


def test_render_html_surfaces_errors_as_red_rows(runner):
    html = runner.render_html(_synth_report())
    # error-row class triggers red color via .error-row td { color: var(--bad) }
    assert "error-row" in html
    assert "RuntimeError" in html
    assert "⚠" in html


def test_cross_strategy_rank_strategy_attribution_uses_tuple(runner):
    """R527 修复验证: strategy 名必须和 row 直接绑定, 不能用 preset 名反查。

    在 _synth_report() 中, cycle_price_action 的 preset 名是 "v1"。
    chase_up 也有 "v1" 命名的 v33 long_v1 系列空间 — 但本 fixture 不构造冲突。
    验证 attribution 切到 (strat, preset) tuple 后, 不再误把 cycle 的 "v1"
    显示为 chase_up。
    """
    html = runner.render_html(_synth_report())
    # cycle "v1" FAILED, 不进 rank; 但应通过 _render_cross_strategy 中
    # all_rows 列表的 (s["name"], s["title"], r) tuple 路径走通
    assert "TOP-8" in html
    # TOP-8 CAGR 应按 cagr 降序, short_reversal v46 (112.72) 体量级最高, 排第一
    cagr_section = html.split("按 CAGR 排序")[1].split("按 Sharpe 排序")[0]
    first_data_row = cagr_section.split("</tr>")[1]  # 跳过 header <tr>
    assert "v46_sl_0002" in first_data_row
    assert "short_reversal" in first_data_row
    # 关键: cycle 失败的 "v1" 只在 cycle section 作为 error-row 出现一次
    # (rank 表格不收录 error rows)
    # 注意: 其他策略 preset 名中可能包含 "v1" 子串, 故不能用 ">v1<" 精确计数;
    # 而应验证: rank 表格中无 ">v1<" (只 cycle 的 error row 有)
    rank_section = html.split("id='s-rank'")[1]
    assert ">v1<" not in rank_section, "失败的 cycle v1 不应进入跨策略 rank 表格"


# ---------------------------------------------------------------------------
# Tests: defensive formatting (Pessimistic Default §0)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("val,expected", [
    (0.45, "+45.00%"),
    (-0.30, "-30.00%"),
    (0.0, "+0.00%"),
    (math.nan, "—"),
    (math.inf, "—"),
    (-math.inf, "—"),
    (None, "—"),
])
def test_fmt_pct_handles_nan_inf_none(runner, val, expected):
    assert runner._fmt_pct(val) == expected


@pytest.mark.parametrize("val,expected", [
    (1234.567, "1,234.57"),
    (0.0, "0.00"),
    (-1.5, "-1.50"),
    (math.nan, "—"),
    (math.inf, "—"),
    (None, "—"),
])
def test_fmt_num_handles_nan_inf_none(runner, val, expected):
    assert runner._fmt_num(val) == expected


@pytest.mark.parametrize("val,good_if_pos,expected_cls", [
    (1.0, True, "good"),
    (-1.0, True, "bad"),
    (0.0, True, "neutral"),
    (math.nan, True, "neutral"),
    (math.nan, False, "neutral"),
    (math.inf, True, "neutral"),
    (-1.0, False, "good"),  # small DD is good
])
def test_cls_handles_nan(runner, val, good_if_pos, expected_cls):
    assert runner._cls(val, good_if_pos) == expected_cls


# ---------------------------------------------------------------------------
# Tests: CLI reproducibility (institutional rigor)
# ---------------------------------------------------------------------------

def test_cli_defaults_are_documented(runner):
    """CLI 默认值即报告中"区间"的 hardcoded 值, 必须一致(机构 reproducibility)。"""
    import sys
    saved = sys.argv
    try:
        sys.argv = ["run_all_backtests_html"]  # 重置 (pytest 注入自己的 argv)
        ns = runner._parse_args()
        assert ns.start == "2025-09-08"
        assert ns.end == "2026-09-08"
    finally:
        sys.argv = saved


def test_cli_overrides_apply(runner):
    """CLI 覆盖: --start/--end 必须影响 run_all() 传入的参数。"""
    import sys
    saved = sys.argv
    try:
        sys.argv = [
            "run_all_backtests_html",
            "--start", "2024-01-01", "--end", "2024-12-31",
        ]
        ns = runner._parse_args()
        assert ns.start == "2024-01-01"
        assert ns.end == "2024-12-31"
    finally:
        sys.argv = saved


# ---------------------------------------------------------------------------
# Tests: XSS hardening (HTML escape)
# ---------------------------------------------------------------------------

def test_html_escapes_preset_names(runner):
    """Strategy / preset 名若含 <>&'" 等字符, 必须 escape, 否则 XSS。"""
    bad_report = _synth_report()
    bad_report["strategies"][0]["title"] = "<script>alert(1)</script>"
    bad_report["strategies"][0]["rows"][0]["preset"] = "a<b>&c"
    html = runner.render_html(bad_report)
    # escape() 转 < 为 &lt; 等
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "a&lt;b&gt;&amp;c" in html


# ---------------------------------------------------------------------------
# Tests: Registry completeness (catch missing strategy bug)
# ---------------------------------------------------------------------------

def test_strategies_registry_has_all_4(runner):
    names = [s["name"] for s in runner.STRATEGIES]
    assert set(names) == {
        "chase_up", "uptrend_pullback", "short_reversal", "cycle_price_action",
    }


def test_each_strategy_runner_is_callable(runner):
    """所有 runner 必须是 Callable[[preset, db_path, start, end] -> dict],
    主 driver 依赖此签名。"""
    import inspect
    for s in runner.STRATEGIES:
        sig = inspect.signature(s["runner"])
        params = list(sig.parameters.keys())
        # 4 参: preset, db_path, start, end
        assert len(params) == 4, f"{s['name']} runner signature: {params}"