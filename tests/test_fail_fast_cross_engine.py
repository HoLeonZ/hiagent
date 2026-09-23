"""§0 Fail-Fast cross-engine production hot path audit (Tick 44).

CLAUDE.md §0 (verbatim):
  "Pessimistic Default: Always assume the worst-case scenario for market
   liquidity, execution price, and statistical significance.
   Fail-Fast: If a state transition violates physical market laws, throw
   an exception immediately. Do not silently bypass."

**核心发现 (FRESH 2026-09-23):**

A. **Production hot path fail-fast violations** (4 engines):

   **chase_up**:
   - `chase_up/sweep.py:100` — sweep loop:
     ```python
     except Exception as e:
         print(f"  [{done}/{total}] tp={tp_m} sl={sl_m} mh={mh}: FAILED {e}")
         rows.append({...})  # 失败被记为行, 静默吞掉
     ```
     Violation: per-preset failure silently recorded as data row.

   - `chase_up/sweep_all.py:79` — sweep variant:
     `# noqa: BLE001 — 跑批需要继续推进`
     Violation: acknowledged batch pattern, but per CLAUDE.md §0 strict
     reading this still bypasses physical-market-law exceptions.

   - `chase_up/wf_sweep_all.py:91` — WFV sweep:
     Same `# noqa: BLE001` pattern.

   **uptrend_pullback**:
   - `uptrend_pullback/grid.py:106` — grid sweep loop:
     ```python
     except Exception as e:
         logger.warning("窗口 %s..%s 跳过: %s", start, end, e)
         continue
     ```
     Violation: WFV window failure silently skipped, no upstream indicator.

   - `uptrend_pullback/walkforward.py:66` — WFV:
     `except Exception as e:  # 数据不足的早期年份`
     Acknowledged: data-insufficient early years, but same bypass pattern.

   - `uptrend_pullback/bt_compare_presets.py:149` — comparison tool.

   **short_reversal**:
   - `short_reversal/scan_signals.py:127` — signal scan hot path:
     ```python
     except Exception as e:
         print(f"WARN {code}: cerebro.run failed: {e}")
         continue
     ```
     **Worst offender** — affects ALL backtests because scan_signals
     produces the input signal set. Per-stock failure silently skipped.

   - `short_reversal/grid_runner.py:59` — IS-grid sweep loop:
     Same pattern as uptrend_pullback/grid.py:106.

   - `short_reversal/st_filter.py:49, 54` — ST filter scan:
     Multiple `except Exception + continue` patterns.

   **cycle_price_action**:
   - `cycle_price_action/backtest.py:86` — already covered in
     test_cycle_backtest_fail_fast.py (Tick 32, 2 RED).

B. **Why this matters**:
   - short_reversal/scan_signals.py:127: per-stock failure → signal set
     silently loses that stock → backtest results may be biased
     (cherry-picking stocks that don't crash)
   - chase_up/sweep.py:100: per-preset failure → sweep picks the
     next "best" preset which may be a failure-record dressed as data
   - uptrend_pullback/grid.py:106: WFV window lost → walkforward
     validation has silent holes

C. **Acceptable patterns** (explicit acknowledgment):
   - `# noqa: BLE001 — 跑批需要继续推进` (chase_up sweep_all + wf_sweep_all)
     — design decision documented in code
   - `# 数据不足的早期年份` (uptrend_pullback walkforward) — data edge
     case, but still bypasses §0 strict reading

本文件验证:
- 4 RED: hot-path silent fail-fast violations across 4 engines
- 2 PASS baseline: cycle_price_action/backtest.py:86 already covered by
  Tick 32 RED + acknowledged `# noqa: BLE001` batch patterns documented
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# RED: silent except/continue in production hot paths
# ---------------------------------------------------------------------------


def test_short_reversal_scan_signals_has_silent_fail_fast() -> None:
    """§0 RED: short_reversal/scan_signals.py:127 has silent except/continue.

    scan_signals is the signal generation hot path — affects ALL backtests.
    Per-stock failure silently skipped = cherry-picking stable stocks,
    biasing backtest results.
    """
    src = Path("short_reversal/scan_signals.py").read_text(encoding="utf-8")

    # Look for the silent pattern: except Exception as e: ... continue
    # within 5 lines after
    silent_pattern = re.search(
        r"except\s+Exception(?:\s+as\s+\w+)?\s*:\s*\n"
        r"(?:\s*(?:print|logger|#)[^\n]*\n){0,3}"
        r"\s*continue",
        src,
        re.MULTILINE,
    )

    if not silent_pattern:
        return  # GREEN, pattern not found

    raise AssertionError(
        "GAP CAPTURED (RED): short_reversal/scan_signals.py has silent "
        "except/continue pattern (line ~127): per-stock failure silently "
        "skipped in signal scan hot path. §0 Fail-Fast violation — "
        "exception MUST propagate or be flagged loudly, not silently "
        "bypassed. Worst offender because scan_signals affects ALL "
        "backtests via signal-set cherry-picking.\n"
        "GREEN fix: replace `continue` with `raise` (strict) OR log to "
        "structured failure channel (lenient, with upstream metric) — "
        "current pattern silently hides stock-level crashes."
    )


def test_chase_up_sweep_has_silent_fail_fast() -> None:
    """§0 RED: chase_up/sweep.py:100 silently records failure as data row.

    `rows.append({...})` after `except Exception as e` dresses the
    failure as a regular sweep result row. Downstream aggregation
    cannot distinguish real results from failure records.
    """
    src = Path("chase_up/sweep.py").read_text(encoding="utf-8")

    # Find `except Exception` followed by `rows.append` within 5 lines
    silent_pattern = re.search(
        r"except\s+Exception(?:\s+as\s+\w+)?\s*:\s*\n"
        r"(?:\s*(?:print|logger|#)[^\n]*\n){0,3}"
        r"\s*rows\.append",
        src,
        re.MULTILINE,
    )

    if not silent_pattern:
        return  # GREEN

    raise AssertionError(
        "GAP CAPTURED (RED): chase_up/sweep.py:100 has `except Exception` "
        "followed by `rows.append({...})` — per-preset failure silently "
        "recorded as data row in sweep results. Downstream aggregation "
        "treats failure as regular result, biasing sweep metrics.\n"
        "§0 Fail-Fast violation — failures must be flagged in a separate "
        "failure column (`status='failed'`) or raise immediately.\n"
        "GREEN fix: change `rows.append({...})` to either:\n"
        "  (a) raise (strict), or\n"
        "  (b) append to `failed_rows` list with status='failed' marker\n"
        "    so sweep.csv has explicit failure visibility."
    )


def test_uptrend_pullback_grid_has_silent_fail_fast() -> None:
    """§0 RED: uptrend_pullback/grid.py:106 silently skips WFV window.

    Per-window failure → window lost from walkforward validation.
    WFV rigor silently degrades (a 5-fold WFV may become 4-fold).
    """
    src = Path("uptrend_pullback/grid.py").read_text(encoding="utf-8")

    silent_pattern = re.search(
        r"except\s+Exception(?:\s+as\s+\w+)?\s*:\s*\n"
        r"(?:\s*(?:print|logger|warn)[^\n]*\n){0,3}"
        r"\s*continue",
        src,
        re.MULTILINE,
    )

    if not silent_pattern:
        return  # GREEN

    raise AssertionError(
        "GAP CAPTURED (RED): uptrend_pullback/grid.py:106 has silent "
        "except/continue pattern in WFV window loop. §0 Fail-Fast "
        "violation — WFV window failure should propagate or be tracked "
        "in window_status column. Silent skip means walkforward "
        "validation has hidden holes.\n"
        "GREEN fix: log to failures channel + track `n_windows_failed` "
        "metric; assert `n_windows_total == n_windows_passed + n_failed`."
    )


def test_short_reversal_grid_runner_has_silent_fail_fast() -> None:
    """§0 RED: short_reversal/grid_runner.py:59 silent except/continue.

    Combined with §5 IS-grid violation (30 trials, 0 DSR), this means
    failed grid trials are silently skipped AND best parameters chosen
    from incomplete trial set — double statistical compromise.
    """
    src = Path("short_reversal/grid_runner.py").read_text(encoding="utf-8")

    silent_pattern = re.search(
        r"except\s+Exception(?:\s+as\s+\w+)?\s*:\s*\n"
        r"(?:\s*(?:print|logger|warn|rows\.append|failures)[^\n]*\n){0,5}"
        r"\s*continue",
        src,
        re.MULTILINE,
    )

    if not silent_pattern:
        return  # GREEN

    raise AssertionError(
        "GAP CAPTURED (RED): short_reversal/grid_runner.py:59 has silent "
        "except/continue pattern in IS grid sweep. Combined with §5 "
        "IS-grid violation (no WFV, no DSR), per-trial failure "
        "silently skipped means best parameters chosen from "
        "incomplete trial set.\n"
        "GREEN fix: track `n_trials_total`, `n_trials_passed`, "
        "`n_trials_failed` columns; assert 100% pass rate or raise."
    )


# ---------------------------------------------------------------------------
# PASS baselines: existing fail-fast coverage + acknowledged batch patterns
# ---------------------------------------------------------------------------


def test_cycle_backtest_fail_fast_already_covered() -> None:
    """§0 PASS baseline: cycle_price_action/backtest.py:86 covered by Tick 32.

    test_cycle_backtest_fail_fast.py has 2 RED tests targeting
    `except Exception ... continue` at cycle_price_action/backtest.py:86.
    Pin this coverage to prevent regression.
    """
    try:
        mod = importlib.import_module("tests.test_cycle_backtest_fail_fast")
        assert hasattr(mod, "test_run_backtest_no_bare_continue_in_hot_path"), (
            "Regression: test_cycle_backtest_fail_fast.py lost "
            "test_run_backtest_no_bare_continue_in_hot_path"
        )
    except (ImportError, ModuleNotFoundError):
        # Test module not in standard import path; verify file exists
        path = Path("tests/test_cycle_backtest_fail_fast.py")
        if path.exists():
            return
        raise AssertionError(
            "Regression: tests/test_cycle_backtest_fail_fast.py missing"
        )


def test_acknowledged_batch_patterns_have_noqa_comment() -> None:
    """§0 PASS baseline: explicit `# noqa: BLE001 — 跑批需要继续推进` patterns.

    chase_up/sweep_all.py:79 and chase_up/wf_sweep_all.py:91 use
    explicit `# noqa: BLE001` with documented reason. While still
    fails the strict §0 reading, the documented acknowledgment is
    a 'least-bad' pattern compared to silent bypass.

    Pin these so future batch patterns follow same documentation
    discipline.
    """
    sweep_all_src = Path("chase_up/sweep_all.py").read_text(encoding="utf-8")
    wf_sweep_all_src = Path("chase_up/wf_sweep_all.py").read_text(
        encoding="utf-8"
    )

    assert "noqa: BLE001" in sweep_all_src, (
        "Regression: chase_up/sweep_all.py no longer has documented "
        "# noqa: BLE001 comment for batch pattern"
    )
    assert "noqa: BLE001" in wf_sweep_all_src, (
        "Regression: chase_up/wf_sweep_all.py no longer has documented "
        "# noqa: BLE001 comment for batch pattern"
    )