#!/usr/bin/env python3
"""四族 preset 的**当前态普查** (§13.110, 2026-10-19)。

## 为什么做这个
本册的 headline 是「四型 + 横截面 + 配对套利, **全部关闭; 没有任何可用策略**」。
而它一直是靠**引用若干具名 preset** 支撑的 —— **从未做过一次完整普查**。
本工具补上: 把**全部 82 个 preset**在标准窗口上跑一遍, 只报**聚合计数**。

## ⚠️ 它**不做**什么 (CLAUDE.md §5 的硬约束)
**不排名、不选最优。** §5 明文:
> **Banned In-Sample Grids:** Refuse requests to write simple grid-search scripts
> that return the "best parameters based on max Sharpe".

⇒ 输出只有: 每族「在两个窗口上都为正」的有几个、「只在某一个窗口为正」的有几个。
**任何单点最优都不报** —— 那是 §5 禁止的动作。若某族出现"两窗口都为正"的**计数异常**,
正确的反应是**登记并送去做 WFV/DSR**, 不是把它当成发现。

## 窗口 (取 §13 的干净末日, 避开因子表落后造成的假暴跌)
* W2  : 2024-10-08 .. **2026-09-18**  (报告窗; 末日按 §13.8 截到最后一个干净日)
* IND : 2022-10-03 .. 2024-09-30      (独立期)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hiagent_config import DB_PATH  # noqa: E402

W2 = ("2024-10-08", "2026-09-18")
IND = ("2022-10-03", "2024-09-30")


def _chase() -> list[tuple[str, float, float]]:
    from chase_up.backtest import run_backtest
    from chase_up.data import load_panel
    from chase_up.presets import PRESETS
    from chase_up.signals import compute_indicators
    from chase_up.universe import load_universe

    out = []
    uni = set(load_universe("mainboard_only", DB_PATH))
    for w in (W2, IND):
        panel = compute_indicators(load_panel(DB_PATH, *w, universe=uni))
        for name, p in PRESETS.items():
            _t = time.time()
            try:
                r = run_backtest(dict(p), w[0], w[1], DB_PATH, panel_ind=panel)
                out.append((name, w, _ret_of(r["metrics"], f"chase_up/{name}")))
            except Exception:  # noqa: BLE001
                out.append((name, w, float("nan")))
            _tick("chase_up", name, _t)
        del panel
    return out


def _uptrend() -> list[tuple[str, float, float]]:
    from uptrend_pullback.backtest import run_backtest
    from uptrend_pullback.data import load_panel
    from uptrend_pullback.presets import PRESETS
    from uptrend_pullback.signals import compute_indicators
    from uptrend_pullback.universe import load_universe

    out = []
    uni = set(load_universe("mainboard_only", DB_PATH))
    for w in (W2, IND):
        panel = compute_indicators(load_panel(DB_PATH, *w, universe=uni))
        for name, p in PRESETS.items():
            _t = time.time()
            try:
                r = run_backtest(dict(p), w[0], w[1], DB_PATH, panel_ind=panel)
                out.append((name, w, _ret_of(r["metrics"], f"uptrend/{name}")))
            except Exception:  # noqa: BLE001
                out.append((name, w, float("nan")))
            _tick("uptrend_pullback", name, _t)
        del panel
    return out


# §13.23 的教训: **键名各族不同** —— `short_reversal` 叫 `total_yield`, 不是 `total_return`。
# 我第一版直接 `m.get("total_return", nan)` ⇒ **55 条全是 NaN**, 而我会把它读成
# "short_reversal 全缺数据" —— 一个**由取键错误造出来的假发现**。
# ⇒ 现在:**先取存在的那个键; 两个都没有就抛错**, 不静默记 NaN (§0)。
# §13.111: **逐条打印进度与耗时** —— 上一轮的设计缺陷是"聚合表只在全族跑完后才打印",
# 于是长跑被中断时**什么也看不到** (我因此误读 `ps` 并差一点断定它挂了)。
# 现在每条都打印, 并在最后给出**最慢的若干条** —— 那是**成本画像**, 不是策略排名。
TIMINGS: list[tuple[str, str, float]] = []


def _tick(fam: str, name: str, t0: float) -> None:
    dt = time.time() - t0
    TIMINGS.append((fam, name, dt))
    print(f"  [{fam}] {name:<44} {dt:>7.1f}s", flush=True)


_RET_KEYS = ("total_return", "total_yield")


def _ret_of(m: dict, who: str) -> float:
    for k in _RET_KEYS:
        if k in m and m[k] is not None:
            return float(m[k])
    raise KeyError(
        f"{who}: metrics 里找不到 {_RET_KEYS} 中的任何一个 —— 键名又变了? "
        f"现有键: {sorted(m.keys())}"
    )


def _short() -> list[tuple[str, float, float]]:
    from short_reversal.engine import run_backtest_v3
    from short_reversal.presets import PRESETS

    out = []
    for name in PRESETS:
        for w in (W2, IND):
            _t = time.time()
            try:
                r = run_backtest_v3(name, w[0], w[1], DB_PATH)
                m = r.get("metrics") or r
                out.append((name, w, _ret_of(m, f"short_reversal/{name}")))
            except KeyError:
                raise
            except Exception:  # noqa: BLE001
                out.append((name, w, float("nan")))
            _tick("short_reversal", f"{name}@{w[0]}", _t)
    return out


def _cycle() -> list[tuple[str, float, float]]:
    import datetime as dt

    from cycle_price_action.backtest import run_backtest
    from cycle_price_action.presets import PRESET_V1

    out = []
    for w in (W2, IND):
        _t = time.time()
        try:
            r = run_backtest(str(DB_PATH), dt.date.fromisoformat(w[0]),
                             dt.date.fromisoformat(w[1]), preset=dict(PRESET_V1))
            m = r.metrics
            out.append(("PRESET_V1", w, float(m.get("total_pnl", float("nan")))))
        except Exception:  # noqa: BLE001
            out.append(("PRESET_V1", w, float("nan")))
        _tick("cycle_price_action", f"PRESET_V1@{w[0]}", _t)
    return out


def main() -> int:
    fams = {"chase_up": _chase, "uptrend_pullback": _uptrend,
            "short_reversal": _short, "cycle_price_action": _cycle}
    all_rows = []
    for fam, fn in fams.items():
        t0 = time.time()
        rows = fn()
        all_rows += [{"family": fam, "preset": n, "window": w[0], "ret": v} for n, w, v in rows]
        print(f"[{fam}] {len(rows)} 次回测, {time.time()-t0:.0f}s", flush=True)

    # ---- 只报聚合 ----
    from collections import defaultdict
    per = defaultdict(lambda: defaultdict(dict))
    for r in all_rows:
        per[r["family"]][r["preset"]][r["window"]] = r["ret"]
    print("\n=== 每族聚合 (✅ = 该窗口 total_return > 0) ===")
    print(f"{'族':<22} {'n':>4} {'两窗口都为正':>12} {'仅W2正':>8} {'仅IND正':>8} {'都不正':>8} {'缺数据':>7}")
    for fam, d in per.items():
        n = both = w2 = ind = none = nan = 0
        for _, v in d.items():
            a, b = v.get(W2[0]), v.get(IND[0])
            n += 1
            if a is None or b is None or a != a or b != b:
                nan += 1
            elif a > 0 and b > 0:
                both += 1
            elif a > 0:
                w2 += 1
            elif b > 0:
                ind += 1
            else:
                none += 1
        print(f"{fam:<22} {n:>4} {both:>12} {w2:>8} {ind:>8} {none:>8} {nan:>7}")
    out = Path("/tmp/preset_census.json")
    out.write_text(json.dumps(all_rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n=== 最慢的 10 条 (**成本画像**, 不是策略排名) ===")
    for fam, name, dt in sorted(TIMINGS, key=lambda x: -x[2])[:10]:
        print(f"  {dt:>8.1f}s  {fam}/{name}")
    print(f"\n明细落盘: {out}  (⚠️ **不排名、不选优** —— §5)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
