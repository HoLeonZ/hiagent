"""四族**执行通道对照表** —— 把 §13.134–140 的读数并到一处 (§13.141)。

四条通道 (全部在 W2, 全部用 **raw 价**, 信号日由 `LAG(close)` 自建):
  ① **进场超额跳空**   策略的 (开盘/前收 − 1) 减 **同日**全市场等权 (负=多头买得便宜)
  ② **出场跳空占比**   止损出场里"填在开盘价而非止损位"的比例 (§13.134)
  ③ **费用**           Σ fees / 初始本金
  ④ **出场跳空成本**   Σ(设计止损位 − 实际成交价)×股数 (§13.134)

⚠️ 口径与可比性 (这张表最容易出错的地方)
---------------------------------------
* ① 是**逐笔比率**; ② 是**比例**; ③④ 是**元** ⇒ **不要拿①与④相加**;
  要相加就走 `tools/execution_legs_accounting.py` (它把两条腿都换成元、同路径同股数)。
* `cycle_price_action` 的成交是**逐票百万账户** (§13.125a) ⇒ 它的 ③④ **与另三族不同尺度**,
  本工具对 cycle **只报 ① 与 ②**, 并把 ③④ 标成"不可比"。
* 各族 preset 名不通用 ⇒ `--preset` 留空时按族取默认。

用法:
    python3 tools/execution_channel_matrix.py                 # 四族, 用各自默认 preset
    python3 tools/execution_channel_matrix.py --families chase_up,uptrend_pullback
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from hiagent_config import DB_PATH  # noqa: E402

# §13.90: 本工具**并列四族** ⇒ 静态导入各族 METRICS_BASIS 并披露 (不走豁免)
from chase_up.backtest import METRICS_BASIS as _BASIS_CHASE  # noqa: E402
from cycle_price_action.allocator import METRICS_BASIS as _BASIS_CYCLE  # noqa: E402
from short_reversal.engine import METRICS_BASIS as _BASIS_SHORT  # noqa: E402
from uptrend_pullback.backtest import METRICS_BASIS as _BASIS_UPTREND  # noqa: E402

import gap_stop_attribution_4engine as G  # noqa: E402

_BASIS = {"chase_up": lambda: dict(_BASIS_CHASE),
          "uptrend_pullback": lambda: dict(_BASIS_UPTREND),
          "short_reversal": lambda: dict(_BASIS_SHORT),
          "cycle_price_action": lambda: dict(_BASIS_CYCLE)}
INITIAL = 1_000_000.0


def _gaps(con, w0: str, w1: str) -> pd.DataFrame:
    return con.execute("""
      WITH r AS (SELECT thscode, date, open,
                        LAG(close) OVER (PARTITION BY thscode ORDER BY date) pc
                 FROM raw_kline_daily WHERE date BETWEEN ?::DATE - 90 AND ?)
      SELECT thscode, date, open / pc - 1.0 AS g
      FROM r WHERE pc IS NOT NULL AND open > 0
      ORDER BY thscode, date""", [w0, w1]).df()


def _row(fam: str, preset: str, w0: str, w1: str, con) -> dict:
    p, t, direction = G.ADAPTERS[fam](preset, w0, w1)
    if t is None or len(t) == 0:
        return {}
    t = t.copy()
    t["entry_date"] = pd.to_datetime(t["entry_date"])

    # ① 进场超额跳空
    q = _gaps(con, w0, w1)
    q["date"] = pd.to_datetime(q["date"])
    byd = q.groupby("date")["g"].mean()
    m = t.merge(q, left_on=["entry_date", "thscode"],
                right_on=["date", "thscode"], how="left").dropna(subset=["g"])
    ex = (m["g"] - m["entry_date"].map(byd)).to_numpy(float)
    entry_ex = float(ex.mean()) if len(ex) else float("nan")
    entry_t = (float(ex.mean() / (ex.std(ddof=1) / np.sqrt(len(ex))))
               if len(ex) > 2 else float("nan"))

    # ② 出场跳空占比  +  ④ 跳空成本
    use_atr = p.get("atr_tp_mult") is not None and p.get("atr_sl_mult") is not None
    if use_atr and "atr_pct" in t.columns:
        sl_eff = t["atr_pct"].astype(float) * float(p["atr_sl_mult"])
        sl_des = t["entry_price"] * (1 - direction * sl_eff)
    else:
        sl_des = t["entry_price"] * (1 - direction * float(p.get("sl_pct", 0.0)))
    if (t["exit_reason"].astype(str) != "").any():
        sl = t[t["exit_reason"] == "SL"].copy()
    else:
        sl = t[t["exit_price"] <= sl_des + 1e-9].copy()
    gap_frac = float("nan"); gap_cost = float("nan")
    if len(sl):
        isgap = ((sl["exit_price"] < sl_des.loc[sl.index] - 1e-9) if direction > 0
                 else (sl["exit_price"] > sl_des.loc[sl.index] + 1e-9))
        gap_frac = float(isgap.mean())
        gap_cost = float((((sl_des.loc[sl.index] - sl["exit_price"]) * sl["size"]).abs()
                          [isgap]).sum())
    # ⚠️ cycle 的适配器**没有 `fees` 列** (它的 TradeRecord 只有 pnl) ——
    # 本工具第一版在这里直接 `t["fees"]` ⇒ **KeyError 崩掉整行** (实测)。
    # 缺列 ⇒ 打 NaN, 而不是崩 (§0: 拿不到就明说, 不要静默或崩溃)。
    fees = float(t["fees"].sum()) if "fees" in t.columns else float("nan")
    return {"n": len(t), "entry_ex": entry_ex, "entry_t": entry_t,
            "gap_frac": gap_frac, "gap_cost": gap_cost,
            "fees": fees, "net": float(t["net_pnl"].sum())}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--families", default="uptrend_pullback,chase_up,short_reversal,cycle_price_action")
    ap.add_argument("--preset", default="")
    ap.add_argument("--w0", default=G.W0_DEFAULT)
    ap.add_argument("--w1", default=G.W1_DEFAULT)
    args = ap.parse_args()
    fams = [x.strip() for x in args.families.split(",") if x.strip()]

    print(f"窗口 {args.w0}..{args.w1}\n=== 口径披露 (§13.13/§13.90) ===")
    for f in fams:
        print(f"  {f:<22} {_BASIS[f]()}")
    print("  ⚠️ ①是**逐笔比率**, ②是**比例**, ③④是**元** ⇒ ①不能与④相加;\n"
          "     要相加请走 tools/execution_legs_accounting.py (同为元、同路径同股数)。\n")

    con = duckdb.connect(str(DB_PATH), read_only=True)
    print(f"{'族':<20} {'方向':<10} {'n':>6} {'①进场超额':>10} {'t':>7} "
          f"{'②出场跳空':>10} {'③费用%':>8} {'④跳空成本':>13} {'净利':>13}")
    for fam in fams:
        preset = args.preset or G.DEFAULTS[fam]
        try:
            _p, _t, d = G.ADAPTERS[fam](preset, args.w0, args.w1)
            r = _row(fam, preset, args.w0, args.w1, con)
        except Exception as e:  # noqa: BLE001
            print(f"{fam:<20} **{type(e).__name__}: {str(e)[:50]}**"); continue
        if not r:
            print(f"{fam:<20} (无成交)"); continue
        perstock = (fam == "cycle_price_action")
        fav = "负=有利" if d > 0 else "正=有利"
        print(f"{fam:<20} {('多' if d > 0 else '空')+'('+fav+')':<10} {r['n']:>6} "
              f"{r['entry_ex']:>+10.3%} {r['entry_t']:>+7.2f} {r['gap_frac']:>10.0%} "
              f"{(r['fees']/INITIAL if not perstock else float('nan')):>8.2%} "
              f"{(r['gap_cost'] if not perstock else float('nan')):>+13,.0f} "
              f"{(r['net'] if not perstock else float('nan')):>+13,.0f}")
    print("""
⚠️ cycle 的 ③④ 打 NaN: 它的成交是**逐票百万账户** (§13.125a) ⇒ 与另三族**不同尺度**, 不可比。
⚠️ cycle 的 ① 的 t 也不可引用 (逐票且同日高度相关 ⇒ 有效独立单位是**日期数**, 本册已记过该坑)
   ⇒ 该行**只看幅度**。
读法: 四条通道**回答不同的问题**, 并排放只是为了让"哪一族在哪一段吃亏"一眼可见;
      它们**不构成一个可以求和的分数**。""")


if __name__ == "__main__":
    main()
