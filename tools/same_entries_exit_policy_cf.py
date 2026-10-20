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

# §2 Canonical Cost Model: 费用常量只在 core/ 定义一次 —— 本工具**导入**而非重写。
from core.dual_price import calc_commission, calc_stamp_duty  # noqa: E402

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
    print(f"  {'x基线':>7}{axis + ' 取值':>12}{'毛 Σ P&L':>16}{'Δ vs 基线':>16}"
          f"{'TP':>5}{'SL':>5}{'time':>6}{'top3 Σ':>16}{'top3 占比':>10}")
    rows = []
    for m in SWEEP_MULT:
        v = base_v * m
        tp_eff, sl_eff = (v, other) if axis == "tp" else (other, v)
        s, reasons, top3, _ = _policy_stats(bars_by_code, tr, tp_eff, sl_eff, mh)
        rows.append((m, v, s, reasons, top3))
    ref = next(s for m, _, s, _, _ in rows if m == 1.0)
    for m, v, s, rs, top3 in rows:
        tag = "  <- 基线 (有自检)" if m == 1.0 else ""
        share = (top3 / s) if s else float("nan")
        print(f"  {m:>7.2f}{v:>12.4f}{s:>+16,.0f}{s - ref:>+16,.0f}"
              f"{rs['TP']:>5}{rs['SL']:>5}{rs['time']:>6}{top3:>+16,.0f}{share:>10.1%}{tag}")
    ds = [s for _, _, s, _, _ in rows]
    inc = all(b > a for a, b in zip(ds, ds[1:]))
    dec = all(b < a for a, b in zip(ds, ds[1:]))
    shape = "**单调增**" if inc else ("**单调减**" if dec else "**非单调**")
    print(f"  => 形状: {shape} (极差 {max(ds) - min(ds):>+,.0f})")
    # 非单调到底跟不跟 `n_TP` 走? (逐对相邻变动: 只比**两边都在动**的那些对)
    ntps = [rs["TP"] for _, _, _, rs, _ in rows]
    pairs = 0
    flips = 0
    for i in range(len(ds) - 1):
        d_s, d_n = ds[i + 1] - ds[i], ntps[i + 1] - ntps[i]
        if d_s != 0 and d_n != 0:
            pairs += 1
            flips += 1 if (d_s > 0) != (d_n > 0) else 0
    print(f"  => `n_TP` 与 Σ 的相邻变动: **{pairs - flips}/{pairs} 同向**"
          f"  (n_TP 七档: {ntps})")
    print("  ⚠️ 这只说明**这根轴有没有单调方向**与**它跟什么联动**, 不是说某一格更好 —— 同窗择优是 §5 禁令。")


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


# `--net`: 是否扣规范费用 (§2 单一来源: `core.dual_price`)。
NET = False


def entry_fee(px: float, size: int) -> float:
    """买入腿费用 = 佣金 (含 ¥5 地板); 买入不缴印花税。"""
    return float(calc_commission(px * size))


def exit_fee(px: float, size: int) -> float:
    """卖出腿费用 = 佣金 (含 ¥5 地板) + **印花税**。"""
    return float(calc_commission(px * size) + calc_stamp_duty(px * size, "sell"))


def _policy_stats(bars_by_code: dict, tr: pd.DataFrame, tp_eff: float, sl_eff: float,
                  mh: int, net: bool | None = None) -> tuple[float, dict, float, int]:
    """同一批入场、同一批股数下: (毛/净 Σ, 出场原因计数, top-3 Σ, 可重放笔数)。

    `net` 为真 (或 `None` 时取模块级 `NET`) 时, 按 **`core.dual_price` 的规范费用**扣减
    (单一来源, §2): 双边佣金 (含 ¥5 地板) + **卖出**方印花税。
    ⚠️ **股数仍固定在基线那一档** ⇒ `--net` 只补上**费用**, 不解决"各臂自有股数";
       所以净读数与引擎的 `final_equity` **仍不是同一个量**, 但**格与格之间**同尺可比。
    """
    use_net = NET if net is None else net
    pnls: list[float] = []
    reasons: dict[str, int] = {"TP": 0, "SL": 0, "time": 0}
    for t in tr.itertuples():
        bars = bars_by_code.get(t.thscode)
        if bars is None:
            continue
        r = _replay(bars, t.entry_date, float(t.entry_price), tp_eff, sl_eff, mh)
        if r is None:
            continue
        entry_px, exit_px, size = float(t.entry_price), float(r[1]), int(t.size)
        pnl = (exit_px - entry_px) * size
        if use_net:
            pnl -= entry_fee(entry_px, size) + exit_fee(exit_px, size)
        pnls.append(pnl)
        reasons[r[2]] = reasons.get(r[2], 0) + 1
    return (float(sum(pnls)), reasons, float(sum(sorted(pnls, reverse=True)[:3])), len(pnls))


def _stats_row(win: str, label: str, bars_by_code: dict, tr: pd.DataFrame,
               preset: dict) -> tuple[float, float, float, float, float, int] | None:
    """给一批入场算 (T, S, 基线 Σ, Σ(×0.5), Σ(×3.0), 笔数); 自检不过 ⇒ None (该子块作废)。

    ⚠️ **`narrow`/`wide` 必须**单独算**出来, 不能写成 `base ∓ S`** ——
    `S = wide − narrow` 是一个**增量**, 而 `base` 是**水平**;
    `Σ` 对 tp 不是线性的 ⇒ `base − S ≠ narrow`。第一版把它打错了 (差 20 万–140 万)。
    """
    if len(tr) == 0:
        return None
    if not _self_check(_build_df(bars_by_code, tr, preset), f"{win}{label}", quiet=True):
        return None
    tp, sl, mh = float(preset["tp_pct"]), float(preset["sl_pct"]), int(preset["max_hold"])
    base, _, top3, n = _policy_stats(bars_by_code, tr, tp, sl, mh)
    wide = _policy_stats(bars_by_code, tr, tp * 3.0, sl, mh)[0]
    narrow = _policy_stats(bars_by_code, tr, tp * 0.5, sl, mh)[0]
    return (top3 / base if base else float("nan"), wide - narrow, base, narrow, wide, n)


def _all_windows(family: str, preset_name: str, split: int = 0) -> int:
    """§13.202(g) 的**可证伪推论**: 「宽 TP 受益多少」应由该窗的**尾部集中度**决定。

    逐窗在**基线政策**下量两个量 (全在同一批入场、同一批股数上):
      `T` = top-3 Σ ÷ Σ        (尾部集中度)
      `S` = Σ(tp×3.0) − Σ(tp×0.5)   (宽减窄; >0 ⇒ 该窗要宽)
    机理预测: **T 高的窗 S 应当为正、T 低的窗 S 为负 ⇒ 按 T 排序与按 S 排序同序。**

    `split=N>0` 时 (§13.204): 把每窗的入场按 `entry_date` 切成 N 个**连续块**, **逐块**算 `T`/`S`
    —— 这不需要任何额外模拟 (反事实把入场固定住了 ⇒ 任意子集都能重算),
    用来问「`S` 的符号是**时期性质**还是**成交层特异**」。
    ⚠️ 切块后 n 很小 ⇒ 每行都**带着笔数**读; 且这是**同一个窗内的子样本**, 不是新窗、不是样本外。

    ⚠️ **每个窗都过一遍 §13.199 的自检**; 任何一窗复现不了基线 ⇒ 该窗作废 (不静默略过)。
    ⚠️ 独立单位: `IND` 与 `IS2` 时间**重叠** ⇒ 有效独立单位 ≈ 4 而非 5 (§13.192)。
    """
    print(f"\n=== --all-windows: {family} / {preset_name}"
          + (f"  (split={split})" if split else "") + " ===")
    print(f"  {'窗口':<7}{'笔数':>5}{'基线毛 Σ':>14}{'T=top3/Σ':>11}"
          f"{'Σ(tp×0.5)':>14}{'Σ(tp×3.0)':>14}{'S=宽−窄':>14}{'符号':>7}")
    rows, dead, flip_wins = [], [], []
    for win, (w0, w1) in WINDOWS.items():
        preset, panel, res = _load(family, preset_name, w0, w1)
        tr = pd.DataFrame(res["trades"]).copy()
        if len(tr) == 0:
            print(f"  {win:<7}  无成交 ⇒ 跳过"); continue
        tr["entry_date"] = pd.to_datetime(tr["entry_date"])
        tr["exit_date"] = pd.to_datetime(tr["exit_date"])
        bars_by_code = {c: s.reset_index(drop=True)
                        for c, s in panel.groupby("thscode", sort=False)}

        if not split:
            r = _stats_row(win, "", bars_by_code, tr, preset)
            if r is None:
                dead.append(win); continue
            T, S, base, narrow, wide, n = r
            rows.append((win, n, base, T, S))
            print(f"  {win:<7}{n:>5}{base:>+14,.0f}{T:>11.1%}"
                  f"{narrow:>+14,.0f}{wide:>+14,.0f}{S:>+14,.0f}{'宽' if S > 0 else '窄':>7}")
            continue

        # --- split 模式: 窗内切成连续块, 逐块算 ---
        tr = tr.sort_values("entry_date").reset_index(drop=True)
        whole = _stats_row(win, "整窗", bars_by_code, tr, preset)
        if whole is None:
            dead.append(win); continue
        bounds = [int(round(i * len(tr) / split)) for i in range(split + 1)]
        signs, blk = [], []
        for b in range(split):
            seg = tr.iloc[bounds[b]:bounds[b + 1]]
            r = _stats_row(win, f"#{b + 1}", bars_by_code, seg, preset)
            if r is None:
                continue
            T, S, base, narrow, wide, n = r
            signs.append(1 if S > 0 else -1)
            blk.append((b + 1, n, base, T, narrow, wide, S,
                        f"{str(seg['entry_date'].iloc[0])[:10]}..{str(seg['entry_date'].iloc[-1])[:10]}"))
            rows.append((f"{win}#{b + 1}", n, base, T, S))
        if len(blk) < 2:
            dead.append(win); continue
        flipped = len(set(signs)) > 1
        if flipped:
            flip_wins.append(win)
        for b, n, base, T, narrow, wide, S, span in blk:
            print(f"  {win+'#'+str(b):<7}{n:>5}{base:>+14,.0f}{T:>11.1%}"
                  f"{narrow:>+14,.0f}{wide:>+14,.0f}{S:>+14,.0f}"
                  f"{'宽' if S > 0 else '窄':>7}   {span}")
        # ★ 免费的一致性检查: `S` 是**逐笔 P&L 之差的和** ⇒ 对**不相交**的入场子集**可加**
        #   ⇒ 三个块的 `S` 必须**精确**加回整窗的 `S`。不对 ⇒ 分块或重放写错了。
        win_S = sum(x[6] for x in blk)
        ok_add = abs(win_S - whole[1]) < 1.0
        print(f"  {'':<7}⇒ 该窗内 `S` 的符号 **{'变号' if flipped else '稳定'}**"
              f"  · 三块 S 合计 {win_S:>+14,.0f} vs 整窗 {whole[1]:>+14,.0f}"
              f"  ⇒ 可加性自检 **{'过' if ok_add else '⛔ **不过** (分块或重放写错了)'}**")
    if dead:
        print(f"  ⛔ 自检未过的窗**作废**: {dead}")

    if split:
        tot = len({r[0].split('#')[0] for r in rows})
        print(f"\n  ⇒ **{len(flip_wins)}/{tot} 个窗在自己的子样本里就变号**: {flip_wins}")
        print("""  读法: 若 `S` 是**时期性质**, 同一窗的子块应当同号。变号 ⇒ 它是**成交层特异**。
  ⚠️ 每块 n 很小 (见笔数列) ⇒ 只作**一致性检查**; 且子样本不是新窗, 不是样本外。""")
        return 0

    ok = [r for r in rows if r[3] == r[3]]
    by_T = [r[0] for r in sorted(ok, key=lambda r: r[3])]
    by_S = [r[0] for r in sorted(ok, key=lambda r: r[4])]
    print(f"\n  按 T (尾部集中度) 升序: {by_T}")
    print(f"  按 S (宽−窄)      升序: {by_S}")
    print(f"  ⇒ 两个排序**同序**? **{'是' if by_T == by_S else '否'}**"
          f"  ({len(ok)} 个窗; ⚠️ `IND`/`IS2` 重叠 ⇒ 有效独立单位 ≈ {len(ok) - 1})")
    n_pos = sum(1 for r in ok if r[4] > 0)
    n_hiT = sum(1 for r in ok if r[3] > 0)
    print(f"  ⇒ S>0 的窗 **{n_pos}/{len(ok)}** · T>0 的窗 **{n_hiT}/{len(ok)}**")
    print("""  读法: 机理说「T 高 ⇒ 要宽」。同序 = 支持; 乱序 = 该机理**降级为对两窗的事后描述**。
  ⚠️ 排序一致在 4 个单位上是很弱的检验 ⇒ 只作**一致性检查**, 不当作"证明了机理"。""")
    return 0


# `--grid` 的取值 (都是基线倍数; 1.0 那一格 = 基线, 有自检)。
GRID_MULT = (0.5, 0.75, 1.0, 1.5, 2.0)


def _grid(family: str, preset_name: str) -> int:
    """★ 这条线的**最终形态问题**: 在同一批入场上, 存不存在一个**单一的** (tp, sl),
    在**多数窗**上都比基线好?  (§13.206)

    做法: 每窗跑 5×5 网格 (各为基线倍数; 1.0/1.0 = 基线, 过自检),
    对每格数"它在几个窗上严格超过基线", **只报这个计数的分布**。

    ⚠️ **只报分布, 不报"哪一格最好"** (§5: 跨窗挑出最优 = 样本内择优);
    且 §8.1 已说样本外预算用尽 ⇒ 即便有格 ≥4/5 也**只能登记, 不能采用**。
    ⚠️ `IND`/`IS2` 时间重叠 ⇒ 有效独立单位 ≈ 4 (§13.192)。
    """
    print(f"\n=== --grid: {family} / {preset_name} (5×5 (tp,sl) 网格, 同一批入场; {'净(含费)' if NET else '毛'}) ===")
    per_win: dict[str, dict[tuple[float, float], float]] = {}
    base_sig: dict[str, float] = {}
    for win, (w0, w1) in WINDOWS.items():
        preset, panel, res = _load(family, preset_name, w0, w1)
        tr = pd.DataFrame(res["trades"]).copy()
        if len(tr) == 0:
            print(f"  {win}: 无成交 ⇒ 跳过"); continue
        tr["entry_date"] = pd.to_datetime(tr["entry_date"])
        tr["exit_date"] = pd.to_datetime(tr["exit_date"])
        bars_by_code = {c: s.reset_index(drop=True)
                        for c, s in panel.groupby("thscode", sort=False)}
        row = _stats_row(win, "", bars_by_code, tr, preset)   # ← 这里过自检
        if row is None:
            print(f"  {win}: ⛔ 自检未过 ⇒ **作废**"); continue
        _T, _S, base, _narrow, _wide, n = row
        tp, sl, mh = float(preset["tp_pct"]), float(preset["sl_pct"]), int(preset["max_hold"])
        cells = {}
        for mt in GRID_MULT:
            for ms in GRID_MULT:
                cells[(mt, ms)] = _policy_stats(bars_by_code, tr, tp * mt, sl * ms, mh)[0]
        # 免费内检①: (1.0, 1.0) 必须**恰**等于基线
        assert abs(cells[(1.0, 1.0)] - base) < 1.0, (win, cells[(1.0, 1.0)], base)
        # 免费内检②(仅 --net): 我算的费 vs 引擎自己的口径差 (final_equity vs 毛基线)
        if NET:
            gross = _policy_stats(bars_by_code, tr, tp, sl, mh, net=False)[0]
            engine_net = float(res["metrics"]["final_equity"]) - 1_000_000.0
            mine = gross - base
            print(f"  {win:<6} 费用核对: 我算 {mine:>+10,.0f} · 引擎口径差 {gross - engine_net:>+10,.0f}"
                  f" · 比 {mine / (gross - engine_net) if (gross - engine_net) else float('nan'):.2f}×")
        per_win[win] = cells
        base_sig[win] = base
        beat = sum(1 for v in cells.values() if v > base)
        print(f"  {win:<6} n={n:>3} 基线{'毛' if not NET else '净'} Σ={base:>+12,.0f} | "
              f"25 格里**超过基线**的 {beat:>2} 格 · 其中 Σ>0 的 "
              f"{sum(1 for v in cells.values() if v > 0):>2} 格  ✅自检过")

    if len(per_win) < 2:
        print("  ⛔ 可用窗不足 ⇒ 不作结论"); return 1

    print(f"\n  === 每一格「在几个窗上严格超过基线」的分布 ===")
    counts = []
    for cell in [(mt, ms) for mt in GRID_MULT for ms in GRID_MULT]:
        c = sum(1 for w_, cs in per_win.items() if cs[cell] > base_sig[w_])
        counts.append(c)
    from collections import Counter
    hist = Counter(counts)
    for k in sorted(hist):
        print(f"    超过 {k} 个窗的格子: **{hist[k]:>2}** 个  {'#' * hist[k]}")
    nw = len(per_win)
    print(f"  ⇒ **最大计数 = {max(counts)}/{nw}** (有效独立单位 ≈ {nw - 1})")
    print(f"  ⇒ 没有任何一格超过 {max(counts)} 个窗" +
          ("" if max(counts) < nw else "  ⚠️ 存在满贯格 ⇒ 但那是**跨窗挑出来的**, 属样本内择优 (§5), "
                                          "且 §8.1 样本外预算已用尽 ⇒ **只能登记, 不能采用**"))
    print("""  读法: 这是**描述**, 不是选择 —— 本工具**不报**哪一格最好。
  ⚠️ 计数的分母只有 5 个 (有效 ≈ 4); 且格与格之间**不独立** (tp/sl 网格相邻格相关)。""")
    return 0


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
    ap.add_argument("--all-windows", action="store_true",
                    help="五个窗逐个跑: 量「尾部集中度 T」与「宽减窄 S」, 查机理预测 (同序?)")
    ap.add_argument("--net", action="store_true",
                    help="扣规范费用 (core.dual_price: 双边佣金含 ¥5 地板 + 卖出印花税); "
                         "股数仍固定在基线那一档")
    ap.add_argument("--grid", action="store_true",
                    help="★ 最终形态问题: 同一批入场上 5x5 (tp,sl) 网格, 数每格在几个窗上超过基线 "
                         "(只报计数的分布, 不报哪一格最好)")
    ap.add_argument("--split", type=int, default=0,
                    help="配合 --all-windows: 把每窗入场按时间切成 N 个连续块, 逐块算 T/S "
                         "(零额外模拟; 用来问 S 的符号是时期性质还是成交层特异)")
    args = ap.parse_args()

    global NET
    NET = bool(args.net)
    if NET:
        print("⚠️ `--net`: 已扣规范费用 (core.dual_price); 股数**仍固定在基线那一档** ⇒ "
              "与引擎 `final_equity` 仍不是同一个量。\n")

    if args.grid:
        preset_name = args.preset or DEFAULTS["uptrend_pullback"][0]
        return _grid(args.family, preset_name)

    if args.all_windows:
        preset_name = args.preset or DEFAULTS["uptrend_pullback"][0]
        return _all_windows(args.family, preset_name, split=args.split)

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
