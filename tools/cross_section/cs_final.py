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
# 对应登记册: §7.12 —— **价格中性**构造 (层内取低量能、层间等权) + §4 参与上限的**容量咬合**归因
# 跑法: `python tools/cross_section/cs_final.py`
"""两件事: (1) 容量咬合归因 (§4 参与上限 加/不加 对照)
           (2) **价格中性**构造 —— 层内取低量能、**层间等权**

⚠️ 构造必须**中性**, 不能"挑 t 最高的那几层" —— 那是 in-sample 择优 (§5)。
所以: 在**每一个**价格层内部取该层 amt_ratio 最低的 1/5, 然后把五层**等权**合成。
这样价格暴露按构造被中和, 且没有挑层。
"""
import sys, duckdb
import numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hiagent_config import DB_PATH

COMM, STAMP, MINFEE, VOLP, WARM = 0.00025, 0.0005, 5.0, 0.10, 400
WIN = {"IND": ("2022-10-03", "2024-09-30"), "W2": ("2024-10-08", "2026-09-30")}
def sql(h):
    return f"""
WITH b AS (
  SELECT thscode, date, open, close, volume, amount,
    COUNT(*) OVER (PARTITION BY thscode ORDER BY date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS n200,
    AVG(amount) OVER (PARTITION BY thscode ORDER BY date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS amt60,
    LAG(close,1) OVER w AS pc,
    LEAD(open,1) OVER w AS e_open, LEAD(volume,1) OVER w AS e_vol, LEAD(close,{h+1}) OVER w AS fx
  FROM raw_kline_daily WHERE date BETWEEN ? AND ?
    AND (thscode LIKE '60%.SH' OR thscode LIKE '00%.SZ')
  WINDOW w AS (PARTITION BY thscode ORDER BY date)
)
SELECT date, thscode, close AS px, amount/NULLIF(amt60,0) AS sig, e_open, e_vol, pc, fx
FROM b WHERE n200>=200 AND amt60>0 AND fx IS NOT NULL AND e_open>0 AND px>0 AND date >= ? AND date <= ?
ORDER BY date, thscode
"""
def pick(df, mode):
    d = df[np.isfinite(df.sig)].copy()
    if mode == "naive":
        d["sel"] = d.groupby("date")["sig"].rank(pct=True, method="first") <= 0.10
    else:                                   # 价格中性: 层内 1/5, 层间等权
        d["pq"] = d.groupby("date")["px"].rank(pct=True, method="first")
        d["q"] = np.minimum((d["pq"] * 5).astype(int), 4)
        d["in"] = d.groupby(["date", "q"])["sig"].rank(pct=True, method="first") <= 0.20
        d["sel"] = d["in"]
    return d[d["sel"]]

def chain(sel, h, cap0, cap_on, sig_dates):
    by = {k: v for k, v in sel.groupby("date")}
    cash = cap0
    for d in sig_dates:
        g = by.get(d)
        if g is None or g.empty: continue
        g = g[~((g.pc > 0) & (g.e_open / g.pc - 1.0 >= 0.095))]
        if g.empty: continue
        per = cash / len(g)
        spent = 0.0
        for r in g.itertuples(index=False):
            p = r.e_open
            lots = int(per / (p * 100))
            if cap_on: lots = min(lots, int((r.e_vol or 0) * VOLP // 100))
            sh = lots * 100
            if sh < 100: continue
            nt = sh * p
            if spent + nt > cash: continue
            cash -= nt + max(nt*COMM, MINFEE); spent += nt + max(nt*COMM, MINFEE)
            assert cash >= -1e-6
            pr = sh * r.fx
            cash += pr - max(pr*COMM, MINFEE) - pr*STAMP
            assert cash >= -1e-6
    return cash

con = duckdb.connect(str(DB_PATH), read_only=True)
H = 10
for wn,(w0,w1) in WIN.items():
    ws = str((np.datetime64(w0)-np.timedelta64(WARM,"D")).astype("datetime64[D]"))
    df = con.execute(sql(H), [ws,w1,w0,w1]).fetchdf()
    sig_dates = sorted(df["date"].unique())[::H]
    print(f"\n########## {wn} ##########  日 {df['date'].nunique()}  调仓 {len(sig_dates)} 次")
    allg = df[np.isfinite(df.sig)].groupby("date")["fx"].mean()
    for mode in ("naive", "price_neutral"):
        sel = pick(df, mode)
        per = sel.groupby("date").apply(lambda g: (g.fx/g.e_open-1).mean(), include_groups=False)
        mkt = df[np.isfinite(df.sig)].groupby("date").apply(lambda g: (g.fx/g.e_open-1).mean(), include_groups=False)
        ex = (per - mkt).dropna().to_numpy()
        t = ex.mean()/(ex.std(ddof=1)/np.sqrt(len(ex)))
        r_cap = chain(sel, H, 200_000_000, True, sig_dates)
        r_noc = chain(sel, H, 200_000_000, False, sig_dates)
        print(f"  {mode:>14}: 档内 {sel.groupby('date').size().median():>4.0f} 只  日频超额 {ex.mean():>+8.4%} t={t:>+5.2f}")
        print(f"                  ¥200M: 有容量 {r_cap/2e8-1:>+8.2%}  无容量 {r_noc/2e8-1:>+8.2%}  "
              f"**容量咬合 {((r_noc-r_cap)/2e8)*100:>+7.2f}pp**")
con.close()
