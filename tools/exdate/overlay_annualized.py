"""§10.7(e) 的那个**未做的测算** —— 把"每次事件的幅度 vs 每次事件的成本"
换成**策略层面的年化量**, 再判它值不值得做。

## 要回答的问题 (§10.7(e) 原文)
> "回避除权日"的成本是**额外往返**, 但若一个策略**本来就在那几天换手**,
> 边际成本就不是全额往返 ⇒ 同一个效应在不同策略里的净值不同。**本节没有做这个测算。**

## 为什么原判法可能过强
§10.4 把 **每次事件** 的幅度 (0.15%) 与 **每次事件** 的往返成本 (0.10–0.15%) 相比
⇒ 判"≤成本 ⇒ 不可交易"。但一个**策略**不会只碰到一次事件; 它会在**一年里**
碰上它持有的**每只票各一次(或几次)**的事件。
⇒ 正确的量是**年化**: `年化幅度 = 每次事件幅度 × 每只票每年的事件数`。
这是**上界**, 因为下面假设了"边际成本 = 0"(§10.7(e) 设想的那种情形)。

## ★ 预登记判据 (看数之前定下, 事后不改)
1. **年化上界** = 每次事件幅度 × 每票每年事件数。
2. 判据: 若年化上界 **< 1%/年** ⇒ **即使边际成本为零, 这个 overlay 也不足以
   把一个策略从"不可用"推到"可用"** ⇒ **§10.7(e) 由算术关闭, 与成本无关**。
   阈值 1%/年 的依据: §7 那条线**净** +3.4~5.2%/年 才勉强算"有东西";
   而 1%/年 已远低于这批策略自身的年化波动 (§8.2 的范围)。
3. 稳健性: 同时给一张**对事件频率的敏感度表** (0.5/1/2/4 次每票每年),
   使结论不依赖我测到的那一个频率数。
4. **数据纪律**: v_daily_hfq 在 2026-09-21..30 被 §13 污染 (复权因子表落后)
   ⇒ 本脚本把窗口**截到 2026-09-18**。§10.7 原脚本没截, 这是本次的一处收紧。
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import duckdb
import numpy as np
from hiagent_config import DB_PATH

END = "2026-09-18"          # ← §13 污染截断
SEC = [("2016-10..2021-09", "2016-10-01", "2021-09-30", 5.0),
       ("2021-10..2026-09", "2021-10-01", END,        4.97)]
PURE_CASH = "dividend_per_share > 0 AND per_share_bonus = 0 AND rights_ratio = 0"

con = duckdb.connect(str(DB_PATH), read_only=True)

# --- 每次事件的幅度: 与 §10.7 一字不差的构造 (只把末日截断) ---
SQL_EX = """
WITH ev AS (SELECT DISTINCT thscode, ex_date FROM raw_adjustment_events
            WHERE ex_date BETWEEN ? AND ? AND {tf}),
p AS (SELECT thscode, date, close, LAG(close,1) OVER w AS c1 FROM v_daily_hfq
      WHERE date BETWEEN '2016-09-01' AND ? WINDOW w AS (PARTITION BY thscode ORDER BY date)),
m AS (SELECT date, avg(close/c1-1) AS mkt FROM p GROUP BY date)
SELECT ev.ex_date, avg(p.close/p.c1-1) - min(m.mkt) AS ex, count(*) AS nev
FROM ev JOIN p ON p.thscode=ev.thscode AND p.date=ev.ex_date
        JOIN m ON m.date=ev.ex_date
GROUP BY ev.ex_date ORDER BY ev.ex_date
"""

print("=" * 78)
print("① 每次事件的幅度 (构造同 §10.7, 末日截到 %s)" % END)
print("=" * 78)
print(f"{'时段':>20} {'事件日':>6} {'事件数':>7} {'事件日超额':>11} {'t':>7}")
per_event = {}
for lbl, a, b, yrs in SEC:
    df = con.execute(SQL_EX.format(tf=PURE_CASH), [a, b, END]).fetchdf().dropna()
    ex = df.ex.to_numpy()
    t = ex.mean() / (ex.std(ddof=1) / np.sqrt(len(ex)))
    per_event[lbl] = ex.mean()
    print(f"{lbl:>20} {len(df):>6} {int(df.nev.sum()):>7} {ex.mean():>+10.4%} {t:>+7.2f}")

# --- 每票每年的事件数 ---
print()
print("=" * 78)
print("② 每票每年的除权事件数 (纯现金分红) —— 决定「一个持仓一年碰到几次」")
print("=" * 78)
print(f"{'时段':>20} {'事件数':>7} {'有事件票数':>10} {'窗口内票数':>10} {'次数/票/年':>11}")
freq = {}
for lbl, a, b, yrs in SEC:
    n_ev = con.execute(
        f"SELECT COUNT(DISTINCT (thscode, ex_date)) FROM raw_adjustment_events "
        f"WHERE ex_date BETWEEN ? AND ? AND {PURE_CASH}", [a, b]).fetchone()[0]
    n_named = con.execute(
        f"SELECT COUNT(DISTINCT thscode) FROM raw_adjustment_events "
        f"WHERE ex_date BETWEEN ? AND ? AND {PURE_CASH}", [a, b]).fetchone()[0]
    n_all = con.execute(
        "SELECT COUNT(DISTINCT thscode) FROM raw_kline_daily "
        "WHERE date BETWEEN ? AND ?", [a, b]).fetchone()[0]
    f = n_ev / n_all / yrs          # 对**任意持仓**的期望次数 (不看它是否分红)
    freq[lbl] = f
    print(f"{lbl:>20} {n_ev:>7} {n_named:>10} {n_all:>10} {f:>11.3f}")

# --- ③ 年化上界 + 敏感度 ---
print()
print("=" * 78)
print("③ 年化上界 = 每次事件幅度 × 每票每年次数   (边际成本 = 0 的假设下)")
print("=" * 78)
print(f"{'时段':>20} {'每次事件':>10} {'实测频率':>10} {'年化上界':>10}")
for lbl, _, _, _ in SEC:
    ann = per_event[lbl] * freq[lbl]
    print(f"{lbl:>20} {per_event[lbl]:>+9.4%} {freq[lbl]:>10.3f} {ann:>+9.4%}")

print()
print("敏感度 (不依赖我测到的频率):年化上界 vs 假设的每票每年次数")
print(f"{'假设次数/票/年':>16} " + "".join(f"{l:>16}" for l, *_ in SEC))
for k in (0.5, 1.0, 2.0, 4.0):
    row = "".join(f"{per_event[l]*k:>+15.4%} " for l, *_ in SEC)
    print(f"{k:>16.1f} " + row)

print()
print("判据 (预登记): 年化上界 < +1%/年 ⇒ 即使边际成本为零, 也不足以支撑一个策略。")
for lbl, *_ in SEC:
    ann = per_event[lbl] * freq[lbl]
    killed = abs(ann) < 0.01
    print(f"  {lbl:>20}: 年化上界 {ann:>+8.4%}  ⇒  {'关闭' if killed else '未关闭'} "
          f"(即使频率翻 4 倍: {abs(per_event[lbl])*freq[lbl]*4:>7.4%})")
con.close()
