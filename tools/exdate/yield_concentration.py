"""最后的稳健性检查: [4%+) 那条 −1%/次 是不是**少数几只票**撑起来的。

## 为什么这是必须的最后一步
§10.8 刚教训过"用整体断言部分"。反向的错也一样: **用一个宽表格断言一个窄总体**。
若 1665 笔事件其实来自 ~50 只在册多年的大票 (如国有大行/公用事业),
则"10 年 10 段全为负"实际是"50 只票各自 10 次", **事件日数给出的宽度是假的**。
判据:
* 前 10 只票占事件比例 **< 20%** 且 distnct 票数 **> 300** ⇒ 不是少数票现象;
* 否则 ⇒ 必须按**票等权**重算一遍, 并以票等权口径为准。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import duckdb, numpy as np
from hiagent_config import DB_PATH
END = "2026-09-18"
PURE = "dividend_per_share > 0 AND per_share_bonus = 0 AND rights_ratio = 0"
con = duckdb.connect(str(DB_PATH), read_only=True)
SQL = f"""
WITH ev AS (SELECT DISTINCT e.thscode, e.ex_date, e.dividend_per_share AS D,
                   (SELECT max(r.date) FROM raw_kline_daily r
                     WHERE r.thscode=e.thscode AND r.date < e.ex_date) AS d0
            FROM raw_adjustment_events e
            WHERE e.ex_date BETWEEN '2016-10-01' AND ? AND {PURE}),
evy AS (SELECT ev.thscode, ev.ex_date, ev.D/r.close AS yld
        FROM ev JOIN raw_kline_daily r ON r.thscode=ev.thscode AND r.date=ev.d0 WHERE r.close>0),
p AS (SELECT thscode, date, close, LAG(close,1) OVER w AS c1 FROM v_daily_hfq
      WHERE date BETWEEN '2016-09-01' AND ? WINDOW w AS (PARTITION BY thscode ORDER BY date)),
m AS (SELECT date, avg(close/c1-1) AS mkt FROM p GROUP BY date)
SELECT evy.thscode, evy.ex_date, evy.yld, p.close/p.c1-1 - m.mkt AS ex
FROM evy JOIN p ON p.thscode=evy.thscode AND p.date=evy.ex_date JOIN m ON m.date=evy.ex_date
WHERE evy.yld < 1
"""
df = con.execute(SQL, [END, END]).fetchdf().dropna()
hi = df[df.yld >= 0.04].copy()

print("=" * 76); print("① 集中度"); print("=" * 76)
cnt = hi.groupby("thscode").size().sort_values(ascending=False)
print(f"  事件 {len(hi)} 笔, 来自 **{len(cnt)} 只票** (中位每票 {cnt.median():.0f} 次, 最多 {cnt.iloc[0]} 次)")
print(f"  前 10 只占 {cnt.head(10).sum()/len(hi):.1%};  前 30 只占 {cnt.head(30).sum()/len(hi):.1%}")
print("  事件最多的 8 只 (票号 / 次数):")
for c, n in cnt.head(8).items(): print(f"      {c}  {n}")

print(); print("=" * 76); print("② 两种口径 (事件日聚合 vs **票等权**)"); print("=" * 76)
g = hi.groupby("ex_date").ex.mean(); e = g.to_numpy()
print(f"  事件日聚合 (原口径): {e.mean():+.4%}  (n={len(e)} 日, t={e.mean()/(e.std(ddof=1)/np.sqrt(len(e))):+.2f})")
pn = hi.groupby("thscode").ex.mean()
print(f"  **票等权**         : {pn.mean():+.4%}  (n={len(pn)} 只)")
print(f"  票等权下 为负的票占比: {(pn < 0).mean():.1%}")

print(); print("=" * 76); print("③ 剔除事件最多的 30 只票后重算"); print("=" * 76)
drop = set(cnt.head(30).index)
sub = hi[~hi.thscode.isin(drop)]
g2 = sub.groupby("ex_date").ex.mean(); e2 = g2.to_numpy()
print(f"  剩余 {len(sub)} 笔 / {sub.thscode.nunique()} 只: "
      f"{e2.mean():+.4%}  (t={e2.mean()/(e2.std(ddof=1)/np.sqrt(len(e2))):+.2f})")

print(); print("=" * 76); print("④ 逐年 (票等权) —— 检查「10 年全负」在去掉大票后还成立吗"); print("=" * 76)
hi["yr"] = hi.ex_date.astype(str).str[:4]
sub2 = sub.copy(); sub2["yr"] = sub2.ex_date.astype(str).str[:4]
print(f"{'年':>6} {'剔30大票后 票等权超额':>22} {'为负的票占比':>12}")
for y in sorted(hi.yr.unique()):
    s = sub2[sub2.yr == y]
    if len(s) < 20: continue
    pn2 = s.groupby("thscode").ex.mean()
    print(f"{y:>6} {pn2.mean():>+21.3%} {(pn2<0).mean():>11.1%}")
con.close()
