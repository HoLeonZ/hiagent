"""进场侧隔夜跳空的**超额** —— 信号日收盘 → T+1 开盘 (§13.137)。

为什么这个轴值得单列
------------------
§13.134–136 把**出场**侧的跳空查透了 (跳空穿价占止损出场的 20–57%)。
**进场侧的同款从来没有量过** —— 而信号在 T 日**收盘**发出、成交在 T+1 **开盘**,
中间那**一整个隔夜跳空**是白送的还是白丢的, 决定了这条执行链的一半。

⚠️ 必须带**同构造对照**, 否则会把 market drift 当成 edge:
全市场每天本身也有隔夜跳空 (本库 W2 期等权均值 −0.046%)。对照口径 =
与策略**同日**的全市场等权隔夜跳空 (`raw_kline_daily.open / LAG(close) − 1`, 按日取等权平均)。
> 这与 §6.3 那条"任何前向收益结论都必须与同构造的市场对照一起给出"是同一条纪律。

口径
----
* 两侧都用 **raw 价** (§3 双价格系统: 执行走 raw);
* 信号日 = 入场日的前一个交易日 ⇒ 用 `LAG(close)` 在同一序列上取, 不用 `prev_close` 列
  (那列 100% NULL, §13.106 的坑);
* 符号: **负 = 你买得比信号日收盘更便宜 = 对你有利**。

用法:
    python3 tools/entry_gap_attribution.py
    python3 tools/entry_gap_attribution.py --preset v33_long_reverse_v22 --w0 2017-10-02 --w1 2019-09-30
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

from hiagent_config import DB_PATH  # noqa: E402

from uptrend_pullback.backtest import run_backtest  # noqa: E402
from uptrend_pullback.data import load_panel  # noqa: E402
from uptrend_pullback.presets import get_preset  # noqa: E402
from uptrend_pullback.signals import compute_indicators  # noqa: E402
from uptrend_pullback.universe import load_universe  # noqa: E402

WINDOWS: tuple[tuple[str, str, str], ...] = (
    ("W2", "2024-10-08", "2026-09-18"),      # 末日按 §13.8 截到干净日
    ("IND", "2022-10-03", "2024-09-30"),
    ("IS1", "2021-10-01", "2022-09-30"),
    ("IS2", "2023-10-01", "2024-09-30"),
    ("EXTRA", "2017-10-02", "2019-09-30"),
)


def _gaps(con, w0: str, w1: str) -> pd.DataFrame:
    return con.execute("""
      WITH r AS (SELECT thscode, date, open,
                        LAG(close) OVER (PARTITION BY thscode ORDER BY date) pc
                 FROM raw_kline_daily WHERE date BETWEEN ?::DATE - 90 AND ?)
      SELECT thscode, date, open / pc - 1.0 AS g
      FROM r WHERE pc IS NOT NULL AND open > 0
      ORDER BY thscode, date""", [w0, w1]).df()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    # ⚠️ 留空 ⇒ 由所选的族取它自己的默认 preset (各族 preset 名不通用)
    ap.add_argument("--preset", default="")
    ap.add_argument("--w0", default="")
    ap.add_argument("--w1", default="")
    ap.add_argument("--family", default="uptrend_pullback",
                    help="uptrend_pullback / chase_up / short_reversal / cycle_price_action")
    args = ap.parse_args()

    con = duckdb.connect(str(DB_PATH), read_only=True)
    # 四族适配器 (§13.135): 各族成交记录形状不同, 且**空头的有利方向相反**
    import gap_stop_attribution_4engine as G
    if args.family != "uptrend_pullback":
        return _four_engine(args, con)
    p = get_preset(args.preset or "v33_long_reverse_v22")
    wins = ((("ONE", args.w0, args.w1),) if args.w0 and args.w1 else WINDOWS)
    print(f"preset={args.preset}   (负 = 买得比信号日收盘更便宜 = 有利)\n")
    print(f"{'窗口':<6} {'n':>4} {'策略隔夜':>10} {'同日市场':>10} {'**超额**':>10} "
          f"{'t':>7} {'为负(有利)':>10}")
    pooled = []
    for label, w0, w1 in wins:
        uni = set(load_universe(p["universe"], DB_PATH, asof_date=w0))
        pan = compute_indicators(load_panel(DB_PATH, w0, w1, universe=uni))
        t = run_backtest(dict(p), w0, w1, DB_PATH, panel_ind=pan)["trades"].copy()
        del pan
        if len(t) == 0:
            print(f"{label:<6} 无成交"); continue
        t["entry_date"] = pd.to_datetime(t["entry_date"])
        q = _gaps(con, w0, w1)
        q["date"] = pd.to_datetime(q["date"])
        byd = q.groupby("date")["g"].mean()
        m = t.merge(q, left_on=["entry_date", "thscode"],
                    right_on=["date", "thscode"], how="left").dropna(subset=["g"])
        ex = (m["g"] - m["entry_date"].map(byd)).to_numpy(float)
        pooled.append(ex)
        tt = ex.mean() / (ex.std(ddof=1) / np.sqrt(len(ex))) if len(ex) > 2 else float("nan")
        print(f"{label:<6} {len(m):>4} {m['g'].mean():>+10.3%} "
              f"{m['entry_date'].map(byd).mean():>+10.3%} {ex.mean():>+10.3%} {tt:>+7.2f} "
              f"{int((ex < 0).sum()):>5}/{len(ex)}")
    if len(pooled) > 1:
        allx = np.concatenate(pooled)
        tt = allx.mean() / (allx.std(ddof=1) / np.sqrt(len(allx)))
        print(f"\n合并: n={len(allx)}  超额均值 **{allx.mean():+.3%}**  t=**{tt:+.2f}**  "
              f"为负(有利) {int((allx < 0).sum())}/{len(allx)}")
    print("""
读法: **负的超额 = 把成交推迟到 T+1 开盘, 比在信号日收盘买更便宜。**
      这是**真实的成交价改进** (同样的股票买得更低), 但它**不是预测能力的证据** ——
      它是"在回调信号上延迟到次日开盘"这条入场规则的性质。
⚠️ 未做: 它对本 preset 之外的族/ preset 的同款检验; 也未把 TP/SL 锚定在滑点后入场价
      (§13.129) 的交互算进来。""")


def _four_engine(args, con) -> None:
    """四族通用: 用 §13.135 的适配器拿成交, 再算**超额隔夜跳空**。

    ⚠️ **空头的有利方向相反**: `short_reversal` 的"入场"是在 T+1 开盘**卖出**
    ⇒ 卖得更**高**才有利 ⇒ **正号 = 有利**。下表按各族的方向解释。
    """
    import gap_stop_attribution_4engine as G
    fam = args.family
    preset = args.preset or G.DEFAULTS[fam]
    p, t, direction = G.ADAPTERS[fam](preset, args.w0 or G.W0_DEFAULT,
                                      args.w1 or G.W1_DEFAULT)
    if t is None or len(t) == 0:
        print(f"{fam}: 无成交"); return
    w0 = args.w0 or G.W0_DEFAULT
    w1 = args.w1 or G.W1_DEFAULT
    t = t.copy()
    t["entry_date"] = pd.to_datetime(t["entry_date"])
    q = _gaps(con, w0, w1)
    q["date"] = pd.to_datetime(q["date"])
    byd = q.groupby("date")["g"].mean()
    m = t.merge(q, left_on=["entry_date", "thscode"],
                right_on=["date", "thscode"], how="left").dropna(subset=["g"])
    ex = (m["g"] - m["entry_date"].map(byd)).to_numpy(float)
    tt = ex.mean() / (ex.std(ddof=1) / np.sqrt(len(ex))) if len(ex) > 2 else float("nan")
    side = "多头(买) ⇒ **负=有利**" if direction > 0 else "空头(卖) ⇒ **正=有利**"
    print(f"family={fam}  preset={preset}")
    print(f"  方向: {side}")
    print(f"  n={len(m)}  策略隔夜 {m['g'].mean():+.3%}  同日市场 "
          f"{m['entry_date'].map(byd).mean():+.3%}  **超额 {ex.mean():+.3%}**  t={tt:+.2f}")
    favor = int((ex < 0).sum()) if direction > 0 else int((ex > 0).sum())
    print(f"  **有利笔数 {favor}/{len(ex)}**")

    # ★★ 判别 (本节的关键): 「便宜」是**真收益**还是**逆向选择的标记**?
    # 只看跳空的符号与均值**分不出**这两者 —— 要看**跳空与结果的关系**。
    # 判别法: 按超额跳空的中位数把成交切两半, 比两半的净收益。
    if "net_return" in m.columns and len(m) >= 8:
        ret = m["net_return"].astype(float)
        med = float(np.median(ex))
        cheaper = ret[ex <= med]      # 多头: 跳空越低 = 买得越便宜
        dearer = ret[ex > med]
        if direction < 0:             # 空头: 跳空越高 = 卖得越贵 = 有利
            cheaper, dearer = dearer, cheaper
        r = float(np.corrcoef(ex, ret)[0, 1])
        # ⚠️ 判语必须**按方向**说: 多头是"买得便宜", 空头是"卖得贵" ——
        # 本工具第一版对空头也打"便宜是真收益" ⇒ **用多头的词说空头的事** (已修)。
        gain = "买得便宜" if direction > 0 else "卖得贵"
        verdict = (f"**{gain}是真收益**" if cheaper.mean() > dearer.mean()
                   else f"**{gain}是逆向选择的标记**")
        print(f"  按超额跳空切两半 → **更有利的一半 ({gain})** 净收益 {cheaper.mean():+.2%} "
              f"(n={len(cheaper)})  vs 另一面 {dearer.mean():+.2%} (n={len(dearer)})")
        print(f"  corr(超额跳空, 净收益) = {r:+.2f}  ⇒ {verdict}")


if __name__ == "__main__":
    main()
