# short_reversal preset 搜索:评估协议、工具与机制不变量

> **本文按 CLAUDE.md §7 撰写:只写「怎么复现」和「要检验什么不变量」,不含任何历史指标。**
> CAGR / Sharpe / 胜率 / 收益 / 行数(max_dd、final_capital、逐笔 trade 数等)一律不入此文;
> 带数字的运行记录留在 gitignored 的产物里(路径见 §3)。
>
> **先例**:本文照 `docs/uptrend_pullback_preset_search.md` 的结构撰写——那是一份 §5 合规的
> preset 搜索协议文档,证明「发现进 commit log,docs 只留复现方法与已证伪方向」是本仓库的既定做法。
> 一个只在 gitignored 的 spec 尾注里记录过的选型,对仓库等于不存在:下一个人无法知道哪些配置被试过、
> 哪些方法已被证伪,于是必然重犯。

---

## 1. 为什么要这份文档

对 `short_reversal` 做 ensemble 选型(`v63_ensemble` / `v64_ensemble_3leg` / `v79_ens44`)时,
仓库内的选型材料**互相矛盾**,且**没有任何一条能被当前代码复现**:

- 三条候选各自的腿(`v50_slope` / `v44_ratio02_buf07` / `v45_ratio01_buf10` / `v50_slope_strict`)
  **全部**是在价格域修复(见 §4)之前调参的,其历史业绩数字在新语义下不成立;
- `presets.py` 自己的注释判定 `v63_ensemble` 的 edge「仅存在于它被选出的那个时段」,
  并留下一条必须遵守的警示:**2024-2026 基准窗口易过拟合**;
- preset 库中存在**行为完全重复**的条目(`v44_ratio02_buf07` 与 `v81_adj` 在当前默认
  `signal_price_domain="adj"` 下是同一个策略,见 §4 与 §5 M1)。

因此除工具本身之外,还需要把「怎么复现一次评估」和「哪些改动方向已被证伪」固化下来,
避免后人用错误的尺子重选一遍。

## 2. 评估协议(CLAUDE.md §5 合规)

| 项 | 做法 |
|---|---|
| 对比窗口 | `2024-01-02 .. 2026-10-16`(冻结;种子、`min_bars=150` 一并冻结) |
| 复核门禁窗口 | `2017-06-01 .. 2023-12-29`——**跨窗口一致性复核**,不是样本外(见下方「为什么不是样本外」)。起点**不得**早于 `2017-06-01`(理由见 §4) |
| 候选 | 决策候选 3 个:`v63_ensemble` / `v64_ensemble_3leg` / `v79_ens44`;另加**参照候选** `v81_adj` |
| 口径 | CAGR / max_dd / Calmar / **逐日净值 Sharpe**(**不用** `short_reversal/engine.py` 的 `_approx_sharpe`——那是按「每笔 PnL × √250」的粗略年化,不是日净值 Sharpe) |
| 统计校正 | DSR(Bailey & López de Prado)+ Bonferroni,统一用 `dna_stats.deflated` |
| `n_trials` 记账 | `RESERVED(3) + len(PRESETS)(75) + widest_declared_sweep(41)`;**不得**只用各 preset 自报的 `n_comparisons` |
| 归因 | 每候选报告相对**等权基准**(同 universe 买持 basket)的超额 CAGR;候选 ensemble 的腿有重叠,R6 要求显式列出 |
| 产物 | 落盘到 gitignored 的 `/tmp/hiagent_live_runs/`;文档只引用路径与窗口,不复制数字 |

**纪律**:不做网格搜索取最高 Sharpe;一次只评估一个假设;**参照候选不是第四个决策候选**——
`v44_ratio02_buf07` 是全部三个 ensemble 共同的一条腿,不设参照点就是拿三个共享同一缺陷的构造互比。

**`n_trials` 为什么是「下界」而非某 preset 的自报值**:候选是从一个规模为 `len(PRESETS)` 的
历史搜索空间里抽出来的,只统计每个 preset 自己那条轴的扫描(`n_comparisons`,实测在 11–45 之间且互不一致)
会隐去「先搜出整库才挑出这几个」这一层。故取 `len(PRESETS)` 为主导层,再取本次实际跑到的候选里
**最宽**的自报扫描规模(`widest_declared_sweep`),用 `max` 而非 `sum`(三条 ensemble 共享腿,求和会重复计数)。

**为什么 `2017-06-01 .. 2023-12-29` 不是「样本外」(§5)**:这段窗口**参与过**这些腿的选型。
`short_reversal/presets.py` 记录的 v44 消融用的正是 `2017-H2 / 2022-H2 / 2019-H2 / 2021-H1 / 2018-H2`
(全部落在该区间内),并据此给出「2016-2023 mean delta Calmar +0.75(7 windows)」。因此本门禁
**只能**读作**跨窗口一致性复核**(同一批候选在两段窗口上是否给出一致结论),
**不得**描述为 out-of-sample / independent / 样本外。CLAUDE.md §5 要求的
「a holdout window that participated in no iteration」在现有数据下**无法满足**:数据地板是
`2016-10-10`,而在可行区间上这些腿的选型早已用过这些月份。真正意义上的样本外裁决需要有
**从未**被搜索过的数据,本仓库今天没有。

## 3. 工具与复现命令

```bash
# (a) 对比:三个决策候选 + 参照候选,统一窗口。写 <out>/compare.json(gitignored)
python3 -u -m tools.live.compare_ensembles --out /tmp/hiagent_live_runs \
    --start 2024-01-02 --end 2026-10-16

# (b) 跨窗口一致性复核:同批候选跑另一段窗口(不是样本外,见 §2),写 <out>/repro.json(与 compare.json 分开!见下)
python3 -u -m tools.live.reproduce_2016_2023 --out /tmp/hiagent_live_runs

# 契约测试(schema 与口径钉桩,离线,不依赖上面两轮长批)
python3 -m pytest tests/test_compare_ensembles_contract.py -q
```

- **两个脚本必须写不同的文件**。Step 6 用 `&` **并发**启动、共用同一个 `--out` 目录;
  若两者都写 `compare.json`,就是并发写同一文件的竞争,后写的会静默覆盖先写的。
  `compare_ensembles.OUTPUT_NAME` / `reproduce_2016_2023.OUTPUT_NAME` 的**不相等**由契约测试钉住。
- **判定规则**写死在 `repro.json` 的 `verdict` 字段里:仅在 2024-2026 上出色、
  而在 2017-2023 上不显著的候选**不得采纳**。`adopt` 当且仅当至少一个**决策**候选在该复核窗口上显著
  (DSR ≥ 0.95);参照候选不参与判定。
- 两个脚本都**逐候选打印一行并 `flush=True``**——这是数小时无人值守长跑里唯一的进度信号。
  单条候选内部(单腿回测)依然 CPU 满载、无中间输出,这是正常的。

## 4. 机制不变量(每条都可证伪;改动后请重跑验证)

以下方向**均已实测为更差或已被证伪**,若有人重新提出,请先复现再讨论:

| 不变量 | 改动即变差 / 失效 | 复现方式 |
|---|---|---|
| **双价域**:信号用 `adj_close`,执行与 SL/TP 用 `raw_close` | 把 A/B/C 条件与 MA/MACD 混到一个价域 | 见下方「价格域」段 |
| **`require_intraday_reversal`(K)当前不可运行(待改写到单一价域)** | 在 `adj` 域启用 K → K 拿 adj `signal_close` 比 raw high/low/open,恒真(no-op);引擎直接抛错。改用 `raw` **不是**补救——那会让 A 条件变 no-op | 见下方「价格域」段 |
| **`intraday_tiebreak = sl_first`** | 同 bar 内 TP/SL 都破时判 TP | 改 preset 的 tiebreak 后跑 §3(a) |
| **All-In 入场 + `max_volume_participation = 0.10`(IOC)** | 放松参与率上限 → 流动性幻觉 | 覆盖 `max_volume_participation` |
| **子账户 `max_positions = 1`(单发子弹)** | 提高并行持仓数 | 覆盖 `max_positions` |
| **参照候选不可省**:`v44_ratio02_buf07` 是三条 ensemble 共同的腿 | 去掉参照 → 三条共享同一缺陷的构造互比 | 删掉 `v81_adj` 后跑 §3(a),看「最优」只反映对同一条腿的加权差异 |
| **复现窗口起点 ≥ `2017-06-01`** | 取 2016 → **空 universe → `ValueError`**(不再静默 0 笔) | 见下方「空 universe」段 |

**价格域(§3 双价)**:候选的腿在调参时,A/B/C 条件用的是 raw close,而 MA/MACD 用 adj close;
因 raw 系统性低于 adj,`close < ma60` 几乎恒真——**A 条件当时实际是 no-op**。
`v81_adj` 把 A/B/C 切到 adj_close 与 MA 同域。修正后绝对表现下降,
但「无 F 条件优于有 F 条件」这条排序不依赖该 bug。

**同一个价域缺陷也在 K 条件里**(单日在 range 中的位置):K 读 bar 的 **raw** high/low/open,
却拿它们去比 `signal_close`——在 `signal_price_domain='adj'` 下 `signal_close` 是 **adj** 价。
两边不同域,于是 `close_pos = (adj_close − raw_low)/(raw_high − raw_low)` 恒在 0.6 阈值以上、
`close_v > bar.open` 也几乎恒真——**K 永不拒绝,静默退化成 no-op**(实测 000001.SZ
2026-09-01..09-08:close_pos = 13.4 / 28.2 / 15.7 / 26.1 / 16.8 / 24.8)。因此
`require_intraday_reversal=True` 与 `signal_price_domain='adj'` 的组合被引擎**具名抛错**
(§0 fail-fast)。**切到 `signal_price_domain='raw'` 不是补救**——那正是让 A 条件退化
(用 adj MA 比 raw close,`close < ma60` 几乎恒真)的那个 §3 缺陷,等于拿 K 的静默 no-op
去换 A 的静默 no-op。K 必须在**单一价域**上改写(例如改读 adj high/low/open 与 adj
`signal_close` 同域比较,或整条条件走 raw)之后才能启用;在此之前 `require_intraday_reversal=True`
的条目 —— `v61_k` / `v61_kf` —— **无法运行**(见 `short_reversal/presets.py` 对应条目的
UNRUNNABLE 注记)。

**空 universe(§2.9 / F-01 的近亲)**:`raw_kline_daily.min(date)` 是 **2016-10-10**。
`load_universe_asof` 用「上市日 ≤ as-of」做代理,早于该日期的 as-of 返回**空 universe**。
空 universe **不再**是一段静默的 0 笔:`run_backtest_v3` 现在会具名抛 `ValueError`
(`short_reversal/engine.py`,as-of 早于数据地板或 DB 缺该日覆盖)—— 空 universe 下没有一根
bar 被评估,其 0 笔与「市场当天没信号」在输出上不可区分,违反 §0 fail-fast。两个运行脚本
仍在**更外层**带**两条强制守卫**,好在跑任何候选之前就给出可诊断的报错:
(1) 每窗口开跑前断言 universe 非空,否则 `SystemExit` 并打印 as-of 与 DB `min(date)`;
(2) 每候选跑完断言 `trades_count > 0`,否则 `SystemExit` 并打印候选名——
空 universe、`min_bars` 悬崖、F-01/空 universe 守卫拦下这几种「未评估/零成交」必须可区分。

**参考**:`presets.py` 记的稳健性复核里有一项 `2016-H2 (min_bars 不足)`——
那一档因 `min_bars` 门槛而未产出任何交易,门槛的产物而非策略表现,却被算进了当时的均值。
即仓库自己那次「2016-2019 复现」的证据链本身就含此类 artifact,更不能被当作结论引用。

## 5. 已证伪的方法(定性;每条给出复现路径)

| # | 方法 | 复现方式 |
|---|---|---|
| M1 | 把 preset 库条目数当作「搜索空间大小」(库内存在行为完全重复的条目,如 `v44_ratio02_buf07` ≡ `v81_adj`) | 对同一窗口跑两者,比较 trade list 是否逐笔相同(见 `tests/golden/` 的价格域等价性基线) |
| M2 | 在 F-free 基线(`v44_ratio02_buf07`)上加 F 以外的入场条件(G cumret / H amount dry-up / I RSI / K) | 在 v44 基线上叠该条件后跑 §3(a);结论:条件更少时更好 |
| M3 | 用「弱势水平」而非「斜率」定义 downtrend(G 条件) | 叠加 G 后跑 §3(a):测绝对跌幅会把「中段下跌」当入场点 |
| M4 | 按 conviction(最陡斜率)选择当日唯一仓位(`conviction` / `steepest_slope`) | 在 v44 基线上覆盖 `entry_selection` |
| M5 | 放宽 `below_ratio_60` 到 0.5(`v82_ratio05`) | 覆盖 `below_ratio_60` 后跑 §3(a):regime-dependent,由单窗口驱动 |
| M6 | 靠「多腿集成」取得分散化收益(腿高度相关) | 跑 §3(a) 看 `v79_ens44`(两腿同源)vs 单腿 |

## 6. 该族的结构性事实(结论性,无数字)

- 该策略是一个**反向动量 / 超跌反弹**族:在下跌趋势中入场,靠**紧 SL + 宽 TP** 收割右尾。
  因此**胜率天然偏低、退出分布极度偏止损、持仓期极短**,盈亏由少数右尾事件驱动——
  **均值类指标(Sharpe、窗口均值)不是唯一合适判据**,必须与 max_dd / Calmar / 尾部口径并读。
- 该族在**条件更少时更好**:移除 F 有益,新增 G/H/I/K 在两个基线上均有害(§5 M2/M3)。
  入场维度已多次尝试收敛,继续在价格派生的条件上做参数或排序改动,期望收益很低。
- **候选 ensemble 的独立性弱于表面**:`v44_ratio02_buf07` 出现在全部三个决策候选中(R6)。
  因此「三选一」的边际价值有限,选型必须带参照候选才有意义。
- 该族的 headline 收益与**市场 beta** 高度相关,必须按 §2 归因要求对照等权基准,
  不得直接当作选股 alpha。要取得可证实的 alpha,应更换**信号源**,而非继续调参。
- 该族的全部历史业绩数字来自**价格域修复之前**的搜索;在当前语义下应视作失效,
  需按 §3 的两段窗口重新裁决。

## 7. 相关代码与测试

- `tools/live/compare_ensembles.py` —— 三方对比 + 参照候选;日净值 Sharpe、DSR/Bonferroni、
  `honest_n_trials()`、两条强制守卫
- `tools/live/reproduce_2016_2023.py` —— 2017-2023 跨窗口一致性复核门禁,写 `verdict`
- `tests/test_compare_ensembles_contract.py` —— JSON schema、`n_trials` 下界、Sharpe 单源委托、
  窗口切片、两脚本输出文件名不重合
- `dna_stats/deflated.py` —— DSR / Bonferroni / `annualized_sharpe`(Sharpe 单源)
- `short_reversal/engine.py`(`run_backtest_v3`,含 `equity_curve`)、`short_reversal/universe.py`(`load_universe_asof`)
- `tests/golden/` —— 价格域等价性基线(锁定 `v44_ratio02_buf07` ≡ `v81_adj`)
