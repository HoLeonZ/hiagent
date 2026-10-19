"""§5 归因: `uptrend_pullback` 当前最优的**择优 (top-1 by mom120) 子集**有没有超额?

**为什么单独有这个脚本** (§6.3.2 自陈留下的缺口)
------------------------------------------------
§6.3.2 量的是**候选集平均**的前向超额 (≈0), 并在结尾明写:

    > 候选集里取极少数 (`max_positions=1`), **取哪一笔**由 `score = mom120` 决定;
    > 本节量的是**候选集平均**, 不是"择优后的子集"。
    > **择优能否改变结论属另一个问题。**

于是本册一直缺一个数: **择优本身**有没有正贡献。本脚本把它量出来, 并同时量出
**信号吃下率** (引擎实际吃下多少比例的触发) —— 后者决定这个问题的量级。

方法 (与 §6.3 的**同构造市场对照**一致)
----------------------------------------
* 对照: 同一 panel 的**等权主板**日频指数 (`close` 逐日等权平均收益累乘);
  "同构造"= 同宇宙、同窗口、同起止点 —— 否则对照本身有偏 (§6.3 的明文要求)。
* A 口径 (实际成交): 每一笔实际成交, 与**同起止日**的等权对照比 ⇒ 逐笔超额。
  用引擎真实出场规则 (TP/SL/time), 故这是"引擎真拿到的"超额。
* B 口径 (固定 h): 信号日上算未来 h 日收益, 减去**同日**等权对照 ⇒ 逐笔超额。
  分别在 (i) **择优 top-1** 与 (ii) **候选集全量** 上算, 两者**同口径可直接比**。
  h 取 3, 与实测均持仓 ~3.2 日一致。

⚠️ 口径说明
-----------
* 本脚本用 `shift(-h)` 只为**度量前向收益**, 不参与任何决策 —— §1 禁的是在
  特征/指标里用未来信息, 不是禁评估。
* 信号日 → 引擎实际在 **T+1** 入场; 本脚本从**信号日**起算 (与 §6.3.2 同),
  口径一致才可比。
* 成交腿的 `entry_price/exit_price` 是 **raw 执行价**, 对照用 **adj close** 收益;
  持有期通常 2–3 日且无权益事件 ⇒ 两者一致 (§3 双价格系统, 见 §13.114)。

用法 (数字 → 一条命令可重生成, 满足 §7):
    python3 tools/attribute_uptrend_selection.py                # 当前最优
    python3 tools/attribute_uptrend_selection.py --preset v33_long_reverse_v21
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hiagent_config import DB_PATH  # noqa: E402

from uptrend_pullback.backtest import run_backtest  # noqa: E402
from uptrend_pullback.data import load_panel  # noqa: E402
from uptrend_pullback.presets import get_preset  # noqa: E402
from uptrend_pullback.regime import compute_regime  # noqa: E402
from uptrend_pullback.signals import compute_indicators, select_entries  # noqa: E402
from uptrend_pullback.universe import load_universe  # noqa: E402

DEFAULT_PRESET = "v33_long_reverse_v22"
H = 3
# 末窗末日按 §13.8 截到最后一个**干净日** (因子表止于 2026-09-18)
WINDOWS: tuple[tuple[str, str, str], ...] = (
    ("W2", "2024-10-08", "2026-09-18"),
    ("IND", "2022-10-03", "2024-09-30"),
    ("IS1", "2021-10-01", "2022-09-30"),
    ("IS2", "2023-10-01", "2024-09-30"),
)


def _tstat(x: np.ndarray) -> tuple[float, int]:
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) < 2:
        return float("nan"), 0
    return float(np.mean(x) / (np.std(x, ddof=1) / np.sqrt(len(x)))), len(x)


def _select_fn(preset: dict):
    """信号选择器 —— 与 `backtest.run_backtest` 的分支**同源**, 避免口径分叉。"""
    if preset["signal"].get("entry_mode") == "v33_long_mirror":
        from uptrend_pullback.signals import select_entries_v33_long_mirror
        return select_entries_v33_long_mirror
    return select_entries


def _one_window(preset: dict, w0: str, w1: str) -> dict:
    p = preset
    # 单一来源: 建 panel 的 PIT 口径只在 `_panel` 里写一次 (A/B 与主口径共用)
    panel, _ = _panel(p, w0, w1, pit=True)

    res = run_backtest(p, w0, w1, DB_PATH, panel_ind=panel)
    trades, m = res["trades"], res["metrics"]

    # 等权主板日频指数 (同宇宙/同窗口)
    px = panel.pivot_table(index="date", columns="thscode", values="close")
    ew = (1.0 + px.pct_change().mean(axis=1).fillna(0.0)).cumprod()

    # ---- A: 实际成交, 与同起止日的等权对照比 ----
    exc_a, gross_a = [], []
    for _, r in trades.iterrows():
        d0, d1 = pd.Timestamp(r["entry_date"]), pd.Timestamp(r["exit_date"])
        if d0 not in ew.index or d1 not in ew.index:
            continue
        gross = r["exit_price"] / r["entry_price"] - 1.0
        gross_a.append(gross)
        exc_a.append(gross - (ew[d1] / ew[d0] - 1.0))

    # ---- B: 固定 h 的前向超额, 择优 vs 候选集全量 ----
    reg = compute_regime(panel, **p["regime"]) if p.get("regime") else None
    kwargs = {k: v for k, v in p["signal"].items() if k != "entry_mode"}
    entries = _select_fn(p)(panel, start_date=w0, end_date=w1, regime_df=reg, **kwargs)

    g = panel.sort_values(["thscode", "date"]).copy()
    g["_fwd"] = g.groupby("thscode")["close"].shift(-H) / g["close"] - 1.0
    ctrl_by_date = g.groupby("date")["_fwd"].mean()
    mg = entries.merge(g[["date", "thscode", "_fwd"]], on=["date", "thscode"], how="left")
    mg["exc"] = mg["_fwd"] - mg["date"].map(ctrl_by_date)
    top1 = mg.sort_values(["date", "score"], ascending=[True, False]).groupby("date").head(1)

    return {
        "n_signals": m["signals"], "n_trades": m["trades"],
        "fill_rate": (m["trades"] / m["signals"]) if m["signals"] else 0.0,
        "exposure": m["exposure"], "avg_hold_days": m["avg_hold_days"],
        "total_return": m["total_return"],
        "exc_a": np.asarray(exc_a, float), "gross_a": np.asarray(gross_a, float),
        "exc_top1": top1["exc"].to_numpy(float),
        "exc_all": mg["exc"].to_numpy(float),
    }


def _panel(preset: dict, w0: str, w1: str, *, pit: bool):
    """建 panel —— **PIT 口径只在这里写一次** (主口径与 A/B 共用同一处)。

    ⚠️ 这里**故意把两个分支写成两条显式调用**, 而不是 `**kw` 解包 ——
    因为 §13.123 的 AST 守卫看得到关键字, **看不到 `**` 解包里有没有 `asof_date`**
    (AST 里 `**kw` 的 `arg` 是 None)。用解包会让守卫无法判定, 也让读者无法一眼看出。
    """
    # ⚠️ §3 PIT (§13.123): **预建 panel 的调用方必须自己做 PIT。**
    # `run_backtest(..., panel_ind=...)` 只在 panel_ind is None 时才自己取股票池。
    if pit:
        uni = set(load_universe(preset["universe"], DB_PATH, asof_date=w0))
    else:
        # 故意: `--ab` 的反事实臂 (见模块 docstring)。非产品路径。
        uni = set(load_universe(preset["universe"], DB_PATH))
    return compute_indicators(load_panel(DB_PATH, w0, w1, universe=uni)), len(uni)


def _ab(preset: dict) -> None:
    """post-hoc 池 vs PIT 池 —— 量出 §13.123 那处静默绕过的**幅度**。"""
    print("=== A/B: 同一个 preset/窗口, 只换股票池 (§3 PIT 有没有被绕过) ===")
    print(f"{'窗口':<5} {'池':<9} {'股票数':>7} {'笔数':>6} {'总收益':>10} "
          f"{'Sharpe':>8} {'maxDD':>7}")
    for label, w0, w1 in WINDOWS:
        for kind, pit in (("post-hoc", False), ("PIT", True)):
            panel, n_uni = _panel(preset, w0, w1, pit=pit)
            m = run_backtest(preset, w0, w1, DB_PATH, panel_ind=panel)["metrics"]
            print(f"{label:<5} {kind:<9} {n_uni:>7} {m['trades']:>6} "
                  f"{m['total_return']:>+10.2%} {m['sharpe']:>+8.3f} {m['max_dd']:>7.3f}")
            del panel
    print("\n读法: 两列若不同, 说明该口径**不是 PIT**。方向可能两边都出现 ——\n"
          "它不是'乐观偏差', 是**另一个实验** (换了一批可选标的)。")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--preset", default=DEFAULT_PRESET)
    ap.add_argument("--ab", action="store_true",
                    help="额外跑 post-hoc vs PIT 股票池的 A/B (§13.123)")
    args = ap.parse_args()

    p = get_preset(args.preset)
    if args.ab:
        _ab(p)
        return

    print(f"preset = {args.preset}  entry_mode = {p['signal'].get('entry_mode')}")
    print(f"max_positions = {p.get('max_positions')}  "
          f"sizing = {p.get('position_sizing')}  "
          f"position_fraction = {p.get('position_fraction')}")
    print(f"前向口径 h = {H}\n")

    print("=== 信号吃下率 (容量是不是紧的?) ===")
    print(f"{'窗口':<5} {'信号数':>8} {'成交数':>8} {'吃下率':>8} {'暴露':>8} {'均持仓':>7} {'总收益':>10}")
    rows = {}
    for label, w0, w1 in WINDOWS:
        r = _one_window(p, w0, w1)
        rows[label] = r
        print(f"{label:<5} {r['n_signals']:>8} {r['n_trades']:>8} {r['fill_rate']:>7.1%} "
              f"{r['exposure']:>7.2%} {r['avg_hold_days']:>7.1f} {r['total_return']:>+10.2%}")

    print("\n=== A: 实际成交的逐笔超额 (vs 同起止日等权对照) ===")
    print(f"{'窗口':<5} {'n':>5} {'原始收益':>10} {'超额':>10} {'t':>7}")
    for label in rows:
        r = rows[label]
        t, n = _tstat(r["exc_a"])
        print(f"{label:<5} {n:>5} {np.nanmean(r['gross_a']):>+10.2%} "
              f"{np.nanmean(r['exc_a']):>+10.2%} {t:>+7.2f}")

    print("\n=== B: 固定 h 前向超额 —— **择优 vs 候选集全量** (§6.3.2 的缺口) ===")
    print(f"{'窗口':<5} | {'择优 top-1':>22} | {'候选集全量':>22}")
    print(f"{'':5} | {'mean':>9} {'t':>6} {'n':>5} | {'mean':>9} {'t':>6} {'n':>5}")
    for label in rows:
        r = rows[label]
        t1, n1 = _tstat(r["exc_top1"])
        t2, n2 = _tstat(r["exc_all"])
        print(f"{label:<5} | {np.nanmean(r['exc_top1']):>+9.2%} {t1:>+6.2f} {n1:>5} | "
              f"{np.nanmean(r['exc_all']):>+9.2%} {t2:>+6.2f} {n2:>5}")

    print("\n=== 合并四窗 ===")
    for name, key in (("择优 top-1", "exc_top1"), ("候选集全量", "exc_all"),
                      ("实际成交", "exc_a")):
        allx = np.concatenate([rows[label][key] for label in rows])
        t, n = _tstat(allx)
        print(f"  {name:<10} n={n:>5}  mean={np.nanmean(allx):>+8.2%}  t={t:>+6.2f}")

    print("\n读法 (§5 归因口径): t 不到 ±2 时只能写「没有正/负贡献」, 不能写「显著」。")
    print("本脚本不选择任何配置 ⇒ 不产生新的 DSR 主张; 它只做**归因**。")


if __name__ == "__main__":
    main()
