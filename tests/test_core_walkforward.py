"""core.walkforward 共用 WFV 窗口生成器契约 (CLAUDE.md §5 + 4-engine 共享目标).

锁定 4 engine (chase_up / uptrend_pullback / short_reversal / cycle_price_action)
共用同一份 walkforward 窗口生成代码:
  - `WalkForwardWindow`: train_start / train_end / test_start / test_end
  - `walkforward_windows()`: train/test split windows (cycle_price_action 风格)
  - `monthly_windows()`: 滚动单窗口 (chase_up + uptrend_pullback 同构)
  - `yearly_windows()`: 逐年窗口 (uptrend_pullback 风格)

任何 engine 改写本地副本必须 FAIL 此测试。
"""
from __future__ import annotations

from datetime import date

import pytest


# ============================================================ RED: 共享 API 契约

class TestCoreWalkforwardSharedAPI:
    """core.walkforward 必须暴露 4-engine 共用 API."""

    def test_walkforward_window_dataclass(self):
        """WalkForwardWindow 4 字段: train_start/train_end/test_start/test_end."""
        from core.walkforward import WalkForwardWindow

        w = WalkForwardWindow(
            train_start=date(2020, 1, 1),
            train_end=date(2020, 12, 31),
            test_start=date(2021, 1, 1),
            test_end=date(2021, 12, 31),
        )
        assert w.train_start == date(2020, 1, 1)
        assert w.train_end == date(2020, 12, 31)
        assert w.test_start == date(2021, 1, 1)
        assert w.test_end == date(2021, 12, 31)
        # frozen dataclass
        with pytest.raises((AttributeError, TypeError)):
            w.train_start = date(2025, 1, 1)  # type: ignore

    def test_walkforward_windows_basic(self):
        """walkforward_windows 生成 train/test split 窗口."""
        from core.walkforward import walkforward_windows

        windows = walkforward_windows(
            start=date(2020, 1, 1),
            end=date(2024, 1, 1),
            train_months=12,
            test_months=12,
            roll_months=6,
        )
        assert len(windows) >= 4
        for w in windows:
            assert w.train_end < w.test_start
            assert w.test_start <= w.test_end

    def test_walkforward_windows_rejects_short_horizon(self):
        """horizon < train+test months → ValueError."""
        from core.walkforward import walkforward_windows

        with pytest.raises(ValueError):
            walkforward_windows(
                start=date(2024, 1, 1),
                end=date(2024, 6, 1),
                train_months=12,
                test_months=12,
            )

    def test_monthly_windows_basic(self):
        """monthly_windows 生成月级滚动 (chase_up + uptrend_pullback 同构)."""
        from core.walkforward import monthly_windows

        windows = monthly_windows(
            start_month="2020-01",
            end_month="2021-01",
            window_months=3,
            step_months=0,
        )
        # 2020-01..2020-04, 2020-04..2020-07, 2020-07..2020-10, 2020-10..2021-01
        assert len(windows) == 4
        assert windows[0] == ("2020-01-01", "2020-04-01")
        assert windows[1] == ("2020-04-01", "2020-07-01")
        assert windows[2] == ("2020-07-01", "2020-10-01")
        assert windows[3] == ("2020-10-01", "2021-01-01")

    def test_monthly_windows_step_overlap(self):
        """step_months < window_months → 重叠窗 (rolling)."""
        from core.walkforward import monthly_windows

        windows = monthly_windows(
            start_month="2020-01",
            end_month="2020-07",
            window_months=3,
            step_months=1,  # 重叠 2m
        )
        # 2020-01..04, 2020-02..05, 2020-03..06, 2020-04..07 → 4 窗 (end 2020-08 越界)
        assert len(windows) == 4
        assert windows[0] == ("2020-01-01", "2020-04-01")
        assert windows[-1] == ("2020-04-01", "2020-07-01")

    def test_yearly_windows_basic(self):
        """yearly_windows 生成逐年窗口."""
        from core.walkforward import yearly_windows

        windows = yearly_windows(first_year=2020, last_year=2023, month_day="09-08")
        assert windows == [
            ("2020-09-08", "2021-09-08"),
            ("2021-09-08", "2022-09-08"),
            ("2022-09-08", "2023-09-08"),
        ]


# ============================================================ GREEN: 4-engine 复用契约

class TestWalkforwardEngineReuse:
    """4 engine 必须从 core.walkforward import, 不重复实现.

    任何 engine 重新实现 walkforward_windows / monthly_windows / yearly_windows
    必须 FAIL 此测试 — 强制共用同一份代码。
    """

    @pytest.mark.parametrize("engine_module", [
        "chase_up.walkforward",
        "uptrend_pullback.walkforward",
        "cycle_price_action.walkforward",
    ])
    def test_engine_re_exports_from_core(self, engine_module):
        """每个 engine 的 walkforward.py 必须 import 自 core.walkforward."""
        import importlib
        import inspect

        mod = importlib.import_module(engine_module)
        source = inspect.getsource(mod)
        assert "from core.walkforward" in source or "import core.walkforward" in source, (
            f"{engine_module} 没引用 core.walkforward"
        )

    def test_chase_up_monthly_windows_equivalent_to_core(self):
        """chase_up.monthly_windows 必须 ≡ core.monthly_windows."""
        from core.walkforward import monthly_windows as core_fn
        from chase_up.walkforward import monthly_windows as chase_fn

        ref = core_fn("2020-01", "2020-07", window_months=3, step_months=1)
        # 验证 chase_fn 行为一致 (re-export 同一函数对象或等效实现)
        assert chase_fn("2020-01", "2020-07", window_months=3, step_months=1) == ref

    def test_uptrend_pullback_monthly_windows_equivalent_to_core(self):
        """uptrend_pullback.monthly_windows 必须 ≡ core.monthly_windows."""
        from core.walkforward import monthly_windows as core_fn
        from uptrend_pullback.walkforward import monthly_windows as up_fn

        ref = core_fn("2020-01", "2020-07", window_months=3, step_months=1)
        assert up_fn("2020-01", "2020-07", window_months=3, step_months=1) == ref


# ============================================================ Layout 锁定 (CLAUDE.md §5)

class TestWalkforwardContractPinning:
    """CLAUDE.md §5 铁律: 必须支持 train/test split (out-of-sample 测试).

    simple grid-search 找 max Sharpe 是 banned; 必须 WFV。
    """

    def test_walkforward_windows_enforces_oos_test_window(self):
        """每个 window 的 train_end < test_start (无 sample overlap)."""
        from core.walkforward import walkforward_windows

        windows = walkforward_windows(
            start=date(2020, 1, 1),
            end=date(2023, 1, 1),
            train_months=6,
            test_months=3,
            roll_months=3,
        )
        for w in windows:
            assert w.train_end < w.test_start, (
                f"WFV out-of-sample 违反: train_end={w.train_end} ≥ test_start={w.test_start}"
            )
            # 进一步: train 段和 test 段完全不重叠
            assert w.train_start <= w.train_end
            assert w.test_start <= w.test_end