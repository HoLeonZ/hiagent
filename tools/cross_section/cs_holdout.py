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
# 对应登记册: §7.13 —— **样本外** 2017-07..2022-09 (三段 + 全段), 逐段报告不做挑选
# 跑法: `python tools/cross_section/cs_holdout.py`
"""**真正的样本外**: 2016-09..2022-09 —— 前面 90 轮从未用过的时段。

素材: 全部 §7 分析只用过 IND (2022-10..2024-09) 与 W2 (2024-10..2026-09)。
DB 覆盖 2016-09-02 起 ⇒ **2017-07..2022-09 是完全未被碰过的 ~5.2 年**,
且跨越 2018 熊市 / 2019Q1 急涨 / 2021-22 下跌, regime 比那两个窗口宽得多。

构造: **price-neutral** (§7.12 定下的最终构造) —— 每个价格层内取该层 amt_ratio 最低 1/5,
层间等权。逐段报告, **不做任何挑选**。
"""
import sys, duckdb
import numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hiagent_config import DB_PATH

H, WARM = 10, 400
SEGS = [("H1 2017-07..2019-06", "2017-07-01", "2019-06-30"),
        ("H2 2019-07..2021-06", "2019-07-01", "2021-06-30"),
        ("H3 2021-07..2022-09", "2021-07-01", "2022-09-30"),
        ("全段 2017-07..2022-09", "2017-07-01", "2022-09-30")]
SQL = f"""
WITH b AS (
  SELECT thscode, date, open, close, amount,
    COUNT(*) OVER (PARTITION BY thscode ORDER BY date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS n200,
    AVG(amount) OVER (PARTITION BY thscode ORDER BY date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS amt60,
    LEAD(open,1) OVER w AS e_open, LEAD(close,{H+1}) OVER w AS fx
  FROM raw_kline_daily WHERE date BETWEEN ? AND ?
    AND (thscode LIKE '60%.SH' OR thscode LIKE '00%.SZ')
  WINDOW w AS (PARTITION BY thscode ORDER BY date)
)
SELECT date, thscode, close AS px, amount/NULLIF(amt60,0) AS sig,
       fx/NULLIF(e_open,0)-1 AS gross
FROM b WHERE n200>=200 AND amt60>0 AND fx IS NOT NULL AND e_open>0 AND px>0
      AND date >= ? AND date <= ?
ORDER BY date, thscode
"""
con = duckdb.connect(str(DB_PATH), read_only=True)
print(f"{'段':>24} {'日数':>6} {'档内只数':>8} {'日频超额':>10} {'t':>7} {'年化':>9}")
for lbl, a, bb in SEGS:
    ws = str((np.datetime64(a)-np.timedelta64(WARM,"D")).astype("datetime64[D]"))
    df = con.execute(SQL, [ws, bb, a, bb]).fetchdf()
    df = df[np.isfinite(df.sig) & np.isfinite(df.gross) & (df.px>0)]
    if df.empty: print(f"{lbl:>24}  空"); continue
    df["pq"] = df.groupby("date")["px"].rank(pct=True, method="first")
    df["q"] = np.minimum((df["pq"]*5).astype(int), 4)
    df["in"] = df.groupby(["date","q"])["sig"].rank(pct=True, method="first") <= 0.20
    lo = df[df["in"]]
    per = lo.groupby("date")["gross"].mean()
    mkt = df.groupby("date")["gross"].mean()
    ex = (per - mkt).dropna().to_numpy()
    t = ex.mean()/(ex.std(ddof=1)/np.sqrt(len(ex)))
    print(f"{lbl:>24} {len(ex):>6} {lo.groupby('date').size().median():>8.0f} "
          f"{ex.mean():>+10.4%} {t:>+7.2f} {ex.mean()*(244/H):>+8.2%}")
con.close()
