"""当前最优在**滚动 24 个月窗口**上的分布 (§13.131)。

为什么需要
----------
§7.16 的教训: 横截面线看上去的"两个时代"(先亏五年再赚四年), 换成**滚动窗**一看
并不是台阶, 而是 **1–2 年周期的振荡** ⇒ **改变了失败的理由**。
而本族 (四个 preset 族) **至今只看过 5 个固定窗口** ⇒ 分不清
「W2 是一个孤立高点」还是「一次振荡的相位」。本工具补这一段。

方法: 24 个月窗, 步长 6 个月, 从最早可用起点跑到history尾;
每窗报 总收益 / **同宇宙等权基准** / 超额 / 笔数。

⚠️ **纯描述**: 不设阈值、不选参、**不排名** (§5)。它不产生新主张,
   只给已有主张补上"时间上的分布"这一维。

⚠️ 边界: 窗与窗**互相重叠** (步长 6 个月 < 窗长 24 个月) ⇒ 相邻两窗**不是独立样本**,
   "2/14 为正"不能当 14 次独立试验读。
   末窗截到 §13.8 的干净日。

用法:
    python3 tools/rolling_window_stability.py
    python3 tools/rolling_window_stability.py --months 12 --step 3
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from uptrend_pullback.presets import get_preset  # noqa: E402

import attribute_uptrend_selection as AT  # noqa: E402

START_FLOOR = "2017-10-02"   # 暖机够的最早起点 (DB 起 2016-09-02 + 400 天)
END_CAP = "2026-09-18"       # §13.8 的最后一个干净日


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--preset", default="v33_long_reverse_v22")
    ap.add_argument("--months", type=int, default=24)
    ap.add_argument("--step", type=int, default=6)
    ap.add_argument("--drop-best", type=int, default=0,
                    help="同时报「去掉本窗最好 k 笔」后的超额 (依赖恒等式 末值=初值+Σnet_pnl)")
    args = ap.parse_args()

    p = get_preset(args.preset)
    starts = pd.date_range(START_FLOOR, END_CAP, freq=f"{args.step}MS")
    print(f"preset = {args.preset}   滚动 {args.months} 个月窗, 步长 {args.step} 个月, "
          f"共 {len(starts)} 窗   末窗截到 {END_CAP}")
    extra = f" {'去最好'+str(args.drop_best)+'超额':>14}" if args.drop_best else ""
    print(f"{'起始':<12} {'终止':<12} {'总收益':>10} {'等权基准':>10} {'超额':>10} "
          f"{'笔数':>5}{extra}")

    rows, dropped = [], []
    for s in starts:
        w0 = s.strftime("%Y-%m-%d")
        full_end = s + pd.DateOffset(months=args.months)
        w1 = min(full_end.strftime("%Y-%m-%d"), END_CAP)
        # ⚠️ 末窗会被 END_CAP 截短 —— 而**不同长度的窗口不可比**。
        # 本工具第一版把它们一并混进分布里, 打出了 "6/18 为正" 这个**长度的产物**
        # (末几个窗只有 4.5–16.5 个月, 恰好都在上涨段)。现要求 ≥ 90% 的请求长度。
        got = (pd.Timestamp(w1) - s).days / 30.44
        if got < 0.90 * args.months:
            dropped.append((w0, w1, round(got, 1)))
            continue
        try:
            r = AT._one_window(p, w0, w1)
        except Exception as e:  # noqa: BLE001
            print(f"{w0:<12} {w1:<12} **{type(e).__name__}: {str(e)[:36]}**")
            continue
        exc = r["total_return"] - r["benchmark"]
        dem = float("nan")
        if args.drop_best and len(r["net_pnl"]):
            pnl = np.sort(r["net_pnl"])[::-1]
            kept = float(pnl.sum()) - float(pnl[:args.drop_best].sum())
            dem = kept / 1_000_000.0 - r["benchmark"]
        rows.append((w0, w1, r["total_return"], r["benchmark"], exc, r["n_trades"], dem))
        col = f" {dem:>+14.2%}" if args.drop_best else ""
        print(f"{w0:<12} {w1:<12} {r['total_return']:>+10.2%} {r['benchmark']:>+10.2%} "
              f"{exc:>+10.2%} {r['n_trades']:>5}{col}", flush=True)

    if dropped:
        print(f"\n⚠️ 跳过 {len(dropped)} 个被 END_CAP 截短的窗 (不足请求长度的 90%, 不可比): "
              + ", ".join(f"{a}→{b}({m}m)" for a, b, m in dropped))
    if not rows:
        return
    exc = np.array([x[4] for x in rows])
    tr = np.array([x[2] for x in rows])
    print("\n=== 分布 ===")
    print(f"  超额: 为正 {int((exc > 0).sum())}/{len(exc)} 窗; 中位 {np.median(exc):+.2%}; "
          f"均值 {exc.mean():+.2%}; 极差 {exc.min():+.2%}..{exc.max():+.2%}")
    print(f"  总收益: 为正 {int((tr > 0).sum())}/{len(tr)} 窗; 中位 {np.median(tr):+.2%}")
    if args.drop_best:
        exc2 = np.array([x[6] for x in rows])
        print(f"  **去掉最好 {args.drop_best} 笔后**: 超额为正 "
              f"{int((exc2 > 0).sum())}/{len(exc2)} 窗; 中位 {np.nanmedian(exc2):+.2%}; "
              f"极差 {np.nanmin(exc2):+.2%}..{np.nanmax(exc2):+.2%}")
    print(f"  超额符号变号 {int((np.sign(exc)[1:] != np.sign(exc)[:-1]).sum())} 次 "
          f"/ {len(exc)-1} 个相邻对")
    print("""
读法: 相邻窗**互相重叠** ⇒ 不是独立试验, 不能把"n 为正"当二项计数读。
     本工具只回答一件事: **那个固定的 5 窗结论, 在时间轴上长什么样。**""")


if __name__ == "__main__":
    main()
