"""[同一个入场集合] × {基线出场政策, ATR 出场政策} 的逐 bar 重放取证 (§13.199)。

问的是什么
----------
§13.196 用**完整重模拟**换出场政策 ⇒ W2 摆动 140pp。但那里面**两个通道叠在一起**:
  ① **几何** (同一些票的盈亏率变了);
  ② **机会数量** (笔数/持仓时长塌了 ⇒ 成交集合整个换了一批)。
§13.198(g) 想用 `max_hold` 把笔数按住来拆 ⇒ **失败**, 因为 `max_hold` 本身既是几何旋钮
又是机会旋钮 (刀刃)。

**本工具的正确做法**: **不重新模拟**。
拿基线的**同一批入场** (逐笔的 `entry_date`/`thscode`/`entry_price`/`size`),
**只换出场政策**, 从入场日之后逐 bar 重放 ⇒ **成交集合天然固定**, 差只来自**几何**。

为什么这个工具自带一个"通过/不通过"的关卡
------------------------------------------
> **用"基线政策"重放"基线的入场", 必须复现引擎记的出场。**
> 复现不了 ⇒ 是**我的重放错了**, 不是我发现了什么。

本工具把这个自检当成**硬门禁**: 出场日、出场价、原因三者逐笔比对,
任何一项低于 100% 就**打印作废声明**并以非零码退出 (默认)。

重放模型与引擎逐行对齐
----------------------
规则顺序照抄 `uptrend_pullback/portfolio.py::simulate_portfolio` 的出场块 (~L489-508):

    if o <= sl_p:          SL @ o      # §4 跳空穿止损: 填开盘价 (悲观)
    elif o >= tp_p:        TP @ o
    elif lo <= sl_p:       SL @ sl_p
    elif h >= tp_p:        TP @ tp_p
    elif bars >= max_hold: time @ c    # §4 日内盲区: SL 优先于 TP 已由上序保证

价格源用 **raw 系列列** (`raw_open/high/low/close`) (§3: SL/TP 是**未复权**世界的制度约束),
与 preset 的 `price_source_for_execution="raw_close"` 一致。

⚠️ **如实登记本重放省略了什么** (以及为什么可以省):
* **跌停封板拒卖守卫** (`_raw_ok` 那段) —— 省略。86/86 的自检是它在本样本上**没有咬合**
  的证据 (否则出场日/价不可能逐笔吻合); 它一旦咬合, 自检就会红。
* **`_exit_fill_px` 出场成交价变换** —— 省略。本族 4/4 个 preset 的 `slippage` 与
  `atr_slip_scale` 都是 0 (§13.189/§13.191 的零漂移结论), 该变换是恒等;
  同样地, 自检不吻合就会红。
* **入口 ATR 口径**: 引擎读 `atr_lookup[(cal[t-1], code)]` = **信号日**那一行
  (`portfolio.py:641`)。本工具照抄。⚠️ 第一版我取的是**入场日**的 `atr_pct`
  ⇒ 几何通道的差 **−1,917,095 → −2,355,973**, 差 44 万 ⇒ **口径错是会影响结论的**。

⚠️ **本工具报的是反事实, 不是可交易结果**
股数固定在基线那一档 ⇒ 它只用于**通道归因**, 不能读成"换个政策能赚 X"。

用法:
    python3 tools/same_entries_exit_policy_cf.py                 # 默认 uptrend / v33_long_reverse_v22
    python3 tools/same_entries_exit_policy_cf.py --teeth          # 注入检查: 至少一个扰动必须让自检红
    python3 tools/same_entries_exit_policy_cf.py --preset <名>

实测 (2026-10-20, W2): 自检 86/86 通过; 注入检查 **4/5 响** —— **`swap_sl_tp_order` 不响**,
而它是**结构上不可能响**的: 本 preset 的 `sl_pct=2.10%` / `tp_pct=26.28%` ⇒ 同一根 bar
要同时触及两者需要 >28% 的日内振幅。⇒ 那是**死钉桩** (一个永不可能触发的注入),
不是判据坏了。⚠️ **第一版我只写了这一个注入, 于是整个"牙齿检查"是假的。**

而 `no_gap_through_stop` 给出一个**意外的旁证**: 拆掉 §4 的跳空分支后
**出场日 86/86、原因 86/86 不变, 只有出场价 51/86 变** ⇒
跳空穿止损是**纯价格效应、不是时点效应** —— 这正是"第一股力"(§13.158/§13.190)在单笔层面的签名。
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

# ⚠️ 只支持出场语义已被本工具逐行对齐过的那一族。其余族 **fail-fast 拒跑**,
#    不猜、不近似 —— cycle 走分配器 (每票独立账户)、short_reversal 需 T+1 与
#    涨停/跌停拒单 (§4), 照 uptrend 的规则顺序重放它们会得到**看着像结论的假数**。
SUPPORTED = ("uptrend_pullback",)

# (家族, 默认 preset, 默认窗口) —— 窗口口径与 tools/capacity_ceiling.py 一致 (§13.8)。
DEFAULTS: dict[str, tuple[str, str, str]] = {
    "uptrend_pullback": ("v33_long_reverse_v22", "W2"),
}

# ⚠️ `W2` 的末日按 §13.8 截到干净日 (§13.9: 复权因子表落后 7 个交易日,
#    更晚的窗口在 `v_daily_hfq` 上会读到**假的暴跌**)。
WINDOWS: dict[str, tuple[str, str]] = {
    "W2": ("2024-10-08", "2026-09-18"),
    "IND": ("2022-10-03", "2024-09-30"),
    "IS1": ("2021-10-01", "2022-09-30"),
    "IS2": ("2023-10-01", "2024-09-30"),
    "EXTRA": ("2017-10-02", "2019-09-30"),
}

# ATR 对照臂的参数 (chase_up §13.196 用的那一档)。
ATR_TP_MULT, ATR_SL_MULT, ATR_MAX_HOLD = 6.0, 1.75, 18
ATR_FLOOR, ATR_CAP = 0.01, 0.08
MAX_LOOKAHEAD = 60      # 逐 bar 最多看这么多根 (两臂的 max_hold 都远小于它)

# `--sweep` 的取值: 都以**基线倍数**给 (含 1.0 = 基线, 那一点有自检)。
SWEEP_MULT = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0)


def _sweep(bars_by_code: dict, tr: pd.DataFrame, preset: dict, axis: str) -> None:
    """**同一批入场**上, 一次只动一根轴 (tp 或 sl), 另一根钉在基线值。

    ⚠️ **只报形状 (符号 / 单调性), 不报「哪一格最好」**(§5 禁止同窗择优)。
    ⚠️ 只有 `×1.0` 那一点有 ground truth (自检); 其余点是**纯反事实** ——
       股数没有跟着重算, 所以**格与格之间可比**(同一把尺), 但不能读成可交易结果。
    """
    base_v = float(preset["tp_pct"] if axis == "tp" else preset["sl_pct"])
    other = float(preset["sl_pct"] if axis == "tp" else preset["tp_pct"])
    mh = int(preset["max_hold"])
    print(f"\n=== --sweep {axis}: 同一批 {len(tr)} 个入场, 另一根轴钉在基线 "
          f"({'sl' if axis == 'tp' else 'tp'}={other:.4f}) ===")
    print(f"  {'x基线':>7}{axis + ' 取值':>12}{'毛 Σ P&L':>16}{'Δ vs 基线':>16}{'可重放':>9}")
    rows = []
    for m in SWEEP_MULT:
        v = base_v * m
        s, n = 0.0, 0
        for t in tr.itertuples():
            bars = bars_by_code.get(t.thscode)
            if bars is None:
                continue
            tp_eff, sl_eff = (v, other) if axis == "tp" else (other, v)
            r = _replay(bars, t.entry_date, float(t.entry_price), tp_eff, sl_eff, mh)
            if r is None:
                continue
            s += (r[1] - float(t.entry_price)) * int(t.size)
            n += 1
        rows.append((m, v, s, n))
    ref = next(s for m, _, s, _ in rows if m == 1.0)
    for m, v, s, n in rows:
        tag = "  <- 基线 (有自检)" if m == 1.0 else ""
        print(f"  {m:>7.2f}{v:>12.4f}{s:>+16,.0f}{s - ref:>+16,.0f}{n:>9}{tag}")
    ds = [s for _, _, s, _ in rows]
    inc = all(b > a for a, b in zip(ds, ds[1:]))
    dec = all(b < a for a, b in zip(ds, ds[1:]))
    shape = "**单调增**" if inc else ("**单调减**" if dec else "**非单调**")
    print(f"  => 形状: {shape} (极差 {max(ds) - min(ds):>+,.0f})")
    print("  ⚠️ 这只说明**这根轴有没有单调方向**, 不是说某一格更好 —— 同窗择优是 §5 禁令。")


def _load(family: str, preset_name: str, w0: str, w1: str):
    if family == "uptrend_pullback":
        from uptrend_pullback.backtest import run_backtest
        from uptrend_pullback.data import load_panel
        from uptrend_pullback.presets import get_preset
        from uptrend_pullback.signals import compute_indicators
        from uptrend_pullback.universe import load_universe
    else:
        raise SystemExit(f"⛔ {family} 不在已对齐的出场语义清单 {SUPPORTED} 内 ⇒ 拒跑。")

    preset = dict(get_preset(preset_name))
    uni = set(load_universe(preset["universe"], DB_PATH, asof_date=w0))
    panel = compute_indicators(load_panel(DB_PATH, w0, w1, universe=uni))
    res = run_backtest(dict(preset), w0, w1, DB_PATH, panel_ind=panel)
    return preset, panel, res


def _replay(bars: dict, e0, e0_px: float, tp_eff: float, sl_eff: float,
            max_hold: int, perturb: str = ""):
    """从入场日之后逐 bar 判出场 ⇒ (exit_date, exit_px, reason) 或 None。

    `perturb` 是**注入**: 用它把重放故意弄错, 观察自检会不会红 (见 `--teeth`)。
    """
    d = bars
    pos = np.where(d["date"].to_numpy() == np.datetime64(pd.Timestamp(e0)))[0]
    if len(pos) == 0:
        return None
    i0 = int(pos[0])
    sl_p = e0_px * (1 - sl_eff)
    tp_p = e0_px * (1 + tp_eff)

    # 价格源: 正常用 raw_* (§3); 注入时故意改用复权价。
    src = ("open", "high", "low", "close") if perturb == "use_adj_prices" \
        else ("raw_open", "raw_high", "raw_low", "raw_close")
    k_o, k_h, k_lo, k_c = src

    start = 2 if perturb == "start_one_bar_late" else 1
    for k in range(start, MAX_LOOKAHEAD):
        i = i0 + k
        if i >= len(d):
            return None
        o = d[k_o].iat[i]
        h = d[k_h].iat[i]
        lo = d[k_lo].iat[i]
        c = d[k_c].iat[i]
        if np.isnan(o) or np.isnan(h) or np.isnan(lo) or np.isnan(c):
            continue          # 停牌/缺 bar ⇒ 顺延 (不造合成 bar, §1)
        day = pd.Timestamp(d["date"].iat[i])

        gap_check = (perturb != "no_gap_through_stop")
        if perturb == "swap_sl_tp_order":
            if o >= tp_p:
                return (day, float(o), "TP")
            if o <= sl_p:
                return (day, float(o), "SL")
            if h >= tp_p:
                return (day, float(tp_p), "TP")
            if lo <= sl_p:
                return (day, float(sl_p), "SL")
        else:
            if gap_check and o <= sl_p:
                return (day, float(o), "SL")      # §4 跳空穿止损: 填开盘价 (悲观)
            if o >= tp_p:
                return (day, float(o), "TP")
            if lo <= sl_p:
                return (day, float(sl_p), "SL")
            if h >= tp_p:
                return (day, float(tp_p), "TP")

        # §4 日内盲区: SL 优先于 TP 已由上序保证 (两臂 tp/sl 宽度差异极大, 见下)
        if k >= max_hold and perturb != "drop_time_exit":
            return (day, float(c), "time")
    return None


def _signal_day_atr(bars: dict, entry_date, floor: float, cap: float) -> float | None:
    """**信号日** = 入场日的上一根 bar 的 `atr_pct` (照抄 portfolio.py:641)。"""
    pos = np.where(bars["date"].to_numpy() == np.datetime64(pd.Timestamp(entry_date)))[0]
    if len(pos) == 0 or int(pos[0]) < 1:
        return None
    a = bars["atr_pct"].iat[int(pos[0]) - 1]
    if np.isnan(a):
        return None
    return float(min(max(a, floor), cap))


def _build_df(bars_by_code: dict, tr: pd.DataFrame, preset: dict,
              perturb: str = "") -> pd.DataFrame:
    rows = []
    for t in tr.itertuples():
        bars = bars_by_code.get(t.thscode)
        if bars is None:
            continue
        e0_px = float(t.entry_price)
        base = _replay(bars, t.entry_date, e0_px, float(preset["tp_pct"]),
                       float(preset["sl_pct"]), int(preset["max_hold"]),
                       perturb=perturb)
        a = _signal_day_atr(bars, t.entry_date, ATR_FLOOR, ATR_CAP)
        atrx = (None if a is None else
                _replay(bars, t.entry_date, e0_px, ATR_TP_MULT * a, ATR_SL_MULT * a,
                        ATR_MAX_HOLD))
        rows.append((t.entry_date, t.thscode, t.exit_date, float(t.exit_price),
                     t.exit_reason, int(t.size), e0_px, base, atrx))
    return pd.DataFrame(rows, columns=["entry_date", "thscode", "exit_date", "exit_px",
                                       "reason", "size", "entry_px", "base", "atrx"])


def _self_check(df: pd.DataFrame, label: str, quiet: bool = False) -> bool:
    n = len(df)
    ok_date = sum(1 for r in df.itertuples()
                  if r.base is not None and r.base[0] == r.exit_date)
    ok_px = sum(1 for r in df.itertuples()
                if r.base is not None
                and abs(r.base[1] - r.exit_px) / max(abs(r.exit_px), 1e-9) < 1e-6)
    ok_rs = sum(1 for r in df.itertuples() if r.base is not None and r.base[2] == r.reason)
    ok = min(ok_date, ok_px, ok_rs) == n
    if quiet:
        print(f"  {label:<26} 日 {ok_date:>3}/{n} · 价 {ok_px:>3}/{n} · 因 {ok_rs:>3}/{n}"
              f"   {'✅ 通过' if ok else '⛔ **红了**'}")
        return ok
    print(f"\n=== 自检 ({label}): 重放基线政策 vs 引擎记的 ===")
    print(f"  出场日一致 {ok_date}/{n} · 出场价一致 {ok_px}/{n} · 原因一致 {ok_rs}/{n}")
    if not ok:
        print("  ⛔ **重放复现不了基线** ⇒ 本节结论**作废** (是我的重放错了, 不是发现)。")
        return False
    print("  ✅ 三者**逐笔满分** ⇒ 重放读到的正是它声称的那个量 (§13.105)。")
    return True


def _teeth_check(bars_by_code: dict, tr: pd.DataFrame, preset: dict) -> bool:
    """注入检查: 至少**一个**扰动必须让自检红 ⇒ 否则这个自检是**死钉桩**。"""
    print("\n=== 注入检查: 自检有牙齿吗 ===")
    clean = _self_check(_build_df(bars_by_code, tr, preset), "无注入 (应为绿)",
                        quiet=True)
    if not clean:
        print("⛔ 无注入就已经红了 ⇒ 先修重放, 谈不到牙齿。")
        return False
    fired = 0
    for p in ("start_one_bar_late", "drop_time_exit", "use_adj_prices",
              "no_gap_through_stop", "swap_sl_tp_order"):
        if not _self_check(_build_df(bars_by_code, tr, preset, perturb=p), p, quiet=True):
            fired += 1
    print(f"  ⇒ **{fired}/{5} 个注入响**; 需要 ≥1 ⇒ {'✅ 自检有牙齿' if fired else '⛔ 死钉桩'}")
    return fired >= 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--family", default="uptrend_pullback")
    ap.add_argument("--preset", default=None)
    ap.add_argument("--window", default=None, choices=list(WINDOWS),
                    help="默认取 DEFAULTS 里的那一窗")
    ap.add_argument("--teeth", action="store_true",
                    help="注入检查: 至少一个扰动必须让自检变红 (证明自检不是死钉桩)")
    ap.add_argument("--sweep", choices=["tp", "sl"], default=None,
                    help="在同一批入场上一次只动一根轴, 只报形状 (±1.0 那点有自检); 不报最优")
    args = ap.parse_args()

    preset_name, win = DEFAULTS.get(args.family, (None, None))
    preset_name = args.preset or preset_name
    win = args.window or win
    w0, w1 = WINDOWS[win]
    preset, panel, res = _load(args.family, preset_name, w0, w1)

    tr = pd.DataFrame(res["trades"]).copy()
    if len(tr) == 0:
        raise SystemExit("⛔ 基线无成交 ⇒ 无从重放。")
    tr["entry_date"] = pd.to_datetime(tr["entry_date"])
    tr["exit_date"] = pd.to_datetime(tr["exit_date"])

    print(f"family={args.family} preset={preset_name} 窗口 {win} {w0}..{w1}")
    print(f"基线: {len(tr)} 笔, final_equity={float(res['metrics']['final_equity']):,.0f}")

    need = ("date", "raw_open", "raw_high", "raw_low", "raw_close", "atr_pct",
            "open", "high", "low", "close")
    missing = [c for c in need if c not in panel.columns]
    if missing:
        raise SystemExit(f"⛔ 面板缺列 {missing} ⇒ 重放需要的价格源不存在, 拒跑。")
    bars_by_code = {c: s.reset_index(drop=True) for c, s in panel.groupby("thscode", sort=False)}

    if args.teeth:
        return 0 if _teeth_check(bars_by_code, tr, preset) else 1

    df = _build_df(bars_by_code, tr, preset)
    if not _self_check(df, "基线政策"):
        return 1

    if args.sweep:
        _sweep(bars_by_code, tr, preset, args.sweep)
        return 0

    def total(col: str) -> float:
        s = 0.0
        for r in df.itertuples():
            x = getattr(r, col)
            px = r.exit_px if x is None else x[1]   # 重放不到 ⇒ 保持基线出场 (保守)
            s += (px - r.entry_px) * r.size
        return s

    tb, ta = total("base"), total("atrx")
    n_atr = int(df["atrx"].notna().sum())
    net_b = float(res["metrics"]["final_equity"]) - 1_000_000.0
    print(f"\n=== 同一批 {len(df)} 个入场, 只换出场政策 ===")
    print(f"  ⚠️ 口径: 下面两个 Σ 是 **(出场价 − 入场价) × 基线股数**, 即 **毛 P&L, 不含费用**,")
    print(f"     且股数**固定为基线那一档** ⇒ 它与引擎报的 `final_equity − 初始` (**净**, 各臂自带股数)")
    print(f"     **不是同一个量**, 两者之差**不可**当作「费用」或「通道」来解释。")
    print(f"  基线政策 (固定 {preset['tp_pct']:.4f} / {preset['sl_pct']:.4f}, mh={preset['max_hold']})"
          f"  毛 Σ P&L = {tb:>14,.0f}   (引擎净 Σ = {net_b:>14,.0f}; 差 {tb-net_b:>+12,.0f} = 费 + 口径)")
    print(f"  ATR  政策 (信号日 ATR × {ATR_TP_MULT} / {ATR_SL_MULT}, mh={ATR_MAX_HOLD}; "
          f"可用 {n_atr}/{len(df)} 笔)  毛 Σ P&L = {ta:>13,.0f}")
    print(f"  ⇒ **几何通道的差 (毛, 同规模) = {ta - tb:>+14,.0f}**")
    same_mh = (int(preset["max_hold"]) == ATR_MAX_HOLD)
    if same_mh:
        print(f"  ⚠️ **两臂的 max_hold 相同 (= {ATR_MAX_HOLD})** ⇒ 唯一的政策差就是 "
              f"tp/sl 的宽窄 ⇒ 这一整个摆动**只是止损/止盈宽度**造成的。")
    print(f"  (对照 §13.196 完整重模拟的差 ≈ −1,449,000 元 / −144.48pp)")
    print("""
读法: 入场集合、股数、入场价**逐笔固定** ⇒ 这个差**只**来自几何。
      ⚠️ 这是**反事实** (股数没跟着新政策重算), 只用于通道归因, 不是可交易结果。
      ⚠️ ATR 臂 = **把 chase 的档套在 uptrend 的入场上** ⇒ 它测**几何**, 不是"chase 政策更好"。""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
