"""Short_reversal 单轴 grid runner（不落 PRESETS，仅临时构造 cfg）。

用途：在 P3+P5 修复后的 v3 引擎上做参数 grid，对比 n / win% / CAGR / Sharpe / DD。
NOT 用于 production — 仅作为探索性研究脚本。lock-by-file-location 即可,
不污染 PRESETS。

CLAUDE.md §5 合规：sweep 末尾报告 DSR 校正多 trial selection bias。
对于生产环境的 walk-forward 验证 (OOS 训练/测试切分), 见
short_reversal.walkforward 或 core.walkforward.walkforward_windows。
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from short_reversal.engine import run_backtest_v3  # noqa: E402
from hiagent_config import DB_PATH as DEFAULT_DB  # noqa: E402
from dna_stats.deflated import deflated_sharpe_ratio  # noqa: E402
from core.cli_verdict import cli_verdict  # §0 结论落退出码 (附八十四)

START = "2025-09-12"
END = "2026-09-12"


def _run(cfg: dict, name: str) -> dict:
    """临时 monkey-patch PRESETS dict,跑一次 v3 引擎。"""
    from short_reversal import presets as _p

    _p.PRESETS[name] = cfg
    try:
        m = run_backtest_v3(name, START, END, DEFAULT_DB)
    finally:
        _p.PRESETS.pop(name, None)
    return m


def grid(axis: str, base: dict, values: list, base_name: str) -> list[dict]:
    rows = []
    for v in values:
        cfg = dict(base)
        if axis == "tp_pct":
            cfg["tp_pct"] = v
        elif axis == "sl_pct":
            cfg["sl_pct"] = v
        elif axis == "max_hold":
            cfg["max_hold"] = v
        elif axis == "pct_chg_low":
            cfg["pct_chg_low"] = v
        elif axis == "pct_chg_high":
            cfg["pct_chg_high"] = v
        elif axis == "a_condition":
            cfg["a_condition"] = v
        else:
            raise ValueError(axis)
        name = f"_grid_{base_name}_{axis}_{str(v).replace('.', '_')}"
        import time
        t0 = time.time()
        try:
            m = _run(cfg, name)
        except (duckdb.Error, ValueError, KeyError) as e:
            # §0 Fail-Fast narrowed: IS-grid sweep is exploratory; keep
            # warn + error row + continue. Only catch data-shape/lookup
            # exceptions; programming errors / MemoryError propagate.
            print(f"  [ERR] {axis}={v}: {e}", flush=True)
            rows.append({"axis": axis, "value": v, "error": str(e)[:60]})
            continue
        dt = time.time() - t0
        rows.append({
            "axis": axis,
            "value": v,
            "name": name,
            "n": m["trades_count"],
            # §5 (audit 2026-10-16): 随产物发布观测数 T —— 下面算 DSR 需要它,
            # 而它此前从不出现在落盘的 CSV 里(于是只能硬编码,见 DSR 调用处)。
            "n_trading_days": m["n_trading_days"],
            "win%": m["win_rate"] * 100,
            "CAGR%": m["cagr"] * 100,
            "Sharpe": m["sharpe"],
            "DD%": m["max_dd"] * 100,
            "TP/SL/T": f"{m['tp_count']}/{m['sl_count']}/{m['time_count']}",
        })
        print(f"  [{dt:>5.1f}s] {axis:>15}={str(v):<8} n={m['trades_count']:>4} "
              f"win={m['win_rate']*100:>5.1f}% CAGR={m['cagr']*100:>10.2f}% "
              f"Sharpe={m['sharpe']:>5.2f} DD={m['max_dd']*100:>5.1f}% "
              f"{m['tp_count']}/{m['sl_count']}/{m['time_count']}",
              flush=True)
    return rows


# §0/§2/§6 (附八十四): 两个 base 都**缺 `position_sizing`**,而这是引擎 preset 契约的
# **必填**字段(「没有声明」与「声明为合法值」必须可区分)⇒ 实测 **27/27 个配置全部被拒**,
# 脚本落一张空网格、退出 0(静默的零)。
# 取值 `"all_in"` 不是自由选择:CLAUDE.md §2 强制 strict all-in sizing
# (`position_fraction = 1.0`),且 short_reversal 的**每一个** preset 都声明 `"all_in"`。
#
# ⚠️ **仍未跑通,且这次是刻意停手的**:补上它之后下一个缺字段是
# `price_source_for_execution`(再下一个还不知道)—— 打地鼠。而补全它需要选一个
# **§3 口径**(执行域取 raw 还是 adj),且这两个 base 的作者意图所指的 preset
# (`tp2_sl05_dneg` / `tp6_sl005_mh5_realistic`)在 `presets.py` 里**已不存在**
# ⇒ "这个网格应该建在哪个 preset 上"是**口径决策,不是缺陷**,已登记(见附八十四 §4)。
# 本节只做**契约那半**:脚本不再假装成功 —— 0/27 会以退出码 1 与 `[PARTIAL]` 结论收尾。
BASE_CONSERVATIVE = {
    "universe": "mainboard_only",
    "position_sizing": "all_in",
    "tp_pct": 0.02,
    "sl_pct": 0.005,
    "max_hold": 3,
}
BASE_AGGRESSIVE = {
    "universe": "mainboard_only",
    "position_sizing": "all_in",
    "tp_pct": 0.06,
    "sl_pct": 0.0005,
    "max_hold": 5,
    "pct_chg_low": 0.02,
    "pct_chg_high": 0.07,
}


def main():
    out_dir = Path("short_reversal/results/grid")
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=== CONSERVATIVE (tp2_sl05_dneg) GRID ===", flush=True)
    all_rows = []
    axes = {
        "tp_pct": [0.015, 0.020, 0.025, 0.030],
        "sl_pct": [0.003, 0.005, 0.007],
        "max_hold": [2, 3, 4],
        "pct_chg_high": [0.05, 0.07, 0.10],
    }
    for ax, vals in axes.items():
        rows = grid(ax, BASE_CONSERVATIVE, vals, "cons")
        all_rows.extend(rows)

    print()
    print("=== AGGRESSIVE (tp6_sl005_mh5_realistic) GRID ===", flush=True)
    axes_a = {
        "tp_pct": [0.05, 0.06, 0.07, 0.08],
        "sl_pct": [0.0003, 0.0005, 0.0008],
        "max_hold": [4, 5, 6, 7],
        "pct_chg_low": [0.015, 0.02, 0.025],
    }
    for ax, vals in axes_a.items():
        rows = grid(ax, BASE_AGGRESSIVE, vals, "agg")
        all_rows.extend(rows)

    csv_path = out_dir / "grid_v3_p3p5fix.csv"
    with open(csv_path, "w", newline="") as f:
        # §0 (附八十四): `fieldnames` 里**漏了 `n_trading_days`**,而成功行带着它
        # (上面 `grid()` 落的行、以及附六十 起为取 T 而发布的字段)。
        # `csv.DictWriter` 默认 `extrasaction="raise"` ⇒ **只要有任何一个配置成功,
        # 写第一行就抛 ValueError**。它能"跑完"纯粹因为 27/27 都失败(失败行只有 3 个键)
        # —— 一个缺陷被另一个缺陷掩盖了。行 schema 与写出器必须一致。
        w = csv.DictWriter(f, fieldnames=["axis", "value", "name", "n", "n_trading_days",
                                          "win%", "CAGR%", "Sharpe", "DD%", "TP/SL/T",
                                          "error"])
        w.writeheader()
        for r in all_rows:
            w.writerow(r)
    print(f"\n→ 落盘 {csv_path}")

    # CLAUDE.md §5 Penalty Metrics: 多 trial grid 必须报告 DSR
    sharpes = [float(r["Sharpe"]) for r in all_rows
               if "Sharpe" in r and r.get("error") is None]
    if sharpes:
        observed = max(sharpes)
        # §5 (audit 2026-10-16): `n_returns` 是"Sharpe 用了多少个收益观测"(T),
        # 此前硬编码 252。本窗口实际只有 242 个交易日 ⇒ T 被高估 4.1%,
        # 标准误被低估约 2%,DSR 系统性偏乐观 —— 而 §5 的惩罚指标恰恰要用在
        # "看起来不错"的结果上。改为取本次运行的真实交易日数(引擎随 metrics 发布);
        # **缺它就 fail-fast**,不再用 252 兜底(兜底值正是这个缺陷的形态)。
        n_obs = max((int(r["n_trading_days"]) for r in all_rows if "n_trading_days" in r),
                    default=0)
        if n_obs < 2:
            raise ValueError(
                "§5: 无法取得观测数 T(metrics 缺 n_trading_days)—— "
                "不许用常数兜底,那正是本项要修的缺陷"
            )
        # §5 (附八十二): `n_trials` 是"**试过多少个配置**",不是"有多少个配置跑成功了"。
        # `grid()` 对每个取值都 append 一行(失败的那行只有 `error`)⇒ 上面用
        # `r.get("error") is None` 过滤掉失败行 ⇒ **n_trials 少计、DSR 偏乐观**。
        # §5 Iterative-Tuning Accounting:"每一次迭代都计入" —— 崩掉的那次也是迭代。
        _n_tried = int(len(all_rows))
        _n_ok = int(len(sharpes))
        dsr = deflated_sharpe_ratio(
            observed_sharpe=observed, n_trials=_n_tried, n_returns=n_obs,
        )
        print(
            f"\n§5 DSR | observed_sharpe={observed:.3f} | "
            f"n_trials={_n_tried} | "
            f"deflated_sharpe={dsr['deflated_sharpe']:.3f} | "
            f"expected_max={dsr['expected_max_sharpe']:.3f} | "
            f"p_value={dsr['dsr_p_value']:.4f}"
        )
        if _n_tried != _n_ok:
            print(
                f"  ⚠️ 其中 {_n_tried - _n_ok} 个配置**抛异常**(见 CSV 的 `error` 列)"
                f"—— 它们同样计入 n_trials(§5:每次迭代都算)"
            )

    # §0 (附八十四): 结论必须落在**退出码**上。
    # 实测:本脚本的 base 配置缺 `position_sizing` ⇒ **27/27 个配置全部被引擎的
    # preset 契约 fail-fast 拒绝** ⇒ 落一张空网格、一个 DSR 都不打、**退出码 0**。
    # 这是"静默的零",正是 `core.cli_verdict` 当初为另外四个工具建的场景。
    _failures = sum(1 for r in all_rows if r.get("error") is not None)
    _attempted = len(all_rows)
    _code, _msg = cli_verdict(
        failures=_failures, attempted=_attempted,
        succeeded=_attempted - _failures, what="grid_runner 的配置",
    )
    print(f"\n{_msg}")
    return _code


if __name__ == "__main__":
    sys.exit(main())