"""§10 异质性轴的**判别**: [4%+) 那一档的 −1% 到底是什么。

## 为什么必须判别 (§7.3/§7.10/§7.13 都栽过: "第一次查看"是伪影的藏身处)
曲线几乎全由 `[4%+)` 这条细尾贡献, 且对该档与股息率**高度线性** (r≈−0.93)。两条互斥解释:

* **H_adj** (复权残差): 后复权因子在除权日有系统性残差 ⇒ 机械跳空没被完全消掉 ⇒ 纯口径伪影;
* **H_price** (分母伪影): 股息率 = 分红 / **T−1 收盘**。股价崩塌的票, 同样的分红会显得"股息率极高"
  ⇒ `[4%+)` 其实是**困境股/低价股**代理 ⇒ 负超额是那些票本来就差, 与除权无关。

## ★ 预登记判别法 (看数之前定下)
**判别 1 — 复权恒等式 (直接测 H_adj)**
对每笔事件算 `r_adj` (来自 `v_daily_hfq`) 与 `r_raw_div = (raw_close_T + D)/raw_close_{T−1} − 1`。
复权正确 ⇒ 两者相等。
* 中位 |差| **< 0.10pp** ⇒ **H_adj 被否** ⇒ 后面测到的是**真实经济收益**;
* 中位 |差| ≥ 0.10pp ⇒ **§10 的测量被口径污染** ⇒ 比"关不关方向"严重得多 (§13 同类)。

**判别 2 — 价格分层 (§7.11 的同一手段)**
把全部事件按 **T−1 收盘价**分 5 层, **层内**比较 `[4%+)` 与 `<4%` 的超额。
若层内差异塌掉 ⇒ `[4%+)` 只是低价代理 (H_price); 若层内仍在 ⇒ 与价格无关。

**判别 3 — 换自变量: 用"每股分红**金额**"而非比率**
若效应跟着**比率**走而不跟**金额**走 ⇒ 指向分母伪影。
"""
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from pathlib import Path
import duckdb, numpy as np
from hiagent_config import DB_PATH

END = "2026-09-18"
PURE = "dividend_per_share > 0 AND per_share_bonus = 0 AND rights_ratio = 0"
con = duckdb.connect(str(DB_PATH), read_only=True)

BASE = f"""
WITH ev AS (SELECT DISTINCT e.thscode, e.ex_date, e.dividend_per_share AS D,
                   (SELECT max(r.date) FROM raw_kline_daily r
                     WHERE r.thscode=e.thscode AND r.date < e.ex_date) AS d0
            FROM raw_adjustment_events e
            WHERE e.ex_date BETWEEN ? AND ? AND {PURE}),
evy AS (SELECT ev.thscode, ev.ex_date, ev.D, ev.d0,
               r.close AS praw, r.volume AS vol,
               ev.D / r.close AS yld
        FROM ev JOIN raw_kline_daily r ON r.thscode=ev.thscode AND r.date=ev.d0
        WHERE r.close > 0),
p AS (SELECT thscode, date, close, LAG(close,1) OVER w AS c1 FROM v_daily_hfq
      WHERE date BETWEEN '2016-09-01' AND ? WINDOW w AS (PARTITION BY thscode ORDER BY date)),
m AS (SELECT date, avg(close/c1-1) AS mkt FROM p GROUP BY date),
j AS (SELECT evy.*, p.close/p.c1-1 AS r_adj, m.mkt,
             (SELECT r2.close FROM raw_kline_daily r2
               WHERE r2.thscode=evy.thscode AND r2.date=evy.ex_date) AS praw_T
      FROM evy JOIN p ON p.thscode=evy.thscode AND p.date=evy.ex_date
               JOIN m ON m.date=evy.ex_date
      WHERE evy.yld < 1)
SELECT thscode, ex_date, D, praw, praw_T, yld, r_adj, mkt,
       r_adj - mkt AS ex,
       (praw_T + D)/praw - 1 - r_adj AS adj_gap
FROM j WHERE praw_T IS NOT NULL
"""

df = con.execute(BASE, ["2016-10-01", END, END]).fetchdf().dropna()
print("=" * 80)
print(f"判别 1 —— 复权恒等式 (全部 {len(df)} 笔事件)")
print("=" * 80)
g = df.adj_gap.abs()
print(f"  |r_adj − r_raw_div| 的中位数 = {g.median():.5%};  p90 = {g.quantile(0.9):.5%};  "
      f"超过 0.10pp 的比例 = {(g > 0.001).mean():.1%}")
for lo, hi, nm in [(0, 0.005, "<0.5%"), (0.005, 0.04, "0.5–4%"), (0.04, 99, "[4%+)")]:
    sub = df[(df.yld >= lo) & (df.yld < hi)]
    print(f"    {nm:>8}: n={len(sub):>6}  中位|差|={sub.adj_gap.abs().median():.5%}")
print("  ⇒ H_adj " + ("**被否** (复权正确, 后面测到的是真实经济收益)"
                      if g.median() < 0.001 else "**未被否** ⇒ §10 的测量被口径污染"))

print()
print("=" * 80)
print("判别 2 —— 价格分层: 层**内**比 [4%+) vs <4%  (§7.11 的同一手段)")
print("=" * 80)
df["layer"] = np.where(df.praw < 5, "  <¥5", np.where(df.praw < 10, "¥5–10",
                np.where(df.praw < 20, "¥10–20", np.where(df.praw < 50, "¥20–50", "  ≥¥50"))))
for L in ["  <¥5", "¥5–10", "¥10–20", "¥20–50", "  ≥¥50"]:
    sub = df[df.layer == L]
    hi, lo = sub[sub.yld >= 0.04], sub[sub.yld < 0.04]
    if len(hi) < 30 or len(lo) < 30:
        print(f"  {L:>7}: [4%+)= {len(hi):>5}  <4%= {len(lo):>6}   —— 样本不足"); continue
    eh = hi.groupby("ex_date").ex.mean(); el = lo.groupby("ex_date").ex.mean()
    print(f"  {L:>7}: [4%+] n={len(hi):>5} 超额 {eh.mean():>+8.3%} (t={eh.mean()/(eh.std(ddof=1)/np.sqrt(len(eh))):>+5.2f})"
          f" | <4% n={len(lo):>6} 超额 {el.mean():>+8.3%}  |  层内差 {eh.mean()-el.mean():>+8.3%}")

print()
print("=" * 80)
print("判别 3 —— 换自变量: 每股分红**金额** (元) 而不是**比率**")
print("=" * 80)
df["Dband"] = np.where(df.D < 0.05, "<0.05元", np.where(df.D < 0.15, "0.05–0.15元",
                 np.where(df.D < 0.3, "0.15–0.3元", np.where(df.D < 0.6, "0.3–0.6元", "≥0.6元"))))
print(f"{'金额档':>12} {'事件数':>7} {'超额':>10} {'t':>7} {'该档中位股息率':>14}")
for L in ["<0.05元", "0.05–0.15元", "0.15–0.3元", "0.3–0.6元", "≥0.6元"]:
    sub = df[df.Dband == L]
    if len(sub) < 200: print(f"{L:>12} {len(sub):>7}  —— 样本不足"); continue
    g2 = sub.groupby("ex_date").ex.mean(); e = g2.to_numpy()
    t = e.mean() / (e.std(ddof=1) / np.sqrt(len(e)))
    print(f"{L:>12} {len(sub):>7} {e.mean():>+9.3%} {t:>+7.2f} {sub.yld.median():>13.3%}")
print("\n判读: 若超额**只在比率轴上成梯度**、在金额轴上不成梯度 ⇒ 分母伪影 (H_price)。")
con.close()
