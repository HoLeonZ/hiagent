"""§10 异质性轴的**收口判据**: [4%+) 那条约 −1%/次 的效应, 该记"关闭"还是"重开预登记"?

## 为什么要再跑一遍 (§7.16 的教训)
§10.8 刚因"两段切分"被判过一次; §7.13/§7.15 的"两个时代"也栽在同一读法上。
⇒ **任何跨时间的幅度结论, 都要先看逐年的形状, 不能只看两段平均。**

## 两个必须分开的频率口径 (预登记里我混了)
* **f_pool** = 事件数 / **全票池**票数 / 年 ⇒ "随便持一只票"碰到几次;
* **f_sel**  = 事件数 / (该档**有事件**的 (票,年) 对数) ⇒ **选中"当年高股息"的票**时碰到几次。
  高股息组合**每年**都会选到当年派高息的票 ⇒ 这是**策略相关**的那个。
⇒ 年化上界要用 f_sel 重算一次, 两个都给。

## 预登记判据 (看数之前)
* **关闭**: 逐年的符号**来回变号** (振荡) ⇒ 与 §7.16 同类, 不可持有;
* **记「未关闭」而非「关闭」**: 逐年**同号**且 |年化(f_sel)| ≥ 1%/年 ⇒ 当时的判定
  ("<1%/年" 或 "非单调") 与真实形状不匹配 ⇒ 应**重开一次预登记**, 而不是当已否。
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
            WHERE e.ex_date BETWEEN '2016-10-01' AND ? AND {PURE}),
evy AS (SELECT ev.thscode, ev.ex_date, ev.D, ev.D/r.close AS yld
        FROM ev JOIN raw_kline_daily r ON r.thscode=ev.thscode AND r.date=ev.d0 WHERE r.close>0),
p AS (SELECT thscode, date, close, LAG(close,1) OVER w AS c1 FROM v_daily_hfq
      WHERE date BETWEEN '2016-09-01' AND ? WINDOW w AS (PARTITION BY thscode ORDER BY date)),
m AS (SELECT date, avg(close/c1-1) AS mkt FROM p GROUP BY date)
SELECT evy.thscode, evy.ex_date, evy.yld, p.close/p.c1-1 - m.mkt AS ex
FROM evy JOIN p ON p.thscode=evy.thscode AND p.date=evy.ex_date JOIN m ON m.date=evy.ex_date
WHERE evy.yld < 1
"""
df = con.execute(SQL, [END, END]).fetchdf().dropna()
hi = df[df.yld >= 0.04].copy()
hi["yr"] = hi.ex_date.astype(str).str[:4]

print("=" * 78)
print(f"① [4%+) 档**逐年** (n={len(hi)} 事件, {hi.ex_date.nunique()} 事件日)")
print("=" * 78)
print(f"{'年':>6} {'事件数':>7} {'事件日':>6} {'事件日超额':>11} {'t':>7}")
signs = []
for y, sub in hi.groupby("yr"):
    g = sub.groupby("ex_date").ex.mean(); e = g.to_numpy()
    if len(e) < 10: print(f"{y:>6} {len(sub):>7} {len(g):>6}   —— 事件日太少"); continue
    t = e.mean() / (e.std(ddof=1) / np.sqrt(len(e)))
    signs.append(np.sign(e.mean()))
    print(f"{y:>6} {len(sub):>7} {len(g):>6} {e.mean():>+10.3%} {t:>+7.2f}")
flips = sum(1 for i in range(1, len(signs)) if signs[i] != signs[i-1])
print(f"  ⇒ 符号变号 {flips} 次 / {len(signs)-1} 次相邻比较 "
      f"⇒ **{'振荡' if flips >= max(2, (len(signs)-1)//3) else '同号为主'}**")

print()
print("=" * 78)
print("② 两个频率口径 → 两个年化上界 (近期 2021-10..2026-09)")
print("=" * 78)
A, B, YRS = "2021-10-01", END, 4.97
rec = hi[(hi.ex_date.astype(str) >= A) & (hi.ex_date.astype(str) <= B)]
g = rec.groupby("ex_date").ex.mean(); eff = g.mean()
n_all = con.execute("SELECT COUNT(DISTINCT thscode) FROM raw_kline_daily WHERE date BETWEEN ? AND ?",
                    [A, B]).fetchone()[0]
n_ev = len(rec)
payer_years = rec.assign(y=rec.ex_date.astype(str).str[:4]).groupby(["thscode", "y"]).ngroups
f_pool = n_ev / n_all / YRS
f_sel = n_ev / payer_years
print(f"  每次事件幅度            = {eff:+.4%}")
print(f"  f_pool (全票池)         = {f_pool:.3f} 次/票/年 ⇒ 年化上界 {eff*f_pool:>+8.4%}/年")
print(f"  f_sel  (选中当年高息票) = {f_sel:.3f} 次/票/年 ⇒ 年化上界 {eff*f_sel:>+8.4%}/年"
      f"   ← **策略相关**")
print(f"  预登记门槛 = 1%/年 ⇒ 用 f_sel 时 {'达到' if abs(eff*f_sel) >= 0.01 else '未达到'}")

print()
print("=" * 78)
print("③ 作为对照: 同一算法用在**中段档** [1%,2%) 上 (若那里也有 1%/年, 说明是普遍现象不是尾部)")
print("=" * 78)
mid = df[(df.yld >= 0.01) & (df.yld < 0.02)]
mr = mid[(mid.ex_date.astype(str) >= A) & (mid.ex_date.astype(str) <= B)]
gm = mr.groupby("ex_date").ex.mean()
py = mr.assign(y=mr.ex_date.astype(str).str[:4]).groupby(["thscode", "y"]).ngroups
print(f"  [1%,2%) 每次事件 {gm.mean():+.4%}, f_sel={len(mr)/py:.3f} ⇒ 年化 {gm.mean()*len(mr)/py:+.4%}/年")
con.close()
