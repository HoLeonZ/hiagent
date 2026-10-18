"""上一版配对估计量**加权错了**, 重做: 按**暴露比例**回归 + 月份固定效应。

## 上一版错在哪 (不改它, 记下来)
`seasonal_check.py` 的"月内配对差"给每个 (年,月) **等权**。
而除权日在月份间**极度不均**: 5/6/7 月共 329 个除权日, 而 3/11/12 月各只有 **1 个**。
⇒ 一个 1 天的月份与 6 月 (129 天) **权重相同**, 均值于是被淡季月份的单日噪声支配。
**这不是数据结论, 是估计量的加权错** —— 正是本册反复记的"工具自己造假象"。

## ★ 正确的设计 (预登记)
对每个组合日: `port_e` = 当日持仓的超额均值;  `frac` = 当日除权的持仓 / 当日持仓数。
回归 `port_e = α_{年,月} + β · frac` (**月份固定效应**吸收了"这个月组合整体好不好")。
* `β` 的含义: **持有比例从 0 变成 1** 时的超额变化 ⇒ 应与 §10.9 的**事件级** −0.99%/次 同量级;
* **不加固定效应**的 β 作对照 (含季节成分)。

**判据**:
* `|β_FE| ≥ 0.6 × 0.99%` (即 ≥0.6pp) 且符号为负 ⇒ **组合层与事件层一致** ⇒ §10.12 的
  −1.78%/年 是**稀释后的正确值**, 上一步的 "H_season" 是我的估计量造成的**假否**;
* `|β_FE|` 塌到 ≈ 0 ⇒ **真的只是季节** ⇒ §10.12 死掉。
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
SELECT y, date, avg(e) AS port_e, count(*) AS nhold,
       sum(CASE WHEN is_ex THEN 1 ELSE 0 END) AS nex
FROM j GROUP BY y, date
"""
d = con.execute(SQL).fetchdf().dropna()
d["frac"] = d.nex / d.nhold
d["ym"] = d.date.astype(str).str[:7]

def ols(x, y):
    x = np.asarray(x, float); y = np.asarray(y, float)
    X = np.column_stack([np.ones_like(x), x])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ b
    se = np.sqrt(np.sum(resid**2) / (len(x) - 2) * np.linalg.pinv(X.T @ X)[1, 1])
    return b[1], b[1] / se

def demo(y, x, tag, sub):
    yv = sub[y].to_numpy(); xv = sub[x].to_numpy()
    b_raw, t_raw = ols(xv, yv)
    # 月份固定效应: 在 (年,月) 内去均值
    g = sub.groupby("ym")
    yd = yv - g[y].transform("mean").to_numpy()
    xd = xv - g[x].transform("mean").to_numpy()
    b_fe, t_fe = ols(xd, yd)
    print(f"\n【{tag}】 组合日 {len(sub)}  平均暴露 frac = {xv.mean():.4%}")
    print(f"  β 不含固定效应 : {b_raw:>+9.4%}  (t={t_raw:>+6.2f})")
    print(f"  **β 含月份固定效应**: {b_fe:>+9.4%}  (t={t_fe:>+6.2f})   ← 判据看这个")
    return b_fe

print("=" * 84)
print("① 全期 (持有年 2017–2026)")
print("=" * 84)
b_all = demo("port_e", "frac", "全期", d)
print()
print("=" * 84)
print("② 近期 (持有年 2022–2026, 日域 2021-10 起)")
print("=" * 84)
b_rec = demo("port_e", "frac", "近期", d[d.date >= np.datetime64("2021-10-01")])

print()
print("=" * 84)
print("③ 与事件级对照")
print("=" * 84)
EV = {"全期": -0.0126, "近期": -0.0099}   # §10.9/§10.7: 事件级每次事件幅度
for tag, b in [("全期", b_all), ("近期", b_rec)]:
    e = EV[tag]
    print(f"  {tag}: 组合层 β_FE = {b:>+8.4%}   事件级 §10.9 = {e:>+8.4%}   "
          f"比值 = {b/e:>+6.2f}  ⇒ {'一致' if 0.6 <= b/e <= 1.6 else '不一致'}")
print("\n判据: 比值 ∈ [0.6, 1.6] ⇒ 组合层与事件层一致 (§10.12 的 −1.78%/年 是稀释后的正确值,")
print("      上一版的 H_season 是我那个配对估计量的加权错造成的假否)。")
con.close()
