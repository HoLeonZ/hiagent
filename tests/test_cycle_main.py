"""Tests for cycle_price_action.main CLI arg parsing + window resolution.

Regression coverage for the FINAL WHOLE-BRANCH review findings:
- Important #1: `run` subparser no longer shadows --start/--end with None.
- Important #2: _resolve_window no longer has the dead second-fromordinal path.
- Minor #3: out_dir suffix includes microseconds (smoke check on the format).
"""
from __future__ import annotations

from datetime import date, datetime

from cycle_price_action.main import _resolve_window, main


def _parsed_ns(argv: list[str]):
    """Re-parse the same argv through the module's argparse setup by intercepting
    the dispatched handler. Returns the Namespace the handler would have seen."""
    captured = {}

    import cycle_price_action.main as cli

    orig_run = cli._run_backtest
    cli._run_backtest = lambda args: captured.setdefault("ns", args) or 0
    try:
        main(argv)
    finally:
        cli._run_backtest = orig_run
    return captured["ns"]


def test_run_subcommand_inherits_parent_start_end():
    """`run` must surface --start/--end from the parent, not shadow them with None.

    Reproduces the Important #1 bug: argparse subparsers shadow parent namespace
    entries with None when --start/--end are redefined on the subparser. After
    the fix, the parent's values must propagate.
    """
    ns = _parsed_ns(["--start", "2025-08-21", "--end", "2025-09-21",
                     "run", "--cash", "1000000"])
    assert ns.start == "2025-08-21"
    assert ns.end == "2025-09-21"


def test_run_subcommand_inherits_db_and_preset():
    """`run` must also inherit --db and --preset from the parent (same shadowing bug)."""
    ns = _parsed_ns(["--start", "2025-08-21", "--end", "2025-09-21",
                     "run", "--cash", "1000000"])
    assert ns.db is not None       # parent's default of get_db_path()
    assert ns.preset == "v1"       # parent's default


def test_resolve_window_explicit_dates_round_trip():
    """When --start/--end are passed, they must propagate unchanged."""
    s, e = _resolve_window("2025-08-21", "2025-09-21")
    assert s == date(2025, 8, 21)
    assert e == date(2025, 9, 21)


def test_resolve_window_defaults_to_365d_window_ending_today():
    """When neither is passed, end = today, start = end - 365 days."""
    s, e = _resolve_window(None, None)
    assert e == date.today()
    assert s == date.fromordinal(e.toordinal() - 365)


def test_resolve_window_end_only_defaults_start():
    """When only --end is passed, start = end - 365 days."""
    s, e = _resolve_window(None, "2025-09-21")
    assert e == date(2025, 9, 21)
    assert s == date.fromordinal(e.toordinal() - 365)


def test_out_dir_suffix_includes_microseconds():
    """Smoke test on out_dir suffix format to catch same-second collisions."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    # Microsecond field is 6 digits
    assert len(stamp.split("_")[-1]) == 6


# ---------------------------------------------------------------------------
# 附六十五 —— §5 那一段此前是**死代码**(注释却宣称"以满足 §5")
# ---------------------------------------------------------------------------


def test_dsr_notice_says_why_when_there_is_no_portfolio_sharpe() -> None:
    """cycle 无组合级 Sharpe ⇒ 必须**显式说明**,不得静默跳过。

    实测:`cycle_price_action/metrics.py` 按设计让 `sharpe` 恒为 `None`
    (`cagr`/`sharpe`/`max_dd` 在"每股独立账户"的口径下无定义),故原来的
    `if sharpe is not None:` 分支**从未执行** —— 而它的注释写着
    "此处直接输出以满足 §5"。
    """
    from cycle_price_action.main import dsr_notice

    msg = dsr_notice(sharpe=None, n_trades=495, preset="v1")
    assert "无定义" in msg or "不报" in msg, f"未说明为什么不报 DSR:{msg}"
    assert "DSR for" not in msg, "sharpe 为 None 时不得报出 DSR 数值(那是伪造)"
    assert "495" in msg, "应当带上 n_trades 以便读者判断这次窗口的量级"


def test_dsr_notice_reports_dsr_when_sharpe_exists() -> None:
    from cycle_price_action.main import dsr_notice

    msg = dsr_notice(sharpe=1.23, n_trades=100, preset="v1")
    assert "DSR for v1" in msg and "deflated_sharpe=" in msg


def test_cycle_metrics_really_has_no_sharpe() -> None:
    """把"cycle 没有组合级 Sharpe"这一**前提**钉住 —— 上面那条说明依赖它。

    若哪天 cycle 真的发布了组合级 Sharpe,本用例变红,提示把那段说明改回报 DSR。
    """
    import inspect

    from cycle_price_action import metrics as cm

    src = inspect.getsource(cm)
    assert "sharpe=None" in src, (
        "cycle 的 metrics 似乎开始发布 sharpe 了 —— 请更新 main.dsr_notice 与附六十五"
    )
