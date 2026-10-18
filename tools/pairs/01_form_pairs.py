"""配对/统计套利: **第一步 —— 选对** (§9 表里唯一"未试且算得出来"的方向)。

## 为什么做这个
§9 的表把"配对/统计套利"标为**未试**; §9.2 **更正**了它的理由:
> 本仓库**有**做空机制 (`MARGIN_RATE` / `BORROW_ASSUMPTION`), 配对是**算得出来的**。
> 真正的障碍是 `availability = "assumed_unlimited"` 既不符现实、也无法被本库检验
> ⇒ **结论只能当上界**。

**而这条路至今没有任何实现。** 本节把它走第一步: 在**形成窗**里选出候选配对。

## ★ 预登记设计 (看数之前定死)
* **宇宙**: 主板 (60/00 开头), 形成窗内**日成交额中位数 ≥ ¥1 亿** (流动性下限, §4 容量前置),
  且**两个窗口都有行情**。
* **形成窗** `2021-10-01 .. 2023-09-30`; **测试窗** `2023-10-01 .. 2026-09-18` —— **互不重叠**。
* **配对**: 用**日对数收益**的 Pearson 相关; 取相关最高的 **K=100 对**,
  且**每只票至多出现在一对里**(配对不重叠 ⇒ 组合可解释)。
* β 由**形成窗**的 OLS (`log A = α + β log B`) 拟合, **固定**, 测试窗不再重估。

## ⚠️ 三条声明 (不写清就是违约)
1. **融券假设 (§4 明文要求)**: `availability = "assumed_unlimited"` (照抄本仓库
   `short_reversal/presets.py` 的 `BORROW_ASSUMPTION`), 借券成本 = `MARGIN_RATE` = **8.6%/年**
   (按空头腿名义额的日频计息)。**这是上界**: A 股个股券源稀缺, 且本库**无券源表**。
2. **样本内 (§8.1)**: 时间样本外已于 §7.13 用掉 ⇒ 本节**只能**得样本内结论。
3. **不做参数扫描 (§5)**: 只跑**一组**预登记参数; 任何额外的 lookback/z 档位都会计入 `n_trials`。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from hiagent_config import DB_PATH  # noqa: E402
import duckdb  # noqa: E402

TRAIN = ("2021-10-01", "2023-09-30")
TEST = ("2023-10-01", "2026-09-18")
MIN_AMT = 1e8          # 日成交额中位数下限
TOP_PAIRS = 100

con = duckdb.connect(str(DB_PATH), read_only=True)

# ① 宇宙: 主板 + 形成窗流动性 + 两窗都有数据
uni = con.execute(
    """
    WITH mb AS (SELECT DISTINCT thscode FROM dim_symbol
                WHERE substr(thscode,1,2) IN ('60','00')),
    amt AS (SELECT thscode, median(amount) AS m FROM raw_kline_daily
            WHERE date BETWEEN ? AND ? GROUP BY 1),
    tr AS (SELECT thscode, count(*) AS n FROM raw_kline_daily
           WHERE date BETWEEN ? AND ? GROUP BY 1),
    te AS (SELECT thscode, count(*) AS n FROM raw_kline_daily
           WHERE date BETWEEN ? AND ? GROUP BY 1)
    SELECT a.thscode FROM mb JOIN amt a USING(thscode)
         JOIN tr T USING(thscode) JOIN te E USING(thscode)
    WHERE a.m >= ? AND T.n >= 400 AND E.n >= 600
    ORDER BY a.thscode
    """,
    [TRAIN[0], TRAIN[1], TRAIN[0], TRAIN[1], TEST[0], TEST[1], MIN_AMT],
).fetchdf()["thscode"].tolist()
print(f"① 宇宙: 主板 + 形成窗日成交额中位 ≥ ¥{MIN_AMT/1e8:.0f}亿 + 两窗齐备 ⇒ **{len(uni)}** 只")

px = con.execute(
    "SELECT thscode, date, close FROM raw_kline_daily "
    "WHERE thscode IN (SELECT unnest(?)) AND date BETWEEN ? AND ? ORDER BY thscode, date",
    [uni, TRAIN[0], TRAIN[1]],
).fetchdf()
con.close()

# ② 形成窗: 日对数收益的宽表
# ⚠️ 这里第一版写的是 `dropna(axis=1, how="any")` —— 1151 只票**不可能天天都有 lr**
# (停牌/缺失) ⇒ 宽表被清成 **0 列**, 而脚本继续往下跑, 崩在 quantile 上。
# ≤ 本册 §0: **fail-fast 要用在自己的脚本上**。改成覆盖率过滤 + **成对完整**相关。
px["lr"] = np.log(px["close"]).groupby(px["thscode"]).diff()
w = px.pivot(index="date", columns="thscode", values="lr")
w = w.loc[:, w.notna().mean() >= 0.95]
assert w.shape[1] >= 100, f"覆盖率 ≥95% 的票只有 {w.shape[1]} 只 —— 上限不对, 别再往下跑"
print(f"② 形成窗宽表: {w.shape[0]} 日 × {w.shape[1]} 票 (覆盖率 ≥95%; 相关按**成对完整**算)")

C = w.corr(min_periods=int(0.8 * len(w))).to_numpy()
codes = list(w.columns)
iu = np.triu_indices(len(codes), k=1)
tri = [t for t in zip(iu[0], iu[1], C[iu]) if np.isfinite(t[2])]
assert len(tri) > 1000, f"有效对数只有 {len(tri)} —— 相关矩阵有问题"
tri = sorted(tri, key=lambda t: -t[2])
print(f"   候选对数 {len(tri)}; 相关系数 p50={np.median([t[2] for t in tri]):.3f} "
      f"p99={np.quantile([t[2] for t in tri],0.99):.3f} max={tri[0][2]:.3f}")

# ③ 不重叠地取前 K 对
used: set[int] = set()
pairs = []
for i, j, c in tri:
    if i in used or j in used:
        continue
    used.add(i); used.add(j)
    pairs.append((codes[i], codes[j], float(c)))
    if len(pairs) >= TOP_PAIRS:
        break
print(f"③ 取不重叠前 {len(pairs)} 对 (用到 {len(used)} 只票); "
      f"相关系数区间 [{pairs[-1][2]:.3f}, {pairs[0][2]:.3f}]")

out = REPO / "tools" / "pairs" / "pairs_formed.csv"
pd.DataFrame(pairs, columns=["a", "b", "corr"]).to_csv(out, index=False)
print(f"   → 落盘 {out.relative_to(REPO)}")

# ④ 顺手看一眼: 这些对在**测试窗**的相关还成立吗 (只看形态, 不下结论)
con = duckdb.connect(str(DB_PATH), read_only=True)
px2 = con.execute(
    "SELECT thscode, date, close FROM raw_kline_daily "
    "WHERE thscode IN (SELECT unnest(?)) AND date BETWEEN ? AND ? ORDER BY thscode, date",
    [sorted(used_codes := {c for p in pairs for c in p[:2]}), TEST[0], TEST[1]],
).fetchdf()
con.close()
px2["lr"] = np.log(px2["close"]).groupby(px2["thscode"]).diff()
w2 = px2.pivot(index="date", columns="thscode", values="lr")
tc = [float(w2[a].corr(w2[b])) for a, b, _ in pairs]
print(f"④ 同一批对在**测试窗**的相关: p50={np.median(tc):.3f} "
      f"p10={np.quantile(tc,0.10):.3f} 仍 ≥0.5 的比例={np.mean(np.array(tc)>=0.5):.1%}")
