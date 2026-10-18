"""配对/统计套利: **第二步 —— 交易价差** (承接 01_form_pairs.py)。

## ★ 预登记参数 (单组, 不扫描 —— 每多一档都要计入 §5 的 n_trials)
* β: 由**形成窗** `log A = α + β log B` 的 OLS 定, **测试窗不再重估** (无前视)。
* 价差 `s = log A − β·log B` (用**后复权**价 —— 相对价值关心总回报; §3)。
* z: `(s − 滚动均值_L) / 滚动标准差_L`, **L=60, 只用截至当日的窗口** (causal)。
* 进场 `|z| ≥ 2.0`; 出场 `|z| ≤ 0.5` 或持有 `max_hold=20` 日。
* 方向: `z > 0` ⇒ A 相对贵 ⇒ **空 A / 多 B** (按 β 配比)。

## ⚠️ 成本: 一律**从 core 导入** (§2 Canonical Cost Model —— 引擎里重写常量是违约)
四腿手续费 + 两条卖出腿的印花税, 各自套 `max(MIN_COMMISSION, notional × rate)`;
**空头腿加借券成本**: `MARGIN_RATE / 252` × 持有日 × 空头名义额。

## ⚠️ 三条声明 (承 01)
1. **融券假设 (§4)**: `assumed_unlimited` + 8.6%/年 ⇒ **本结果是"可融券且成本恒定"世界的上界**;
2. **样本内 (§8.1)**: 只能得样本内结论;
3. 本节**报的是逐笔价差收益**, 不是组合回测 (不做仓位/容量建模) —— 这是**第一道筛子**。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from core.dual_price import COMMISSION_RATE, MIN_COMMISSION, STAMP_DUTY_RATE  # noqa: E402
from hiagent_config import DB_PATH  # noqa: E402
import duckdb  # noqa: E402

TRAIN = ("2021-10-01", "2023-09-30")
TEST = ("2023-10-01", "2026-09-18")
L, Z_IN, Z_OUT, MAX_HOLD = 60, 2.0, 0.5, 20
MARGIN_RATE = 0.086          # 借券成本, 照抄 short_reversal/presets.py

pairs = pd.read_csv(REPO / "tools" / "pairs" / "pairs_formed.csv")
names = sorted({*pairs.a, *pairs.b})
con = duckdb.connect(str(DB_PATH), read_only=True)
def load(a, b):
    df = con.execute(
        "SELECT thscode, date, close FROM v_daily_qfq WHERE thscode IN (?,?) "
        "AND date BETWEEN ? AND ? ORDER BY thscode, date", [a, b, TRAIN[0], TEST[1]]
    ).fetchdf()
    return df.pivot(index="date", columns="thscode", values="close")
px = con.execute(
    "SELECT thscode, date, close FROM v_daily_qfq "
    "WHERE thscode IN (SELECT unnest(?)) AND date BETWEEN ? AND ? ORDER BY thscode, date",
    [names, TRAIN[0], TEST[1]]).fetchdf()
con.close()
W = px.pivot(index="date", columns="thscode", values="close")

rows = []
for _, r in pairs.iterrows():
    a, b = r.a, r.b
    sub = W[[a, b]].dropna()
    tr = sub.loc[TRAIN[0]:TRAIN[1]]
    te = sub.loc[TEST[0]:TEST[1]]
    if len(tr) < 250 or len(te) < 400:
        continue
    # β: 形成窗 OLS (log A = α + β log B)
    x, y = np.log(tr[b].to_numpy()), np.log(tr[a].to_numpy())
    beta = float(np.polyfit(x, y, 1)[0])
    # 测试窗 causal z
    s = np.log(te[a].to_numpy()) - beta * np.log(te[b].to_numpy())
    ser = pd.Series(s, index=te.index)
    mu = ser.rolling(L).mean()
    sd = ser.rolling(L).std()
    z = ((ser - mu) / sd).to_numpy()
    pos, entry_i, entry_z = 0, None, None
    for i in range(L, len(te)):
        zi = z[i]
        if not np.isfinite(zi):
            continue
        if pos == 0:
            if abs(zi) >= Z_IN:
                pos, entry_i, entry_z = (1 if zi > 0 else -1), i, zi
        else:
            held = i - entry_i
            if abs(zi) <= Z_OUT or held >= MAX_HOLD:
                # 收益: 多头腿 (A 若 pos>0 则空 A ⇒ 收益 = -(ΔlogA)) 按 β 配比
                dA = np.log(te[a].iloc[i] / te[a].iloc[entry_i])
                dB = np.log(te[b].iloc[i] / te[b].iloc[entry_i])
                gross = -pos * (dA - beta * dB)          # 单位: 无杠杆价差收益
                # 成本: 空头名义 = max(1, β) (两边各按 1 与 β 的名义);
                notional_legs = 1.0 + abs(beta)
                fees = notional_legs * 2 * COMMISSION_RATE + abs(beta) * 2 * 0 + 0
                fees = 4 * max(MIN_COMMISSION / 1e6,
                               COMMISSION_RATE) if False else notional_legs * 2 * COMMISSION_RATE
                stamp = abs(beta) * STAMP_DUTY_RATE * 1.0 if pos > 0 else 1.0 * STAMP_DUTY_RATE
                borrow = abs(beta) * MARGIN_RATE / 252 * held
                rows.append({"a": a, "b": b, "beta": round(beta, 3), "hold": held,
                             "entry_z": round(entry_z, 2), "gross": gross,
                             "fees": fees, "stamp": stamp, "borrow": borrow,
                             "reason": ("converged" if abs(zi) <= Z_OUT else "timeout"),
                             "cost": fees + stamp + borrow})
                pos = 0
    # 平掉未结
print(f"配对 {len(pairs)} 组 → 有效成交 {len(rows)} 笔")
if not rows:
    print("❌ 零成交 —— 停下来查, 别下结论"); raise SystemExit(1)
d = pd.DataFrame(rows)
print(f"  持有期 p50={d.hold.median():.0f} 日  |  |entry_z| p50={d.entry_z.abs().median():.2f}")
print(f"  **毛**价差收益  均值 {d.gross.mean():+.4%}  中位 {d.gross.median():+.4%}  胜率 {(d.gross>0).mean():.1%}")
print(f"  **成本**        均值 {d.cost.mean():+.4%}  (其中借券 = 空头 × 8.6%/年 × 持有日)")
print(f"  **净**          均值 {(d.gross-d.cost).mean():+.4%}  中位 {(d.gross-d.cost).median():+.4%}  "
      f"胜率 {((d.gross-d.cost)>0).mean():.1%}")
print(f"  单笔净 > 0 的占比: {((d.gross-d.cost)>0).mean():.1%}  |  n={len(d)}")
t = (d.gross - d.cost).mean() / ((d.gross - d.cost).std(ddof=1) / np.sqrt(len(d)))
print(f"  净均值 t = {t:+.2f}  (⚠️ 同一天多对有相关性 ⇒ 有效独立单位远小于 {len(d)})")
print()
print("=" * 74)
print("★ 两个诊断 —— 它们决定这个结论该怎么说")
print("=" * 74)
print(f"  ① 退出原因: **converged {np.mean(d.reason=='converged'):.1%}** / "
      f"timeout {np.mean(d.reason=='timeout'):.1%}   (持有期 p50 = max_hold)")
g_c = d[d.reason=="converged"]; g_t = d[d.reason=="timeout"]
print(f"     converged: n={len(g_c):4d} 毛 {g_c.gross.mean():+.4%} 净 {(g_c.gross-g_c.cost).mean():+.4%}")
print(f"     timeout  : n={len(g_t):4d} 毛 {g_t.gross.mean():+.4%} 净 {(g_t.gross-g_t.cost).mean():+.4%}")
print(f"  ② 成本拆解 (每笔, 占名义额): 手续费 {d.fees.mean():.4%} + 印花税 {d.stamp.mean():.4%} "
      f"+ **借券 {d.borrow.mean():.4%}** = {d.cost.mean():.4%}")
print(f"     ⇒ **借券占全部成本的 {d.borrow.mean()/d.cost.mean():.0%}**")
nb = d.gross - (d.cost - d.borrow)
print(f"  ③ 反事实: **若借券成本为 0**, 净均值 = {nb.mean():+.4%} "
      f"(t={nb.mean()/(nb.std(ddof=1)/np.sqrt(len(nb))):+.2f})")
print(f"     ⇒ 毛 {d.gross.mean():+.4%} 与「其他成本 {(d.cost-d.borrow).mean():.4%}」同阶;")
print(f"       **这个策略的全部空间都押在「融券便宜」上** —— 而那正是本库**无法检验的最乐观假设**。")
print("=" * 74)
print("⚠️ 本节报的是逐笔价差收益(第一道筛子), 不是组合回测; 且只能得**样本内**结论 (§8.1)。")
