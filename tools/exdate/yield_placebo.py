"""最后一个对照: [4%+) 的那 −1% 是**除权日特有**, 还是这些票**在那个季节本来就跑输**?

## 为什么这是决定性的
高股息票的除权日**集中在 6–7 月** (A 股分红季)。若这些票在该季节整体跑输市场,
那"除权日超额"就只是一个**季节/风格**效应被贴到了事件日上 —— 与 §7 的市场级振荡同类,
不是可交易的日期效应。**必须做一个安慰剂: 同一批事件、同一个票池、看 T±5 的偏移。**

## ★ 预登记判据 (看数之前)
* **事件特有**: |excess(T=0)| 显著大于 |excess(T≠0)| 的任何一个 ⇒ 是**日期效应**;
* **季节性**: T±1..±5 也与 T=0 同号同量级 ⇒ 是**季节/风格效应**, 不是除权日效应。
  ⇒ 若是后者, 本节**不得**把它写成"除权日效应"。
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
-- 每只票在事件窗口内的全部交易日 + 序号, 便于按偏移取行
px AS (SELECT thscode, date, close, LAG(close,1) OVER w AS c1
       FROM v_daily_hfq WHERE date BETWEEN '2016-08-01' AND ?
       WINDOW w AS (PARTITION BY thscode ORDER BY date)),
mkt AS (SELECT date, avg(close/c1-1) AS mkt FROM px GROUP BY date),
seq AS (SELECT thscode, date, close/c1-1 AS r, ROW_NUMBER() OVER (PARTITION BY thscode ORDER BY date) AS rn
        FROM px)
SELECT evy.thscode, evy.ex_date, evy.yld, s.rn
FROM evy JOIN seq s ON s.thscode=evy.thscode AND s.date=evy.ex_date
WHERE evy.yld < 1
"""
ev = con.execute(SQL, [END, END]).fetchdf().dropna()

# 取每个事件在 seq 里的行号, 再按偏移取同一只票的相对收益
OFF = list(range(-5, 6))
print("=" * 74)
print("安慰剂: [4%+) 与 [0,4%) 两组的**相对收益**在 T±5 上的形状")
print("=" * 74)
print(f"{'偏移':>5} {'[4%+) 超额':>12} {'t':>7} {'[0,4%) 超额':>13} {'t':>7} {'差值':>10}")
inner = f"""
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
         JOIN seq s ON s.thscode=evy.thscode AND s.date=evy.ex_date WHERE evy.yld < 1)
SELECT b.yld, b.ex_date, a.r - m.mkt AS ex
FROM base b JOIN seq a ON a.thscode=b.thscode AND a.rn=b.rn+? JOIN mkt m ON m.date=a.date
"""
for off in OFF:
    d = con.execute(inner, [off]).fetchdf().dropna()
    d = d[d.ex_date.astype(str) != ""]
    row = []
    for lo, hi in ((0.04, 99), (0.0, 0.04)):
        s = d[(d.yld >= lo) & (d.yld < hi) & (d.yld < 1)]
        g = s.groupby("ex_date").ex.mean(); e = g.to_numpy()
        row.append((e.mean(), e.mean() / (e.std(ddof=1) / np.sqrt(len(e)))))
    print(f"{off:>+5} {row[0][0]:>+11.3%} {row[0][1]:>+7.2f} {row[1][0]:>+12.3%} {row[1][1]:>+7.2f} "
          f"{row[0][0]-row[1][0]:>+9.3%}")
print("\n判读: 若只有 T=0 那一行为大负、两侧迅速回到 0 ⇒ **日期效应**;")
print("      若 ±1..±5 也同号同量级 ⇒ 季节/风格效应, 不得写成'除权日效应'。")
con.close()
