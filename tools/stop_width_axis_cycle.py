"""`cycle_price_action` 的**止损受控轴** (§13.176) —— 四族里最后一个空格。

活键是 `sl_pct` (§13.175)
--------------------------
本族 `PRESET_V1` 同时声明 `sl_pct` 与 `atr_sl_mult`, 但 §13.175 已证明
**`self.p.atr_sl_mult` 在全族一处也没有** ⇒ 止损**纯固定百分比**
(`portfolio.py:377-378`: `tp_p = entry×(1+tp_pct)`, `sl_p = entry×(1−sl_pct)`)。
⇒ 受控轴**必须动 `sl_pct`** (动 `atr_sl_mult` 会得到"什么都没变"的假零结果)。

⚠️ 两条边界 (必须与数字一起读)
--------------------------------
1. **名册截到 200 只** (真引擎/真数据) ⇒ 只读**沿轴方向**, 绝对量级不可与族记分卡比 (§13.168 同一条);
2. `max_positions=1` ⇒ §13.174 那个"N>1 口径不一致"**不适用** (N=1 两种口径恒等, 实测差 0)
   ⇒ 组合数走 `allocator` 是**精确**的。**本表报的就是组合层数**。
3. `TradeRecord` **没有 `exit_reason`** ⇒ 出场原因**从价格反推** (≤ sl_p→SL、≥ tp_p→TP、其余→time);
   ⚠️ **反推**, 不是记录值。

用法:
    python3 tools/stop_width_axis_cycle.py
    python3 tools/stop_width_axis_cycle.py --sl-pcts 0.02 0.035 0.05 0.08
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hiagent_config import DB_PATH  # noqa: E402

import cycle_price_action.allocator as A  # noqa: E402
import cycle_price_action.backtest as B  # noqa: E402
from cycle_price_action.allocator import METRICS_BASIS as _BASIS  # noqa: E402
from cycle_price_action.presets import PRESET_V1  # noqa: E402

INITIAL = 1_000_000.0
N_CODES = 200
WINDOWS: tuple[tuple[str, str, str], ...] = (
    ("W2", "2024-10-08", "2026-09-18"),
    ("IND", "2022-10-03", "2024-09-30"),
)


def _days(w0: str, w1: str) -> list:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return [r[0] for r in con.execute(
            "SELECT DISTINCT date FROM v_daily WHERE date BETWEEN ? AND ? ORDER BY date",
            [w0, w1]).fetchall()]
    finally:
        con.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sl-pcts", type=float, nargs="+", default=[0.02, 0.035, 0.05, 0.08])
    ap.add_argument("--n-codes", type=int, default=N_CODES)
    args = ap.parse_args()

    print(f"口径披露 (§13.13): cycle_price_action -> {dict(_BASIS)}")
    base = dict(PRESET_V1)
    print(f"preset=PRESET_V1  tp_pct={base['tp_pct']} (固定)  max_hold={base['max_hold']} (固定)  "
          f"max_positions={base['max_positions']}")
    print(f"⚠️ 活键 = `sl_pct` (不是 `atr_sl_mult` —— §13.175); 名册截到 {args.n_codes} 只\n")

    # ★ 先用**真** loader 取真名册, 再替换 (不 wrap 原函数 ⇒ 不递归; §13.174 的教训)
    ORIG = B.load_universe_data
    seen: dict = {}

    def _patched(db_path, start, end, asof_date=None, **kw):
        # ⚠️⚠️ 第一版把"第一次调用"的结果**缓存后原样返回** ⇒ 那个 dict 里的 DataFrame
        # 是**第一个窗口**的切片 ⇒ 无论引擎请求哪个窗口, **数据永远是第一个窗口的**
        # ⇒ 两个窗口的输出**逐位相同**, 而 IND 的 allocator 拿到一段与成交**不相交**的日历
        # ⇒ 平权益 ⇒ 打出 **+0.00% / maxDD 0.00%**, 看起来像"这个窗口没收益"。
        # ⇒ **patch 只能缩名册, 不能冻数据**: 每次都**真调原 loader**, 再截名册。
        full = ORIG(db_path, start, end, asof_date=asof_date, **kw)
        seen["full"] = len(full)
        return {k: full[k] for k in sorted(full)[: args.n_codes]}

    B.load_universe_data = _patched
    print(f"  (名册截到 {args.n_codes} 只 / 每个窗口各自取其全名册)\n")

    hdr = (f"{'sl_pct':>8}{'窗口':<6}{'笔数':>6}{'SL*':>5}{'TP*':>5}{'time*':>6}{'跳空':>5}"
           f"{'跳空占比':>9}{'跳空成本':>10}{'组合收益':>11}{'maxDD':>9}")
    print(hdr); print("-" * len(hdr))
    rows = []
    try:
        for slp in args.sl_pcts:
            preset = {**base, "sl_pct": float(slp)}
            for wl, w0, w1 in WINDOWS:
                r = B.run_backtest(str(DB_PATH), dt.date.fromisoformat(w0),
                                   dt.date.fromisoformat(w1), preset=preset)
                t = r.trades
                if not t:
                    print(f"{slp:>8.4f}{wl:<6}{0:>6}"); continue
                df = pd.DataFrame([vars(x) for x in t])
                ep = df["entry_price"].astype(float); xp = df["exit_price"].astype(float)
                sl_p = ep * (1.0 - float(slp)); tp_p = ep * (1.0 + float(base["tp_pct"]))
                is_sl = xp <= sl_p * (1.0 + 1e-12)
                is_tp = xp >= tp_p * (1.0 - 1e-12)
                is_tm = ~is_sl & ~is_tp
                gap = is_sl & (xp < sl_p * (1.0 - 1e-12))
                cost = float(((sl_p[gap] - xp[gap]) * df["shares"].astype(float)[gap]).sum()) / INITIAL
                res = A.allocate(t, trading_days=_days(w0, w1), initial_capital=INITIAL,
                                 max_positions=int(base["max_positions"]))
                m = A.portfolio_metrics(res)
                n_sl = int(is_sl.sum())
                print(f"{slp:>8.4f}{wl:<6}{len(df):>6}{n_sl:>5}{int(is_tp.sum()):>5}{int(is_tm.sum()):>6}"
                      f"{int(gap.sum()):>5}{(int(gap.sum())/n_sl if n_sl else float('nan')):>9.1%}"
                      f"{cost:>10.2%}{m['total_return']:>11.2%}{m['max_dd']:>9.2%}")
                rows.append(dict(sl=float(slp), win=wl, n=len(df), n_sl=n_sl,
                                 cost=cost, ret=float(m["total_return"]),
                                 dd=float(m["max_dd"] or 0.0)))
            print()
    finally:
        B.load_universe_data = ORIG

    print("=== Z1 机理自验: SL 笔数是否随止损变窄而上升 ===")
    bad = []
    for wl, _, _ in WINDOWS:
        c = [x["n_sl"] for x in rows if x["win"] == wl]
        if any(c[i] < c[i + 1] for i in range(len(c) - 1)):
            bad.append((wl, c))
    print("  ✅ 两窗都单调" if not bad else f"  ⚠️ 非单调: {bad}  (⚠️ 本轴同时改入场集合, ±1 级别的抖动见 §13.167(g))")

    print("\n=== Z2 跨族'第一股力': 跳空成本随止损变窄 ===")
    for wl, _, _ in WINDOWS:
        print(f"  {wl:<6} " + "  ".join(f"{x['cost']:>9.2%}" for x in rows if x["win"] == wl))
    print("\n=== Z3: 逐窗符号 (§5: 不报「哪档最好」) ===")
    for wl, _, _ in WINDOWS:
        print(f"  {wl:<6} " + "  ".join(f"{x['ret']:>+10.2%}" for x in rows if x["win"] == wl))
    print("""
⚠️ 名册截到 200 只 ⇒ 只读**方向**不读量级; `SL*/TP*/time*` 是**从价格反推**的 (TradeRecord 无 exit_reason)。
⚠️ 每次运行的档数计入 `n_trials` (§5)。""")


if __name__ == "__main__":
    main()
