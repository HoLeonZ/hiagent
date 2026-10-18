"""§10.11(f) 预登记的**宿主问题**: 持有高股息票的组合, 在**非除权日**的超额是多少?

## 要回答什么
§10.9 量的是**除权日当天**的超额 (≈ −1.0%/次)。若把"4%+ 股息票"当作一个组合**整年持有**:
* **除权日之外**那 240 多天的超额若 ≈ 0 ⇒ "持有高股息票 + 各自除权日空仓 ≈ 等权市场 + ~1%/年";
* 若显著为负 ⇒ 宿主本身是坏的, overlay 救不回来 ⇒ **这条线索到此为止**。

## ★ 预登记设计 (上一轮 §10.11(f) 已定, 本轮一字未改)
1. **无前视**: 用**前一年 (Y−1)** 有 ≥4% 纯现金分红事件的票组成 S_Y, **持有 Y 整年**。
   不得用当年事件选票。
2. **同构造对照**: 基准 = **当日全市场等权** (与 §10 全程一致, 同一列 `mkt`)。
3. **整年分解, 不挑窗口**: 只分"**持有票当日有除权**" vs "**没有**"两类, 不再切 ±k 天。
4. 组合口径: **等权**, 每日在**当日有行情的成分股**上取平均 (停牌票自然缺席, 不合成 bar)。

## ★ 预登记判据 (看数之前)
* **线索活**: 非除权日超额 **|t| < 2** (与零不可区分) **且** 除权日贡献显著为负
  ⇒ "市场 + overlay" 成立, 值得继续;
* **线索死**: 非除权日超额显著为**负** ⇒ 宿主坏掉 ⇒ 关闭;
* ⚠️ 若非除权日超额显著为**正** ⇒ **不得当成 alpha 欢呼** (§8.3: 在本库上再加一个横截面
  选股信号然后报其样本内 t, 已被 §7 证明可以是 5 年样本外归零的)。那只说明宿主自身有溢价,
  需另走 §5/§7 的全套验证才能谈。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import duckdb, numpy as np
from hiagent_config import DB_PATH

END = "2026-09-18"
YEARS = [2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]
PURE = "dividend_per_share > 0 AND per_share_bonus = 0 AND rights_ratio = 0"
con = duckdb.connect(str(DB_PATH), read_only=True)

SQL = f"""
WITH ev AS (SELECT DISTINCT e.thscode, e.ex_date, e.dividend_per_share AS D,
                   (SELECT max(r.date) FROM raw_kline_daily r
                     WHERE r.thscode=e.thscode AND r.date < e.ex_date) AS d0
            FROM raw_adjustment_events e
            WHERE e.ex_date BETWEEN '2016-01-01' AND '{END}' AND {PURE}),
evy AS (SELECT ev.thscode, ev.ex_date, ev.D/r.close AS yld
        FROM ev JOIN raw_kline_daily r ON r.thscode=ev.thscode AND r.date=ev.d0 WHERE r.close>0),
-- 选票: 用 **Y−1 年** 的 ≥4% 事件 (无前视)
sel AS (SELECT DISTINCT thscode, year(ex_date) + 1 AS y FROM evy WHERE yld >= 0.04),
-- ★ 两种口径都算, 以定位上一版"除权日拖累 −4.2%/年"与 §10.9 的 −0.7%/年 之间的 6 倍差
exday_any AS (SELECT DISTINCT thscode, ex_date AS date FROM raw_adjustment_events
              WHERE ex_date BETWEEN '2017-01-01' AND '{END}'),
exday_pc  AS (SELECT DISTINCT thscode, ex_date AS date FROM raw_adjustment_events
              WHERE ex_date BETWEEN '2017-01-01' AND '{END}'
                AND dividend_per_share > 0 AND per_share_bonus = 0 AND rights_ratio = 0),
exday_hy  AS (SELECT DISTINCT evy.thscode, evy.ex_date AS date FROM evy WHERE evy.yld >= 0.04),
px AS (SELECT thscode, date, close, LAG(close,1) OVER w AS c1
       FROM v_daily_hfq WHERE date BETWEEN '2016-12-01' AND '{END}'
       WINDOW w AS (PARTITION BY thscode ORDER BY date)),
q AS (SELECT thscode, date, close/c1 - 1 AS r FROM px WHERE c1 IS NOT NULL),
m AS (SELECT date, avg(r) AS mkt FROM q GROUP BY date),
j AS (SELECT sel.y, q.thscode, q.date, q.r - m.mkt AS e,
             (a.thscode IS NOT NULL) AS is_any,
             (b.thscode IS NOT NULL) AS is_pc,
             (c.thscode IS NOT NULL) AS is_hy
      FROM sel JOIN q ON q.thscode=sel.thscode AND year(q.date)=sel.y
               JOIN m ON m.date=q.date
               LEFT JOIN exday_any a ON a.thscode=q.thscode AND a.date=q.date
               LEFT JOIN exday_pc  b ON b.thscode=q.thscode AND b.date=q.date
               LEFT JOIN exday_hy  c ON c.thscode=q.thscode AND c.date=q.date)
SELECT y, date, avg(e) AS port_e, count(*) AS n_names,
       max(CASE WHEN is_any THEN 1 ELSE 0 END) AS has_any,
       max(CASE WHEN is_pc  THEN 1 ELSE 0 END) AS has_pc,
       max(CASE WHEN is_hy  THEN 1 ELSE 0 END) AS has_hy
FROM j GROUP BY y, date
"""
d = con.execute(SQL).fetchdf().dropna()

print("=" * 88)
print("① 逐年: 「前一年有 ≥4% 股息」的票, 等权持有该年的**日超额** (基准 = 当日全市场等权)")
print("=" * 88)
print(f"{'年':>6} {'成分股':>7} {'交易日':>6} {'全年日超额':>11} {'t':>7} "
      f"{'除权日':>9} {'非除权日':>10} {'t(非除权)':>10}")
rows = []
for y, sub in d.groupby("y"):
    e = sub.port_e.to_numpy()
    t = e.mean() / (e.std(ddof=1) / np.sqrt(len(e)))
    ned = len(sub[sub.has_any == 1]); nod = len(sub[sub.has_any == 0])
    ae = sub[sub.has_any == 1].port_e.to_numpy()
    ao = sub[sub.has_any == 0].port_e.to_numpy()
    to = ao.mean() / (ao.std(ddof=1) / np.sqrt(len(ao))) if len(ao) > 2 else np.nan
    rows.append((y, e.mean(), t, ao.mean(), to))
    print(f"{y:>6} {int(sub.n_names.mean()):>7} {len(e):>6} {e.mean():>+10.4%} {t:>+7.2f} "
          f"{ae.mean():>+9.4%} {ao.mean():>+10.4%} {to:>+10.2f}")

print()
print("=" * 88)
print("② 汇总 (按**日**聚合后跨年合并)")
print("=" * 88)
allh = d[d.has_any == 1].port_e.to_numpy()
allo = d[d.has_any == 0].port_e.to_numpy()
allo_ = d[(d.has_any == 0) & (d.y >= 2018)].port_e.to_numpy()   # 与 §10.9 近段可比
def tt(x):
    return x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))
print(f"  除权日   (n={len(allh):>5} 日): 日超额 {allh.mean():>+8.4%}  t={tt(allh):>+6.2f}")
print(f"  非除权日 (n={len(allo):>5} 日): 日超额 {allo.mean():>+8.4%}  t={tt(allo):>+6.2f}")
print(f"  非除权日, 仅 2018+ (n={len(allo_):>5} 日): 日超额 {allo_.mean():>+8.4%}  t={tt(allo_):>+6.2f}")
print()
print(f"  年化估算: 除权日贡献 ≈ {allh.mean()*len(d[d.has_any==1])/len(d.groupby('y')):.4%}/年"
      f";  非除权日贡献 ≈ {allo.mean()*(len(d)-len(allh))/len(d.groupby('y')):.4%}/年")
print()
print("判据: 非除权日 |t| < 2 ⇒ 宿主≈市场 ⇒ 「市场 + overlay」成立;")
print("      非除权日显著为负 ⇒ 宿主坏掉 ⇒ 关闭。")
print("⚠️ 若为非除权日显著为正 ⇒ 不得当 alpha 欢呼 (§8.3), 需另走 §5/§7 全套验证。")

print()
print("=" * 88)
print("③ ★ 三种「除权日」口径对照 —— 定位那个 6 倍差")
print("=" * 88)
NY = d.y.nunique()
for col, nm in [("has_any", "全部公司行动 (含送股/配股/低息)"),
                ("has_pc",  "纯现金分红 (任意股息率)"),
                ("has_hy",  "纯现金且股息率 ≥4%  ← §10.9 量的是这个")]:
    a = d[d[col] == 1].port_e.to_numpy()
    if len(a) < 5: print(f"  {nm}: 样本不足"); continue
    t = a.mean() / (a.std(ddof=1) / np.sqrt(len(a)))
    print(f"  {nm:>34}: n={len(a):>4} 日, 日超额 {a.mean():>+8.4%} (t={t:>+5.2f})"
          f"  ⇒ 年化拖累 {a.mean()*len(a)/NY:>+8.4%}/年")
con.close()
