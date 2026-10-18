"""§10.13(g) 留档的那条**未解决的不一致**: 事件级 0.47%/年 vs 组合层 1.78%/年, 差约 4 倍。

## 唯一还没被检验的解释: 同日同伴效应 (H_cohort)
高息票**成群**除权 (5/6/7 月)。若在这些日子里, 同群中**当天不除权**的票**也一起跑输**,
那么"组合级跌幅"就会远大于"单票效应 × 暴露比例" —— 4 倍差就是这个缺口。

## ★ 预登记 (看数之前定死; 这一次**必须**带月份固定效应 —— 上一轮就是栽在这里)
**因变量**: 当日**同群中不除权**的那些票的超额均值 (即同伴的当天表现)。
**自变量**: `frac_ex` = 当日除权的同群成员数 / 当日有行情的同群成员数。
**回归**: `hold_excess = α_{年,月} + β · frac_ex`  ← **月份固定效应吸收"这个月同群整体好不好"**。

**判据 (先定)**
* **H_cohort 成立**: `β_FE` 显著为**负**, 且量级足以解释缺口 (缺口 ≈ −0.031%/日,
  而 frac_ex 的典型值 ≈ 1.1% ⇒ 需要 `β_FE ≲ −1.5%`);
* **H_cohort 被否**: `β_FE ≈ 0` ⇒ 4 倍差**不是**同伴效应 ⇒ 那份缺口只能记为"本库无法解释"。

⚠️ **同时报无固定效应的 β 作对照** —— 两者差多少, 就是"季节"占多少。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import duckdb, numpy as np
from hiagent_config import DB_PATH

END = "2026-09-18"
con = duckdb.connect(str(DB_PATH), read_only=True)
SQL = f"""
WITH ev AS (SELECT DISTINCT e.thscode, e.ex_date, e.dividend_per_share AS D,
                   (SELECT max(r.date) FROM raw_kline_daily r
                     WHERE r.thscode=e.thscode AND r.date < e.ex_date) AS d0
            FROM raw_adjustment_events e
            WHERE e.ex_date BETWEEN '2016-01-01' AND '{END}'
              AND e.dividend_per_share > 0 AND e.per_share_bonus = 0 AND e.rights_ratio = 0),
evy AS (SELECT ev.thscode, ev.ex_date, ev.D/r.close AS yld
        FROM ev JOIN raw_kline_daily r ON r.thscode=ev.thscode AND r.date=ev.d0 WHERE r.close>0),
sel AS (SELECT DISTINCT thscode, year(ex_date) + 1 AS y FROM evy WHERE yld >= 0.04),
exd AS (SELECT thscode, ex_date AS date FROM evy WHERE yld >= 0.04),
px AS (SELECT thscode, date, close, LAG(close,1) OVER w AS c1
       FROM v_daily_hfq WHERE date BETWEEN '2016-12-01' AND '{END}'
       WINDOW w AS (PARTITION BY thscode ORDER BY date)),
q AS (SELECT thscode, date, close/c1 - 1 AS r FROM px WHERE c1 IS NOT NULL),
m AS (SELECT date, avg(r) AS mkt FROM q GROUP BY date),
j AS (SELECT sel.y, q.thscode, q.date, q.r - m.mkt AS e,
             (exd.thscode IS NOT NULL) AS is_ex
      FROM sel JOIN q ON q.thscode=sel.thscode AND year(q.date)=sel.y
               JOIN m ON m.date=q.date
               LEFT JOIN exd ON exd.thscode=q.thscode AND exd.date=q.date)
-- 只取「当天不除权」的同伴, 与「当天除权」的那些分开
SELECT y, date,
       avg(CASE WHEN NOT is_ex THEN e END) AS hold_e,
       sum(CASE WHEN NOT is_ex THEN 1 ELSE 0 END) AS n_hold,
       sum(CASE WHEN is_ex THEN 1 ELSE 0 END) AS n_ex,
       avg(CASE WHEN is_ex THEN e END) AS ex_e
FROM j GROUP BY y, date
"""
d = con.execute(SQL).fetchdf().dropna(subset=["hold_e", "n_hold"])
d["frac_ex"] = d.n_ex / (d.n_ex + d.n_hold)
d["ym"] = d.date.astype(str).str[:7]

def ols(x, y):
    x = np.asarray(x, float); y = np.asarray(y, float)
    X = np.column_stack([np.ones_like(x), x])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ b
    se = np.sqrt(np.sum(res**2) / (len(x) - 2) * np.linalg.pinv(X.T @ X)[1, 1])
    return b[1], b[1] / se

def run(sub, tag):
    print(f"\n【{tag}】 组合日 {len(sub)}")
    y = sub.hold_e.to_numpy(); x = sub.frac_ex.to_numpy()
    n0 = sub[sub.n_ex == 0]; n1 = sub[sub.n_ex > 0]
    print(f"  同伴(不除权者)日超额:  无同群除权的日子 {n0.hold_e.mean():>+8.4%} (n={len(n0)})"
          f"  |  有同群除权的日子 {n1.hold_e.mean():>+8.4%} (n={len(n1)})"
          f"  ⇒ 原始差 {n1.hold_e.mean()-n0.hold_e.mean():>+8.4%}")
    b_raw, t_raw = ols(x, y)
    g = sub.groupby("ym")
    yd = y - g["hold_e"].transform("mean").to_numpy()
    xd = x - g["frac_ex"].transform("mean").to_numpy()
    b_fe, t_fe = ols(xd, yd)
    print(f"  β 无固定效应      = {b_raw:>+9.4%}  (t={t_raw:>+6.2f})")
    print(f"  **β 含月份固定效应** = {b_fe:>+9.4%}  (t={t_fe:>+6.2f})")
    exp = x.mean() * b_fe
    print(f"  ⇒ 按 frac_ex 均值 {x.mean():.4%} 折算: 同伴每天多跌 {exp:>+8.4%}"
          f" ⇒ 年化 {exp*d.groupby('y').ngroups*0+exp*243:>+8.4%}")
    return b_fe, t_fe

print("=" * 84)
print("H_cohort 检验: 同群除权的日子里, **当天不除权的同群票**是否也一起跑输?")
print("=" * 84)
call_b, call_t = run(d, "全期 2017–2026")
rec = d[d.date >= np.datetime64("2021-10-01")]
rec_b, rec_t = run(rec, "近期 2022–2026")

print()
print("=" * 84)
print("判据")
print("=" * 84)
print("  缺口 (组合层 vs 事件级, 即 §10.13(g) 那条) ≈ 0.031%/日 (按 389 个除权日摊)。")
for tag, b, t in [("全期", call_b, call_t), ("近期", rec_b, rec_t)]:
    ok = (b < 0) and (t < -2)
    print(f"  {tag}: β_FE = {b:>+8.4%} (t={t:>+5.2f}) ⇒ H_cohort {'成立' if ok else '**不成立**'}")
print("  (H_cohort 成立还需 |β_FE| ≳ 1.5% 才够解释缺口。)")
con.close()
