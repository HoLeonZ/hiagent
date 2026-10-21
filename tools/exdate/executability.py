"""§10.9(h) 清单最后一条能**在本库内检验**的: ④ 容量 / 涨跌停 —— overlay 到底做不做得成?

## overlay 的两条腿 (§10.9(f) 的自然窗口 T−1..T)
* **卖出腿** 在 **T−1** (收盘前卖出, 从此空仓跨过除权日);
* **买回腿** 在 **T**   (除权日收盘买回)。

## ★ 预登记判据 (看数之前定下, 事后不改)
**A. 可执行性** —— 被制度卡住的比例
* 卖出腿被卡: T−1 **封跌停** (抛不掉);
* 买回腿被卡: T  **封涨停** (买不到);
* 另有 **停牌**: T−1 或 T 无行情行。
**判据: 三者合计 ≤ 5% ⇒ 可执行。**

**B. 容量** —— §4 成交量参与上限 = `min(qty, bar_volume × 10%)`。
以**成交额**近似: 单票可持有市值上限 ≈ `10% × amount`。
**判据: 持仓中**最弱那只** (p05) 的上限仍能支撑本仓库预设的规模 (¥1M / 5 只 ≈ ¥20 万/票) ⇒ 容量不咬合。**

## 代理的局限 (必须写明)
没有日内数据 ⇒ 用**调整后日收益**是否触板来代理"封板"。除权日的涨跌停基准是**除权参考价**,
所以用调整后收益是对的 (原始收益在除权日会被机械跳空污染)。
**"触板" ≠ "封死"** —— 封死需要盘口无对手盘, 本库看不到。故这是一个**上界**: 真实被卡比例**只会更低**。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import duckdb, numpy as np
from hiagent_config import DB_PATH

END = "2026-09-18"
PURE = "dividend_per_share > 0 AND per_share_bonus = 0 AND rights_ratio = 0"

def thr(code: str) -> float:
    """该票的涨跌停幅度 (代理阈值取 0.97×, 留一点缓冲)。"""
    if code.startswith(("300", "301", "688")): return 0.20 * 0.97
    if code.startswith(("920", "8", "4")):     return 0.30 * 0.97
    return 0.10 * 0.97

con = duckdb.connect(str(DB_PATH), read_only=True)
SQL = f"""
WITH ev AS (SELECT DISTINCT e.thscode, e.ex_date, e.dividend_per_share AS D,
                   (SELECT max(r.date) FROM raw_kline_daily r
                     WHERE r.thscode=e.thscode AND r.date < e.ex_date) AS d0
            FROM raw_adjustment_events e
            WHERE e.ex_date BETWEEN ? AND ? AND {PURE}),
evy AS (SELECT ev.thscode, ev.ex_date, ev.D/r.close AS yld
        FROM ev JOIN raw_kline_daily r ON r.thscode=ev.thscode AND r.date=ev.d0 WHERE r.close>0),
px AS (SELECT thscode, date, close, LAG(close,1) OVER w AS c1,
              LEAD(close,1) OVER w AS c2
       FROM v_daily_hfq WHERE date BETWEEN '2016-09-01' AND '{END}'
       WINDOW w AS (PARTITION BY thscode ORDER BY date)),
q AS (SELECT thscode, date, close/c1 - 1 AS r FROM px WHERE c1 IS NOT NULL),
s AS (SELECT thscode, date, r,
             LEAD(r,1) OVER w2 AS r_next,
             LAG(r,1)  OVER w2 AS r_prev
      FROM q WINDOW w2 AS (PARTITION BY thscode ORDER BY date)),
am AS (SELECT thscode, date, amount FROM raw_kline_daily
       WHERE date BETWEEN '2016-09-01' AND '{END}')
SELECT evy.thscode, evy.ex_date, evy.yld,
       s1.r AS r_tm1, s0.r AS r_t, am1.amount AS amt_tm1, am0.amount AS amt_t
FROM evy
LEFT JOIN s  s1 ON s1.thscode=evy.thscode AND s1.date = (SELECT max(x.date) FROM s x
                 WHERE x.thscode=evy.thscode AND x.date < evy.ex_date)
LEFT JOIN s  s0 ON s0.thscode=evy.thscode AND s0.date = evy.ex_date
LEFT JOIN am am1 ON am1.thscode=evy.thscode AND am1.date=(SELECT max(y.date) FROM am y
                 WHERE y.thscode=evy.thscode AND y.date < evy.ex_date)
LEFT JOIN am am0 ON am0.thscode=evy.thscode AND am0.date=evy.ex_date
WHERE evy.yld < 1
"""
for lbl, a, b in [("早期 2016-10..2021-09", "2016-10-01", "2021-09-30"),
                  ("近期 2021-10..2026-09", "2021-10-01", END)]:
    d = con.execute(SQL, [a, b]).fetchdf()
    hy = d[d.yld >= 0.04].copy()
    print("=" * 78); print(f"【{lbl}】 [4%+) 事件 {len(hy)} 笔"); print("=" * 78)
    nomiss = hy.dropna(subset=["r_tm1", "r_t"]).copy()
    susp = len(hy) - len(nomiss)
    t  = nomiss.thscode.map(thr).to_numpy()
    sell_blocked = (nomiss.r_tm1.to_numpy() <= -t)
    buy_blocked  = (nomiss.r_t.to_numpy()   >=  t)
    print(f"  A 可执行性")
    print(f"    停牌 (T−1 或 T 无行情)   : {susp:>5} / {len(hy):>5} = {susp/len(hy):>6.2%}")
    print(f"    卖出腿被卡 (T−1 触跌停)  : {sell_blocked.sum():>5} = {sell_blocked.mean():>6.2%}")
    print(f"    买回腿被卡 (T  触涨停)   : {buy_blocked.sum():>5} = {buy_blocked.mean():>6.2%}")
    tot = (susp + sell_blocked.sum() + buy_blocked.sum()) / len(hy)
    print(f"    合计                     : {tot:>6.2%}   判据 ≤5% ⇒ **{'通过' if tot <= 0.05 else '不通过'}**")
    print(f"  B 容量 (§4 上限 = 10% × 成交额, 单票可持市值)")
    for c, nm in [("amt_tm1", "T−1"), ("amt_t", "T")]:
        v = hy[c].dropna().to_numpy() * 0.10
        print(f"    {nm:>4}: p05 ¥{np.percentile(v,5)/1e4:>9.1f}万  中位 ¥{np.median(v)/1e4:>9.1f}万"
              f"   p95 ¥{np.percentile(v,95)/1e4:>10.1f}万")
    v = hy["amt_t"].dropna().to_numpy() * 0.10
    print(f"    ⇒ 5 只组合按 p05 计可容 AUM ≈ ¥{5*np.percentile(v,5)/1e4:.1f}万"
          f"  (预设 ¥1M/5 只 = ¥20万/票 ⇒ **{'够' if np.percentile(v,5) >= 2e5 else '不够'}**)")
    print()
con.close()
