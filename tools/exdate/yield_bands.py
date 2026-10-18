"""§10 最后一条"未做"的异质性轴: 除权日效应 vs **分红率高低** (§10.5 / §10.7(g))。

## 为什么这是**唯一**还可能把 §10 从"关闭"翻回来的方向
§10.8 已证: 纯现金分红事件在**聚合**上, 年化上界只有 −9bp/年 (近期)。
若效应**集中在高股息那一端**, 那么"持有某类票"的年化上界就会随之放大。
⇒ 本节的产出要么是"放大到够门槛", 要么是"这一轴是平的" ⇒ **§10 完全关闭**。

## ★ 这一轴**自带判别器** —— 所以无论结果如何都值得做
用**后复权**价测出来的超额, 在复权正确时应当**不含**那个机械跳空。
于是曲线的形状能区分两种解释:
* **H_real**: 效应大致**与股息率无关** (一个每次事件的行为/税负效应);
* **H_art**: 效应**与股息率成比例** ⇒ 与"复权因子有系统性残差"**无法区分** ⇒
  不能当作可交易边际, 而应先怀疑口径 (§10.2 只抽查过 1 个例子)。

## ★ 预登记划分 (不是搜出来的子群)
按**绝对股息率**分 5 档, 边界在看数之前定死 (用绝对档而不用样本分位 ⇒ 无数据依赖的切点):
    [0, 0.5%) / [0.5%, 1%) / [1%, 2%) / [2%, 4%) / [4%, +∞)
股息率 = `dividend_per_share / raw_close(T−1)` (§3 双价: 收益率口径用**未复权真实价**)。

## ★ 预登记判据 (看数之前定下, 事后不改)
1. **重开**: 最高档的年化上界 (该档每次事件幅度 × 该档每票每年事件数) **≥ 1%/年**
   **且** 幅度沿 5 档**单调**。
2. 否则 ⇒ **§10 关闭** (异质性轴是平的, 或放大不够)。
3. 附带: 若曲线近似**正比**于股息率 ⇒ 记 H_art 嫌疑, 并**不下"可交易"结论**。

## 纪律
* 逐**事件日**聚合 (§7.3), 不按事件池化;
* v_daily_hfq 在 2026-09-21..30 被 §13 污染 ⇒ 末日截到 **2026-09-18**;
* 本库内只有**样本内**证据 (§8.1) ⇒ 结论只能是否定性的或"上界"。
"""
import sys
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import duckdb
import numpy as np
from hiagent_config import DB_PATH

END = "2026-09-18"
SEC = [("早期 2016-10..2021-09", "2016-10-01", "2021-09-30", 5.0),
       ("近期 2021-10..2026-09", "2021-10-01", END,        4.97)]
BANDS = [(0.0000, 0.0050, "[0, 0.5%)"),
         (0.0050, 0.0100, "[0.5%, 1%)"),
         (0.0100, 0.0200, "[1%, 2%)"),
         (0.0200, 0.0400, "[2%, 4%)"),
         (0.0400, 99.0,   "[4%+)")]
PURE = "dividend_per_share > 0 AND per_share_bonus = 0 AND rights_ratio = 0"

con = duckdb.connect(str(DB_PATH), read_only=True)
SQL = f"""
WITH ev AS (SELECT DISTINCT e.thscode, e.ex_date, e.dividend_per_share,
                   (SELECT max(r.date) FROM raw_kline_daily r
                     WHERE r.thscode=e.thscode AND r.date < e.ex_date) AS d0
            FROM raw_adjustment_events e
            WHERE e.ex_date BETWEEN ? AND ? AND {PURE}),
evy AS (SELECT ev.thscode, ev.ex_date, ev.dividend_per_share / r.close AS yld
        FROM ev JOIN raw_kline_daily r ON r.thscode=ev.thscode AND r.date=ev.d0
        WHERE r.close > 0),
p AS (SELECT thscode, date, close, LAG(close,1) OVER w AS c1 FROM v_daily_hfq
      WHERE date BETWEEN '2016-09-01' AND ? WINDOW w AS (PARTITION BY thscode ORDER BY date)),
m AS (SELECT date, avg(close/c1-1) AS mkt FROM p GROUP BY date),
j AS (SELECT evy.yld, evy.ex_date, evy.thscode,
             p.close/p.c1-1 - m.mkt AS ex
      FROM evy JOIN p ON p.thscode=evy.thscode AND p.date=evy.ex_date
               JOIN m ON m.date=evy.ex_date
      WHERE evy.yld < 1)
SELECT yld, ex_date, thscode, ex FROM j
"""

print("=" * 84)
print("① 按预登记股息率档位: 除权日超额 (逐事件日聚合)")
print("=" * 84)
for lbl, a, b, yrs in SEC:
    raw = con.execute(SQL, [a, b, END]).fetchdf().dropna()
    print(f"\n--- {lbl}  (可用事件 {len(raw)}) ---")
    print(f"{'档位':>12} {'事件数':>7} {'事件日':>6} {'事件日超额':>11} {'t':>7} {'年化上界':>10}")
    prev, mono = None, True
    for lo, hi, name in BANDS:
        sub = raw[(raw.yld >= lo) & (raw.yld < hi)]
        if len(sub) < 200:
            print(f"{name:>12} {len(sub):>7}  —— 样本不足"); continue
        g = sub.groupby("ex_date").ex.mean()          # ← 逐事件日聚合
        ex = g.to_numpy()
        t = ex.mean() / (ex.std(ddof=1) / np.sqrt(len(ex)))
        n_names = sub.thscode.nunique()
        freq = len(sub) / n_names / yrs               # 该档"每票每年"事件数
        ann = ex.mean() * freq
        if prev is not None and ex.mean() > prev + 1e-9:
            mono = False
        prev = ex.mean()
        print(f"{name:>12} {len(sub):>7} {len(g):>6} {ex.mean():>+10.4%} {t:>+7.2f} {ann:>+9.4%}")
    print(f"  ⇒ 幅度沿档位单调(=越高的股息率越负)? **{'是' if mono else '否'}**")
    # 判别器: 幅度是否近似正比于股息率
    mids = []
    for lo, hi, name in BANDS:
        sub = raw[(raw.yld >= lo) & (raw.yld < hi)]
        if len(sub) >= 200:
            mids.append((sub.yld.mean(), sub.groupby("ex_date").ex.mean().mean()))
    if len(mids) >= 3:
        x = np.array([m[0] for m in mids]); y = np.array([m[1] for m in mids])
        slope = np.polyfit(x, y, 1)[0]
        r = np.corrcoef(x, y)[0, 1]
        print(f"  ⇒ 判别器: 超额对股息率的斜率 = {slope:+.4f}  (相关系数 r = {r:+.3f})")
        print(f"     若 |斜率| 很大且 r 接近 −1 ⇒ **与「复权残差」无法区分** (H_art), 不能当可交易边际;")
        print(f"     若斜率 ≈ 0 ⇒ 是与股息率无关的行为效应 (H_real)。")
con.close()
