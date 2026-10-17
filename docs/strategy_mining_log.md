# 策略潜力挖掘 —— 评估协议与已判定方向

> 按 CLAUDE.md §7 撰写: **只写"怎么复现"和"哪些方向已被判定", 不记任何数字。**
> 带数字的运行记录留在 gitignored 的 `results/` 与本地工作日志里。
>
> 本文件的存在理由: 这份挖掘跑了很多轮, 判定散落在临时目录里。临时目录会被清掉,
> 而"这个方向已经试过了、结论是什么、用什么尺子量的"恰恰是最不该丢的东西 ——
> 本仓库已经因为丢掉这件事, 把同一个失效方向重新当成机会评估过两次。

---

## 1. 评估窗口(真实 DB 覆盖 `v_daily` 2016-09-02 .. 2026-09-30)

| 代号 | 窗口 | 用途 |
|---|---|---|
| W2 | `2024-10-08 .. 2026-09-30` | 报告窗口(近 2 年) |
| W1 | `2025-09-19 .. 2026-09-19` | chase_up 的历史单窗选优窗口 |
| IND | `2022-10-03 .. 2024-09-30` | 独立期, **从未参与任何迭代** |
| IS1 | `2021-10-01 .. 2022-09-30` | 独立期, 同上 |
| IS2 | `2023-10-01 .. 2024-09-30` | 同上 |

**窗口起点必须落在交易日。** 非交易日作为 `asof_date` 曾让 `chase_up` 的 PIT universe
静默变空, 回测随即静默产出 0 笔交易(已修, 见 commit `0162de5`)。

**滚动口径**: `python3 -m short_reversal.walkforward --preset A --preset B
--start 2024-09-30 --end 2026-09-30 --window-months 2`。这是**窗口稳定性**分析,
不是 WFV 择优 —— 没有任何参数逐窗拟合, 所以它回答"优势是否持续", 不回答样本外有效性。

## 2. 一条必须先问的问题: **这个结论是用什么尺子量的**

本次挖掘里, 每一次"最优秀易主"的起点都是发现**尺子本身出过问题**, 而每一次
误判的形态都一样: 一把对某个维度不敏感的尺子, 把一个尚未开采的维度写成了"已证伪"。

| 尺子 | 对什么不敏感 | 后果 |
|---|---|---|
| **逐笔 E[R]**(`tail_objective`) | 分散化 —— 加仓让每笔变小、期望不变, 组合波动与回撤下降 | `short_reversal` 与 `uptrend_pullback` 的 `max_positions>1` 都被误判为死路 |
| **失效的容量闸门** | 实际并发持仓数 | `short_reversal` 的多仓判决是在"声明 N 个实开 24 个"时做出的(见 `abe7dc7`) |
| **单窗口 CAGR** | 路径依赖 —— 全 all-in 时, 起止日挪几天就能翻转结论 | `chase_up` 的"当前最优"在一个窗口第一、另两个窗口为负 |
| **Phase-2 的权益曲线** | 量纲 —— 复利曲线 + 按逐笔固定规模算的累计 delta | 会产出**负权益**(已加 fail-fast, 见 `5195402`) |

⇒ 复核一条旧结论时, 要复核的是**判决本身**, 不只是重新算一遍数字。

## 3. 已判定的方向

以下是本次挖掘(以及仓库既有记录)中被判定过的方向。**"变差"不等于"永远别试"** ——
它等于"当前这把尺子下更差", 换尺子要重新走一遍。

### 3.1 已判定为**更好**的改动

| 方向 | 证据 | 落点 |
|---|---|---|
| 提高 `max_positions`(N=2 / N=4) | 三个独立窗口 + 9~12 个滚动窗口 | `v58_mp_2`(Sharpe 峰) / `v58_mp_4`(Calmar 峰) |
| 把满仓成交顺序显式化 | 契约修复; 两种顺序实测互有胜负 | `fill_order` 参数, 默认不变 |

### 3.2 已判定为**更差 / 不稳健**的改动

| 方向 | 形状 | 说明 |
|---|---|---|
| 在 `uptrend_pullback` 上按逐笔 E[R] 判 N>1 | 判据错 | 换组合口径后 N>1 更好(仍救不活该族) |
| `short_reversal` 加 TP 宽度 / 放宽止损 | 单调劣化 | 极紧止损(0.05%)是优势本身, 不是历史遗留 |
| `short_reversal` 收紧趋势斜率阈值 | 三档都更差 | 在 N=1/2/4 上一致 |
| 满仓按 MA20 斜率(conviction)排序 | 两窗口方向相反 | IND 更好、W2 更差 |
| `v63/v64` 集成 | W2 亮眼但跨窗口散掉 | 原"WFV-failed"判定碰巧正确、理由错误 |
| cycle 按融合分降序取信号 | 劣于随机(两窗口) | 默认已登记为"已知劣于随机" |
| chase_up 全部 22 个 preset | 三窗口无一全正 | 见 §4 |

### 3.3 数据缺口(不是代码缺口)

DB 只有 14 张表, 全是价格/成交量/复权/公司行动/代码表; `dim_symbol` 与 `v_symbol`
只有 thscode/name/exchange/asset_type —— **没有基本面, 没有行业**。
所以"更换信号源(引入基本面/事件维度)"这条建议目前**做不了**, 不是没写。

## 4. 四型现状(按风险调整口径)

| 策略类型 | 现状 |
|---|---|
| `short_reversal` | 唯一可用的一型。当前最优在 `v58_mp_2` / `v58_mp_4` 之间依口径而定 |
| `uptrend_pullback` | 只在近 2 年为正; 两个独立期 N=1..4 **全部为负** |
| `chase_up` | 三窗口无一 preset 全正; 声明最优在任何跨窗口口径下都不成立 |
| `cycle_price_action` | 补齐跨股容量层前不产生组合收益; 补齐后各 N 全负 |

## 5. 复现入口

```bash
# 单 preset 三窗口
python3 -m short_reversal.main --preset v58_mp_2 --start 2024-10-08 --end 2026-09-29 --out /tmp/x.json

# 运行时注入候选(不写 repo)
python3 -c "
from short_reversal import presets as P
P.PRESETS['tmp'] = {**P.PRESETS['v58_mp_2'], 'tp_pct': 0.10}
from short_reversal.engine import run_backtest_v3
print(run_backtest_v3('tmp', '2024-10-08', '2026-09-29', __import__('pathlib').Path(__import__('hiagent_config').DB_PATH)))
"

# 滚动窗口稳定性
python3 -m short_reversal.walkforward --preset v58_mp_2 --preset v50_slope \
    --start 2024-09-30 --end 2026-09-30 --window-months 2
```

`n_trials` 会计按 §5 逐轮累加在 preset 的 `n_comparisons` 字段上;
**新增一个候选 preset 时必须同时加上本轮的试验数。**

---

## 6. 已登记但**未修**的事项 (按 CLAUDE.md §7: 只写"怎么复现", 数字在 commit log 里)

这一节的存在理由与本文档开头相同: **不记下来, 同一个坑会被重新踩。**
下面每一条都是"已知有问题、但改动属结果变更/口径选择, 故只登记不擅自动"。

### 6.1 `tests/golden/chase_v{5,8..14}_baseline.json` 已陈旧 (§6 待重生成)

**症状**: `tests/test_chase_up_no_lookahead.py` 里 8 条 `*_trades_csv_matches_golden_baseline`
恒红。

**已查明的结构** (复现见下): 漂移来自**两个可分离的来源**, 不要当成一件事:

| 环节 | 来源 | 判定 |
|---|---|---|
| baseline 锁定的笔数 → 用**当前引擎**跑 **V7 前配置**的笔数 | **引擎漂移** (V6 intraday tiebreak / V3a 双价格解耦) | **未验证** |
| 上述 → 用**当前配置**跑当前引擎的笔数 | **配置漂移** (V7: `equal`/`max_positions=2` → `all_in`/`max_positions=1`) | 可归因 |

⇒ **第二段可以归因, 第一段只能"有记录可循"而未被验证。** 所以在第一段被验证之前
**不得重生成 baseline** —— 重生成会把一段未验证的漂移**锁成金标准**, 把一个真问题
变成永久绿。这正是本文档开头说的"把失效方向重新当成机会评估过两次"的近亲。

**另有一个断开的过程指针**: baseline 的 `v7_change_note` 指向
`docs/claudemd_preset_audit_2026_09_22.md` 里的 "§2 re-baseline plan" ——
**该文件已不在仓库中** (README 记明"历史审计报告已从 docs/ 移除")。
⇒ 规定动作只以**指向已删除文档的引用**形式存在, 无人能照做。

**复现** (两段各自跑一次即可分离):
```python
from chase_up.presets import get_preset
from chase_up.backtest import run_backtest
from chase_up.data import load_panel
from chase_up.signals import compute_indicators
from chase_up.universe import load_universe
from hiagent_config import DB_PATH

W0, W1 = "2025-09-19", "2026-09-19"          # 取该 baseline 自己的 window
panel = compute_indicators(load_panel(DB_PATH, W0, W1,
                          universe=set(load_universe("mainboard_only", DB_PATH))))

for label, ov in [("现配置", {}),
                  ("V7 前配置", {"position_sizing": "equal", "max_positions": 2})]:
    p = dict(get_preset("chase_v5_pos2_equal_atr_tp6_sl15_mh10")); p.update(ov)
    print(label, run_backtest(p, W0, W1, DB_PATH, panel_ind=panel)["metrics"]["trades"])
```
**验证后再谈重生成** —— 且重生成属结果变更, 须在 PR 里逐条说明漂移。

### 6.2 §4 ATR 滑点: **机制已接好, 但全部 81 个 preset 都把它关掉了**

**§4 原文**: 「Execution slippage MUST be modeled dynamically as a function of the asset's
current ATR (Average True Range) and the order's participation rate. **Do not use flat-rate
slippage** (e.g. 1 tick).」

**现状** (可直接复现, 见下): `chase_up` 22 / `uptrend_pullback` 4 / `short_reversal` 55
个 preset **没有一个**声明 `atr_slip_scale` 或 `slippage`; 引擎调用点默认 `0.0`
⇒ `core/dual_price.atr_slippage` 恒返回 0 ⇒ **实际是"零 flat rate"**,
而 §4 明令禁止 flat rate。

**注意这里两个"默认"是相反的**: `core/dual_price.atr_slippage(..., scale: float = 1.0)`
的**函数默认是 1.0 (开)**; 而 `chase_up/backtrader_engine.py` / `uptrend_pullback/backtrader_engine.py`
的调用点默认 `0.0` (关), 注释自陈理由是「Defaults preserve pre-R15 behavior ...
**0.0 slippage**」。⇒ 关掉它是为了**向前兼容**, 不是因为它是对的。

**为什么这条**没有**像 §4 跳空成交那样直接修** (那条 `57b751e` 直接修了):
跳空成交那条 §4 给了**唯一的正确取值** (「fills at the open, never at the stop price」);
这一条 §4 只规定了**形式** (ATR × participation), 没规定**系数**。而实测把系数从 0
开到函数默认的 1.0, 效果**不单调**:

| | W2 (报告窗) | IND (独立期) |
|---|---|---|
| CAGR 变化 | 变**差** | 变**好** |
| 笔数变化 | **变多** | **变多** |

⇒ 既不是"一致的收紧", 也不是"§0 悲观默认"(§0 要求假设最坏情形, 而这里有一个窗口变好)。
所以**改它属结果变更/建模取值选择** ⇒ 按长期授权「登记, 不擅自改」。

**要解开它需要的是"一个系数从哪来"的决策**, 不是代码改动。三条可选路径:
(a) 由参与率与冲击成本的**外生标定**推出 (需要外部数据, 本库没有);
(b) 取一个**预先声明**的保守常数, 并在 preset 里显式写出 (不再靠引擎默认);
(c) 保持 0, 但在文档与报告里明确标注「本回测**不含**执行滑点, §4 未落实」。
**在选定之前, 任何引用这几个引擎 CAGR 的结论都应附带 (c) 的标注。**

**并且还有一个独立的结构缺口: 滑点只作用于 entry。** 出场侧
(止损 / 止盈 / 时间退出的成交价) **完全未计冲击成本** ——
`chase_up/portfolio.py` 里所有 `slip` 都在 entry 块内 (约 515–557 行);
`uptrend_pullback/portfolio.py` 同构。§4 说的是 "price impact between **signal trigger
and fill**", 对买入腿与卖出腿同样成立。
⇒ **"对称的执行模型"目前不存在**: 买入腿付冲击、卖出腿不付。
所以 §6.2 表格里那个"开了滑点后某些窗口反而变好"的现象**部分来自这个不对称**
(成本只加在一侧, 而止损/止盈**价位**却按被抬高/压低的 entry 重算, 两侧效应相加不单调)。
⇒ 即便定下了系数, 也**还需决定出场侧是否同样计费**; 这两件事要一起定。

**已修的对偶项 (不要混淆)**: 空头 entry 的**符号**曾写反 (把执行成本记成执行收益),
已于 commit `dd9425e` 修正 —— 那条属契约违反且**零结果漂移** (分支不可达), 故直接修。
本条 (系数取值 + 出场侧是否计费) 才是需要决策的部分。

**复现** (读 preset 的声明; 以及开/关对比):
```python
from chase_up.presets import get_preset, PRESETS
from uptrend_pullback.presets import get_preset as ug, PRESETS as UP
import short_reversal.presets as SR

# (1) 现状: 81 个 preset 全都不声明 atr_slip_scale / slippage
print({k: (get_preset(k).get("atr_slip_scale"), get_preset(k).get("slippage"))
       for k in list(PRESETS)[:3]})

# (2) 开/关对比 (任一引擎的任一提案; 这里以当前最优为例)
from pathlib import Path
from hiagent_config import DB_PATH
from uptrend_pullback.backtrader_engine import run_backtrader_backtest
for sc in (0.0, 1.0):
    p = dict(ug("v33_long_reverse_v22")); p["atr_slip_scale"] = sc
    m = run_backtrader_backtest(p, "2024-10-08", "2026-09-30", Path(DB_PATH),
                                verify=False)["metrics"]
    print(sc, m["trades"], m["cagr"])
```

### 6.3 `short_reversal` 的亏损**追溯到信号本身**, 不是执行层 (§5 归因)

**要回答的问题**: 引擎给出的大幅负收益, 是"信号有 edge 但被执行层吃掉", 还是
"信号本身没有方向性"? 两者对应完全不同的后续动作 (前者可工程化, 后者只能弃)。

**做法** (不重跑待验证的策略, 直接用引擎**自己的成交**):
1. 跑一次 preset 拿到全部成交 (`thscode` / `entry_date` / `exit_date` /
   `entry_price` / `exit_price` / `net_return`) ⇒ 落盘, 后续分析不必再跑回测;
2. **固定持有期**前向收益: 从建仓日的 `raw_open` 到其后第 h 个交易日的 `raw_close`,
   做空取其相反数。**不要用"持有到引擎出场日"** —— 出场日由止损/止盈决定,
   那样等于把信号检验条件在引擎的出场择时上 (本轮我先写成那样, 已改);
   该票当日无 bar (停牌) 的样本**跳过, 不伪造**;
3. 三段分解: `raw_signal` vs `engine 价差 (引擎自己的进出价)` vs
   `engine net_return (含成本/融券)` ⇒ 分别读出**信号方向** / **止损止盈的择时效应** /
   **成本+融券**。

**结论 (已加市场对照 —— 见下"更正")**: 在该样本上
* 空头前向收益在 **1 / 2 / 3 / 5 / 10 日全部为负** (中位数在 3–5 日接近 0, 均值为负),
  胜率在 50% 上下;
* 止损/止盈的**择时**相对"持有到期"是**正的** (它确实在帮忙);
* **成本 + 融券**把它吃掉, 净额大致回到"持有到期"的水平。

> ### ⚠️ 更正 (同一轮稍后, 加市场对照后): 上面"信号方向性为负"的说法**过头了**
> 上面只看了**原始**前向收益, **没有剔除市场**. 而该实测期内市场是**上涨**的
> (空头市场对照 1 日 −0.63%) ⇒ 空头原始收益为负**大部分只是 beta**。
>
> 加对照后 (超额 = 原始 − 市场, 空头视角):
>
> | h | 原始(空) | 市场(空) | **超额** | t |
> |---|---|---|---|---|
> | 1 | 负 | 负 | 约 −0.11% | **−0.85** |
> | 3 | 负 | 负 | 约 +0.10% | **+0.55** |
> | 5 | 负 | 负 | 约 +0.01% | **+0.04** |
>
> ⇒ 正确表述是: **该信号没有可测的 alpha (|t| ≤ 0.85), 而不是"方向性为负"**。
> 二者都指向"不可用", **但理由不同, 而理由决定下一步**:
> "方向错了"会让人去找反向信号; "零 alpha"说明**任何方向都收不回成本**
> (成本 ≈ 0.26%/笔), 换方向没有意义。
>
> **教训 (与本文档 §2 同一条)**: 一个没有对着市场比较过的前向收益, **不是
> "信号有没有方向性"的证据** —— 它主要是 beta。本轮我先按没有对照的口径写下了结论,
> 随后自己补上对照并更正。**任何前向收益结论都必须与同构造的市场对照一起给出。**
>
> 市场对照的构造 (必须与信号**同构造**, 否则对照本身有偏): 对每个 (code, date) 与
> 持有期 h 取 `LEAD(close, h)/open − 1` (即"date 开盘买入、持有 h 日后收盘卖出"),
> 再按 date 取**主板等权平均**。这样信号收益与对照收益的起止点、买卖价完全一致。

⇒ **亏损起点在信号层 (零 alpha), 不在执行层。** 这与 §4 的 `short_reversal` 现状一致,
也与 §3.2「极紧止损是优势本身」不矛盾 —— 止损在帮忙, 但帮不回一个零 alpha 的信号。

**注意不要与旧结论混为一谈**: 早先的独立研究把**通用 A+F+C 三重条件**的前向收益
判为"有小的做空方向性"。本条量的是 **某个 preset 在过滤/容量/宇宙之后的实际建仓**,
**不是同一个对象** —— 两者不可互换 (这正是本文档 §2「先问这个结论是用什么尺子量的」
想防的事)。

**复现**: 见本节步骤 1–3; 步骤 2 的日历推进与停牌跳过是唯一容易出错的地方 ——
本轮实现里出现过两次**键形状不匹配导致静默返回空样本** (DuckDB `fetchdf()` 把 DATE
转成 `Timestamp`; 以及 `(code,date)` 元组去查 dict-of-dicts)。**测量返回空样本时必须
先查键, 绝不能当成"没有数据"写进结论。**

#### 6.3.1 未成交的信号有没有 edge? —— **没有。容量不是瓶颈** (同一轮关闭)

**动机**: 6.3 只量了**引擎实际成交**的 686 笔。一个自然反驳是"信号可能有效, 只是被
容量/过滤挡掉了"。本轮把这条路走完。

**做法** (不改仓库文件): 引擎在 `replay_strategy_v3.py` 每根 bar 对每个 feed 判
`_all_conditions`, 而**容量闸门在之后的 `_fill_pending_entries` 才生效**
⇒ monkeypatch `_all_conditions` 即可拿到**全部触发**, 再对全部触发算固定持有期前向收益。

⚠️ **必须先写对建仓时点**: 引擎在 **T+1 开盘**建仓 (T = 信号日)。若从**信号日开盘**
起算持有, 就把信号自己定义在上面那根 K 线的涨幅 (preset 的 `pct_chg` 条件) 也算进去,
会得到巨大且**虚假**的负值 —— **这是测量里的 §1 前视, 本轮我先犯了一次**。
自检: 全部成交都应能被 "信号日 → T+1" 解释 (本轮 686/686 通过)。

**结论** (样本 = 请求窗 `2018-01-01..2020-12-31`, 实测期见 6.3; **不要把结论外推到别的窗口**):
* **全部 908 个触发**的空头原始前向收益在 1/3/5 日**同样全部为负**, 且未被成交的那批
  **并不更好** (1 日甚至更差);
* 但按 §6.3 的**更正**, 需看**超额 (剔除市场)** —— 对照之下这个"全为负"主要是 beta;
  正确表述是**零 alpha**, 不是方向性为负;
* 引擎吃下了 **686/908 = 75.6%** 的触发 ⇒ **容量不是瓶颈**;
* ⇒ **"容量/过滤扔掉了真 edge" 被否证** —— 本来就没有 edge 可扔
  (注意: 这一条**不依赖**上面的 beta 更正 —— 无论用原始还是超额口径,
  未被成交的那批都不比被成交的好。容量结论因此是稳的)。

**与 6.3 的旧悬空问题合并后的最终表述**:
`short_reversal` 这一族在**信号层**就没有前向方向性, 与它叠了几层过滤无关。
早先独立研究量的是**通用 A+F+C 三重条件**; 本 preset 另有
`d_mode=converge_strict` / `below_ratio_60` / `close_ma60_buffer` 等附加条件,
**差异应归因于那些附加条件或宇宙/窗口, 而不是容量** —— 容量这一项已实测排除。

#### 6.3.2 当前最优 `v33_long_reverse_v22` 的**镜像信号**: 同样没有可测超额

**为什么必须量它**: `select_entries_v33_long_mirror` 的 docstring 自陈是
**short_reversal v33 的严格镜像** (A/B/C/D/E 五条件逐条对偶)。既然空头侧实测
**超额 ≈ 0** (6.3), 镜像侧就不能只靠"跑赢等权 +4pp"这类**未剔除 beta** 的说法。

**做法**: 直接调 `select_entries_v33_long_mirror` 拿**全部候选**
(它本身就是完整信号集, 不必 monkeypatch), 再用 6.3 的**同构造市场对照**算超额。

**结果** (两窗口, 候选量远大于引擎实取的笔数 —— 这里 `max_positions=1`, 选择**是**紧的):
| 窗口 | h=1 超额 (t) | h=3 超额 (t) | h=5 超额 (t) |
|---|---|---|---|
| IND | 正, **t≈+1.7** | ≈0, t≈−0.1 | **负, t≈−2.1** |
| W2 | 正, **t≈+1.4** | ≈0, t≈+0.3 | ≈0, t≈+0.2 |

**读法**:
* **1 日超额在两个窗口同号为正, 但 t 都在 1.4–1.7 —— 不到 2** ⇒ 弱的短周期动量迹象,
  **不足以支持结论**; 且该 preset 的平均持有期在**日级中段**, 不是 1 日;
* **在第 5 日, IND 上超额显著为负 (t≈−2.1)**, W2 上 ≈0 ⇒ **持有期稍长就消失甚至反向**;
* ⇒ **与既有的 §5 归因一致** (风格调整后残差 ≈ 0): 该 preset 的正收益是 **beta**,
  不是选股 alpha。本轮用**独立方法** (固定持有期 + 同构造市场对照) 复核了同一结论。

**⇒ 对四型判定的影响**: `uptrend_pullback` 的"当前最优"此前记作
**"样本量不足以判定"**; 本节的独立证据把它推向 **"无 alpha"** ——
但仍需注意二者的区别: 前者是"证据不足", 后者是"证据指向零"。
按 §0 的口径, **两者都不构成可用策略。**

**不要过度解读**: 2677 (IND) 与 7595 (W2) 量级的候选集里取极少数 (max_positions=1),
**取哪一笔**由 `score = mom120` 决定; 本节量的是**候选集平均**, 不是"择优后的子集"。
择优能否改变结论属另一个问题 —— 而 §4/§3.2 已记录排序类改动被证伪。

### 6.4 其余已登记项

| 项 | 说明 |
|---|---|
| `short_reversal` 权益曲线**起点漂移** | 请求窗起点与实测期起点可差 1.13 年; 四个机制假设已被实验否证, **机制未解**。终点侧由 `PANEL_POST_BUFFER_DAYS=60` 解释 |
| `_approx_sharpe` 的**无权平均** | 一笔残仓与一笔满仓同等计入; 已披露加权版本, 未改 |
| `TRADING_DAYS` **243 vs 252** | `chase_up`/`uptrend_pullback` 用 243, `cycle_price_action` 用 252 |
| `sharpe` **口径不统一** | `short_reversal` 是逐笔口径, 其余三个是日权益口径; **不可跨族比较**。已披露 `sharpe_equity_basis` |
| ATR 滑点值 | 见 **§6.2** (单独成节 —— 它是 §4 明令项, 且效果不单调) |
| `presets.py` 内的历史 CAGR 注释 | 成片的 §7 违规 (代码注释里嵌历史指标) |
| Layer 5 之外的 `test_backtest_data_integrity.py` | 见 6.1; 该文件的 Layer 1/Layer 5 已于 2026-10-17 修真 |
