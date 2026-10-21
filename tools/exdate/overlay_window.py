"""决定性的一张表: 高股息档的 overlay 值多少, **取决于窗口**, 而窗口是事后选的。

从 exdate_yield_placebo.py 的 T±5 形状读出来的事实:
T−4/T−5 有 +0.51%/+0.44% 的**抢息抬升**, T=0 是 −1.31% 的断崖, T+1..T+3 缓慢回吐。
⇒ 一张只"回避除权日当天"的 overlay 与一张"回避 ±5 天"的 overlay, **毛值差 3 倍**。

★ 本节**不选那个最好的窗口** (§5: 不得在同一批数据上挑最优档)。
   只把**整条窗口敏感度曲线**摆出来, 并明确: 任何单一数字都是"窗口的函数"。
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
WITH px AS (SELECT thscode, date, close, LAG(close,1) OVER w AS c1
            FROM v_daily_hfq WHERE date BETWEEN '2016-08-01' AND '{END}'
            WINDOW w AS (PARTITION BY thscode ORDER BY date)),
seq AS (SELECT thscode, date, close/c1 AS r,
               ROW_NUMBER() OVER (PARTITION BY thscode ORDER BY date) AS rn FROM px),
mkt AS (SELECT date, avg(r) AS mkt FROM seq GROUP BY date),
ev AS (SELECT DISTINCT e.thscode, e.ex_date, e.dividend_per_share AS D,
              (SELECT max(r.date) FROM raw_kline_daily r
                WHERE r.thscode=e.thscode AND r.date < e.ex_date) AS d0
       FROM raw_adjustment_events e
       WHERE e.ex_date BETWEEN '2016-10-01' AND '{END}' AND {PURE}),
evy AS (SELECT ev.thscode, ev.ex_date, ev.D/r.close AS yld
        FROM ev JOIN raw_kline_daily r ON r.thscode=ev.thscode AND r.date=ev.d0 WHERE r.close>0),
base AS (SELECT evy.thscode, evy.ex_date, evy.yld, s.rn FROM evy
         JOIN seq s ON s.thscode=evy.thscode AND s.date=evy.ex_date WHERE evy.yld < 1),
offs AS (SELECT * FROM (VALUES (-5),(-4),(-3),(-2),(-1),(0),(1),(2),(3),(4),(5)) t(k))
SELECT b.ex_date, b.yld, o.k AS off, a.r - m.mkt AS ex
FROM base b JOIN offs o ON TRUE
     JOIN seq a ON a.thscode=b.thscode AND a.rn=b.rn+o.k
     JOIN mkt m ON m.date=a.date
"""
d = con.execute(SQL).fetchdf().dropna()
hi = d[d.yld >= 0.04]
day = hi.groupby(["ex_date", "off"]).ex.mean().unstack()      # 逐事件日 → 再按偏移

print("=" * 72)
print("① 高股息档 [4%+) 的**累积超额** (从 T−k 到 T)", )
print("=" * 72)
print(f"{'从 T−k 持有到 T':>16} {'k=1':>10} {'k=2':>10} {'k=3':>10} {'k=4':>10} {'k=5':>10}")
for end_off in (0, 1, 2, 5):
    row = []
    for k in (1, 2, 3, 4, 5):
        cols = [c for c in range(-k, end_off + 1) if c in day.columns]
        row.append(day[cols].sum(axis=1).mean())
    print(f"{'到 T+%d:' % end_off:>16} " + "".join(f"{v:>+9.3%} " for v in row))

print()
print("=" * 72)
print("② overlay 毛值 (= 回避该窗口所省下的) —— **窗口的函数**")
print("=" * 72)
print(f"{'窗口':>18} {'累积超额':>12} {'overlay 毛值':>13} {'t':>7}")
for a_, b_, nm in [(-5, 5, "T−5 .. T+5"), (-2, 2, "T−2 .. T+2"), (-1, 1, "T−1 .. T+1"),
                   (-1, 0, "T−1 .. T"),   (0, 0, "仅 T=0"),   (-5, 0, "T−5 .. T")]:
    cols = [c for c in range(a_, b_ + 1) if c in day.columns]
    cum = day[cols].sum(axis=1)
    v = cum.to_numpy(); t = v.mean() / (v.std(ddof=1) / np.sqrt(len(v)))
    print(f"{nm:>18} {v.mean():>+11.3%} {-v.mean():>+12.3%} {t:>+7.2f}")
print("\n⚠️ 不选最优窗口。区间本身是**事后可选**的 ⇒ 任何单一数字都是'窗口的函数'。")
print("   事件定义 (除权日) 给出的自然窗口是 '仅 T=0'; 但 ±1..±5 的抢息抬升说明")
print("   T=0 那一跌有相当部分是**回吐**, 所以宽窗口的毛值小得多。")

# 年化: overlay 毛值 × 每票每年事件数 (f_sel, 策略相关)
print()
print("=" * 72)
print("③ 年化 (对'持有当年高股息票'的组合, f_sel ≈ 1.0 次/票/年)")
print("=" * 72)
for a_, b_, nm in [(-5, 5, "T−5..T+5"), (-1, 1, "T−1..T+1"), (0, 0, "仅 T=0")]:
    cols = [c for c in range(a_, b_ + 1) if c in day.columns]
    gross = -day[cols].sum(axis=1).mean()
    print(f"  {nm:>12}: 毛值 {gross:>+7.3%}/次 ⇒ 年化 {gross*1.015:>+7.3%}/年  "
          f"(扣往返成本 0.10–0.15% ⇒ 净 {gross*1.015-0.0015:>+7.3%} ~ {gross*1.015-0.0010:>+7.3%})")
print("\n预登记门槛 = 1%/年 (仅对'仅 T=0'窗口达到, 且那是最有利的窗口选择)。")
con.close()
