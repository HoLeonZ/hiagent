"""§10.9(h)5 "机制未证" 的判决实验: T=0 那一跌是**除权日特有**, 还是**通用的"涨过就回吐"**?

## 为什么这一关最要紧
§10.9 的安慰剂显示: 高股息档在 T−5/T−4 有 **+0.51%/+0.44%** 的抬升, T=0 是 **−1.31%**。
若"短期涨过 → 次日回吐"是**全市场通用**规律, 那么那 −1.31% 就**不是除权日效应**,
而是"这些票恰好涨过"。⇒ §10.9 的整个结论会塌成"高股息票在除权前会涨", 而那是另一个
(且本册已探索过的)方向。

## ★ 预登记设计 (看数之前定下)
**对照**: 在**同一批事件日** T 上, 取**全市场**所有票 j (剔除 T±5 内有任何除权事件的票,
避免污染), 对每个 j 算
     runup_j = Σ_{k=1..5} (r_j − mkt)(T−k)      ← 同样口径的前 5 日累积超额
     drop_j  = (r_j − mkt)(T)                    ← 当日超额
在**对照样本内**回归 `drop = a + β·runup`, 得**通用反转系数 β**。

**判据**:
* **H_generic**: 事件组的实际 drop ≈ `β × 事件组平均 runup`  ⇒ 比值 ≈ 1 ⇒ **是通用反转, §10.9 塌**;
* **H_div**: 实际 drop **远负于**预测值 (比值 ≫ 1) ⇒ **除权日特有**, §10.9 站得住。

同时报**事件组内部**自己的 drop~runup 斜率, 与对照的 β 直接比 —— 同一份数据、同一种回归,
唯一差别是"有没有除权"。
"""
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from pathlib import Path
import duckdb, numpy as np
from hiagent_config import DB_PATH

END = "2026-09-18"
PURE = "dividend_per_share > 0 AND per_share_bonus = 0 AND rights_ratio = 0"
con = duckdb.connect(str(DB_PATH), read_only=True)

SQL = f"""
WITH px AS (SELECT thscode, date, close, LAG(close,1) OVER w AS c1
            FROM v_daily_hfq WHERE date BETWEEN '2016-08-01' AND '{END}'
            WINDOW w AS (PARTITION BY thscode ORDER BY date)),
q AS (SELECT thscode, date, close/c1 AS r FROM px WHERE c1 IS NOT NULL),
m AS (SELECT date, avg(r) AS mkt FROM q GROUP BY date),
ex AS (SELECT q.thscode, q.date,
              q.r - m.mkt AS e,
              SUM(q.r - m.mkt) OVER (PARTITION BY q.thscode ORDER BY q.date
                                     ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) AS runup
       FROM q JOIN m ON m.date=q.date),
ev AS (SELECT DISTINCT e.thscode, e.ex_date, e.dividend_per_share AS D,
              (SELECT max(r.date) FROM raw_kline_daily r
                WHERE r.thscode=e.thscode AND r.date < e.ex_date) AS d0
       FROM raw_adjustment_events e
       WHERE e.ex_date BETWEEN '2016-10-01' AND '{END}' AND {PURE}),
evy AS (SELECT ev.thscode, ev.ex_date, ev.D/r.close AS yld
        FROM ev JOIN raw_kline_daily r ON r.thscode=ev.thscode AND r.date=ev.d0 WHERE r.close>0),
mark AS (SELECT thscode, ex_date AS date, 1 AS is_hy, yld FROM evy WHERE yld >= 0.04),
-- 剔除 T±5 内有过任何除权事件的票 (净污染)
dirty AS (SELECT DISTINCT a.thscode, b.ex_date AS date
          FROM evy a JOIN evy b ON a.thscode=b.thscode
          WHERE abs(date_diff('day', a.ex_date, b.ex_date)) <= 10)
SELECT ex.thscode, ex.date, ex.e, ex.runup,
       (mark.is_hy IS NOT NULL) AS is_hy,
       (dirty.thscode IS NOT NULL) AS dirty
FROM ex
LEFT JOIN mark  ON mark.thscode=ex.thscode AND mark.date=ex.date
LEFT JOIN dirty ON dirty.thscode=ex.thscode AND dirty.date=ex.date
WHERE ex.runup IS NOT NULL AND ex.date >= DATE '2021-10-01'
"""
df = con.execute(SQL).fetchdf()
print(f"总行 {len(df):,}")

ev  = df[df.is_hy == True].dropna(subset=["runup"])                    # noqa: E712
ctl = df[(df.is_hy != True) & (df.dirty != True)].dropna(subset=["runup"])  # noqa: E712

print()
print("=" * 78)
print("① 对照样本 (同事件日、全市场、T±5 内无除权): 通用反转系数 β")
print("=" * 78)
x, y = ctl.runup.to_numpy(), ctl.e.to_numpy()
beta, a = np.polyfit(x, y, 1)
r_ctl = np.corrcoef(x, y)[0, 1]
print(f"  对照 n = {len(ctl):,} 行;  drop = {a:+.5f} + {beta:+.4f} · runup   (r = {r_ctl:+.3f})")

print()
print("=" * 78)
print("② 事件组 [4%+) 照同一口径")
print("=" * 78)
xe, ye = ev.runup.to_numpy(), ev.e.to_numpy()
beta_e, a_e = np.polyfit(xe, ye, 1)
print(f"  事件 n = {len(ev):,} 行;  平均 runup = {xe.mean():+.4%};  平均 drop = {ye.mean():+.4%}")
print(f"  事件组自己的斜率 = {beta_e:+.4f}   (对照 β = {beta:+.4f})")

print()
print("=" * 78)
print("③ 判决")
print("=" * 78)
pred = a + beta * xe.mean()
print(f"  用**对照的 β** 预测事件组:  a + β·mean(runup) = {pred:+.4%}")
print(f"  实际 drop                              = {ye.mean():+.4%}")
print(f"  比值 (实际 / 预测)                      = {ye.mean()/pred:>+7.2f}")
print(f"  差额 (实际 − 预测)                      = {ye.mean()-pred:>+7.4%}")
print("  判据: 比值 ≈ 1 ⇒ 通用反转 (§10.9 塌);  比值 ≫ 1 且差额大 ⇒ 除权日特有 (§10.9 站得住)")
con.close()
