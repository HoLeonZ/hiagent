"""§10.12(g) 预登记的入口: ① 近期子段单独算; ② **组合层季节检验**。

## 季节陷阱是什么
除权日**集中在 6–7 月**。若组合**在 6–7 月整体跑输市场** (任何原因), 那整段季节拖累都会被
记成"除权日拖累" —— 而 overlay 只在**具体那几天**空仓, **captures 不到**季节性拖累。
§10.10 在**事件层**否掉了季节解释 (逐事件、同日全市场对照); **组合层没有做同样的检验**。

## ★ 预登记设计 (看数之前)
**月内配对**: 对每个 (年, 月) 同时含有"有票除权"与"无票除权"两种交易日的情况,
分别算组合日超额, 取 **配对差 (除权日 − 非除权日)**, 再对配对求平均。
* **H_date**: 配对差 ≈ 原始差 ⇒ 除权日特有 ⇒ overlay 抓得到;
* **H_season**: 配对差塌到 ≈ 0 ⇒ 只是季节 ⇒ overlay 抓不到, §10.12 的框架死掉。

**判据**: 配对差 / 原始差 **≥ 2/3** ⇒ H_date;  **< 1/3** ⇒ H_season; 之间 ⇒ 说不清。

**② 近期子段**: 持有年 2022–2026 (选票用 2021–2025 的事件), 日域 2021-10-01 起。
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
            WHERE e.ex_date BETWEEN '2016-01-01' AND '{END}' AND {PURE}),
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
SELECT y, date, avg(e) AS port_e, count(*) AS n_names,
       max(CASE WHEN is_ex THEN 1 ELSE 0 END) AS has_ex
FROM j GROUP BY y, date
"""
d = con.execute(SQL).fetchdf().dropna()
d["ym"] = d.date.astype(str).str[:7]
d["mon"] = d.date.astype(str).str[5:7]

def tt(x):
    return x.mean() / (x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 2 else np.nan

def decompose(sub, label):
    a = sub[sub.has_ex == 1].port_e.to_numpy()
    b = sub[sub.has_ex == 0].port_e.to_numpy()
    raw = a.mean() - b.mean()
    # 月内配对
    diffs = []
    for ym, g in sub.groupby("ym"):
        ae = g[g.has_ex == 1].port_e.to_numpy()
        be = g[g.has_ex == 0].port_e.to_numpy()
        if len(ae) >= 1 and len(be) >= 1:
            diffs.append(ae.mean() - be.mean())
    diffs = np.array(diffs)
    paired = diffs.mean() if len(diffs) else np.nan
    print(f"\n【{label}】 除权日 {len(a)} 日 / 非除权日 {len(b)} 日")
    print(f"  除权日   日超额 {a.mean():>+8.4%} (t={tt(a):>+5.2f})")
    print(f"  非除权日 日超额 {b.mean():>+8.4%} (t={tt(b):>+5.2f})")
    print(f"  原始差 (除权 − 非除权) = {raw:>+8.4%}")
    print(f"  月内配对差 (n={len(diffs)} 个月) = {paired:>+8.4%}   (t={tt(diffs):>+5.2f})" if len(diffs) else "  月内配对: 无")
    ratio = paired / raw if raw != 0 else np.nan
    verdict = ("H_date (除权日特有)" if ratio >= 2/3 else
               "H_season (只是季节)" if ratio < 1/3 else "说不清")
    print(f"  配对/原始 = {ratio:>+7.2f}   ⇒ **{verdict}**")
    return ratio

print("=" * 84)
print("① 全期 (持有年 2017–2026)")
print("=" * 84)
decompose(d, "全期")

print()
print("=" * 84)
print("② 近期子段 (持有年 2022–2026, 日域 2021-10 起) —— 与 §10.9 的 −0.99%/次 同期")
print("=" * 84)
rec = d[d.date >= np.datetime64("2021-10-01")]
decompose(rec, "近期")

print()
print("=" * 84)
print("③ 逐月看: 除权日是否只是集中在少数月份, 以及那些月份的非除权日是否也差")
print("=" * 84)
print(f"{'月':>4} {'除权日数':>8} {'非除权日数':>10} {'除权日超额':>11} {'非除权日超额':>12} {'月内差':>10}")
for mon, g in d.groupby("mon"):
    ae = g[g.has_ex == 1].port_e.to_numpy()
    be = g[g.has_ex == 0].port_e.to_numpy()
    if len(ae) == 0: continue
    print(f"{mon:>4} {len(ae):>8} {len(be):>10} {ae.mean():>+10.4%} "
          f"{(be.mean() if len(be) else float('nan')):>+11.4%} "
          f"{(ae.mean()-be.mean() if len(be) else float('nan')):>+10.4%}")
con.close()
