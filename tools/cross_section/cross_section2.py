# ⚠️ **来源与被抢救的原因** (2026-10-19, §13.41)
# 本脚本原先只存在于 `/tmp/hiagent_mining/` —— 一个**设计上易失**的位置。
# 也就是说: 到 2026-10-19 为止, 登记册 §7 (唯一一个非族方向, 也是全篇最载重的结论之一)
# **没有任何可以从仓库复现的入口** —— 它的 17 处「复现」全是**统计意义**的
# (两窗口同号 / 外部队列复现), 没有一处是**可以运行的命令**;
# 且它的核心变量 `amt_ratio` 在仓库的任何 .py 里**都不存在**。
# 本节把三支**权威脚本**抢救进 `tools/cross_section/`, 只改了一处:
# 把硬编码的 `sys.path.insert(0, "/Users/holeon/code/hiagent")` 换成**相对本文件**的路径,
# 使它在任何 clone 上都能跑。**其余一字未动。**
#
# 对应登记册: §7.4 / §7.6 —— 横截面**按日聚合**的 t 统计量 (样本内 IND / W2)
# 跑法: `python tools/cross_section/cross_section2.py`
"""横截面信号筛查 —— **按日聚合**后的 t 统计量。

⚠️ 上一版把 878,916 个 (code,date) 行当成独立样本算 t, 得到 t=−20 这种数。
**那是错的**: 同一天的所有票高度相关, 有效独立单位是**日期数** (~480), 不是行数。
(这与本循环前面几次"看起来像结果但不合常识"是同一类 —— 但这次不是 bug,
是**统计口径**错: 数字算对了, 显著性算错了。)

正确做法: 每天算一个**跨档价差**, 得到一条日频序列, 再对**日期**做 t。
"""
import sys, duckdb
import numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hiagent_config import DB_PATH

WIN = {"IND": ("2022-10-03", "2024-09-30"), "W2": ("2024-10-08", "2026-09-30")}
SIG = {"mom120": "close/NULLIF(c120,0)-1", "rev20": "close/NULLIF(c20,0)-1",
       "hl20": "hl20", "amt_ratio": "amount/NULLIF(amt60,0)"}

SQL = """
WITH b AS (
  SELECT thscode, date, open, close, high, low, amount,
    LAG(close,120) OVER w AS c120, LAG(close,20) OVER w AS c20,
    COUNT(*) OVER (PARTITION BY thscode ORDER BY date
                   ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS n200,
    AVG((high-low)/NULLIF(close,0)) OVER (PARTITION BY thscode ORDER BY date
        ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS hl20,
    AVG(amount) OVER (PARTITION BY thscode ORDER BY date
        ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS amt60,
    LEAD(open,1) OVER w AS e_open, LEAD(close,2) OVER w AS f1, LEAD(close,6) OVER w AS f5
  FROM raw_kline_daily
  WHERE date BETWEEN ? AND ? AND (thscode LIKE '60%.SH' OR thscode LIKE '00%.SZ')
  WINDOW w AS (PARTITION BY thscode ORDER BY date)
), s AS (
  SELECT date, thscode, {sig} AS sig, f1/NULLIF(e_open,0)-1 AS r1, f5/NULLIF(e_open,0)-1 AS r5
  FROM b WHERE n200 >= 200 AND c120 IS NOT NULL AND e_open > 0
), x AS (
  SELECT date, thscode, sig, r1 - AVG(r1) OVER (PARTITION BY date) AS ex1,
         r5 - AVG(r5) OVER (PARTITION BY date) AS ex5
  FROM s WHERE r1 IS NOT NULL AND r5 IS NOT NULL AND sig IS NOT NULL
), d AS (
  SELECT date, sig, ex1, ex5,
         ntile(10) OVER (PARTITION BY date ORDER BY sig, thscode) AS dec FROM x
)
SELECT date, dec, avg(ex1) AS e1, avg(ex5) AS e5, count(*) AS n
FROM d GROUP BY date, dec
ORDER BY date, dec
"""

con = duckdb.connect(str(DB_PATH), read_only=True)
for wn, (w0, w1) in WIN.items():
    print(f"\n########## {wn} ##########")
    for name, expr in SIG.items():
        df = con.execute(SQL.replace("{sig}", expr), [w0, w1]).fetchdf()
        if df.empty:
            print(f"  {name}: 空"); continue
        piv1 = df.pivot(index="date", columns="dec", values="e1")
        piv5 = df.pivot(index="date", columns="dec", values="e5")
        ndate = len(piv5)
        print(f"\n  --- {name} ---  日数={ndate}")
        print(f"  {'档':>4} {'h=1 日频均值':>13} {'t':>7} {'h=5 日频均值':>13} {'t':>7}")
        for d in (1, 2, 9, 10):
            if d not in piv1.columns: continue
            a1, a5 = piv1[d].to_numpy(), piv5[d].to_numpy()
            t1 = a1.mean()/(a1.std(ddof=1)/np.sqrt(ndate))
            t5 = a5.mean()/(a5.std(ddof=1)/np.sqrt(ndate))
            print(f"  {d:>4} {a1.mean():>+13.4%} {t1:>7.2f} {a5.mean():>+13.4%} {t5:>7.2f}")
        sp = piv5[10].to_numpy() - piv5[1].to_numpy()
        tsp = sp.mean()/(sp.std(ddof=1)/np.sqrt(ndate))
        print(f"  跨档价差(10−1) h=5: 日均 {sp.mean():+.4%}  t={tsp:+.2f}  (日数 {ndate})")
con.close()
