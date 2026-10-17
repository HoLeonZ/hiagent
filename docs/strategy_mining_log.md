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

### 6.2 其余已登记项

| 项 | 说明 |
|---|---|
| `short_reversal` 权益曲线**起点漂移** | 请求窗起点与实测期起点可差 1.13 年; 四个机制假设已被实验否证, **机制未解**。终点侧由 `PANEL_POST_BUFFER_DAYS=60` 解释 |
| `_approx_sharpe` 的**无权平均** | 一笔残仓与一笔满仓同等计入; 已披露加权版本, 未改 |
| `TRADING_DAYS` **243 vs 252** | `chase_up`/`uptrend_pullback` 用 243, `cycle_price_action` 用 252 |
| `sharpe` **口径不统一** | `short_reversal` 是逐笔口径, 其余三个是日权益口径; **不可跨族比较**。已披露 `sharpe_equity_basis` |
| ATR 滑点值 | `§8#2`, 全部预设仍为 0 |
| `presets.py` 内的历史 CAGR 注释 | 成片的 §7 违规 (代码注释里嵌历史指标) |
| Layer 5 之外的 `test_backtest_data_integrity.py` | 见 6.1; 该文件的 Layer 1/Layer 5 已于 2026-10-17 修真 |
