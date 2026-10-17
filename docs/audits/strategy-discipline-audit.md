# hiagent 四策略研发/测试纪律审计 —— `main` 分支

**被审计对象**:`main` @ `94ca15d`,以只读 worktree 固定检出在 `/tmp/hiagent-main`,审计全程读取该快照。**不引用任何其它分支的实现状态。**

审计依据:`CLAUDE.md` §0–§7(绝对确定性)。
审计日期:2026-10-14 ~ 2026-10-15。

---

## 0. 结论摘要

**判定:`main` @ `94ca15d` 不合规(NO-GO)。四个策略包全部违规,无一合规。**

| 项目 | 数值 |
|---|---|
| 分派审计单元 | 26(4 策略 × 5 节 + 6 跨引擎维度) |
| **产出结果的单元** | **26 / 26(0 个空手)** |
| agent 数 / 报错 / 空返回 | 379 / 0 / 0 |
| 原始发现 | 208 |
| 去重后逐条清点(经验证) | **203** |
| 被对抗验证驳回 | 1 |
| 无法验证(验证者全挂) | 0 |
| 严重度 | **BLOCKER 20 · HIGH 63 · MEDIUM 70 · LOW 50** |

> 其中 **80 条**的严重度被验证者修正过(多数为下调),说明验证环节在做实际工作而非盖章。

### 0.1 四包逐包判定

| 策略包 | 判定 | BLOCKER | 违反条款 |
|---|---|---|---|
| `chase_up`(追涨) | **违规** | 6 | §1、§2、§3、§4、§6 |
| `uptrend_pullback`(趋势回调) | **违规** | 1 | §1、§2、§3、§4、§6 |
| `short_reversal`(做空反转) | **违规(四包中最严重)** | 7 | §1、§2、§3、§4、§6 |
| `cycle_price_action`(周期/价格行为) | **违规** | 2 | §1、§2、§3、§4、§6 |

去重后 **11 个 BLOCKER 缺陷族**(完整清单见 §6 报告第 3.1 节):

1. `chase_up` 权益/NAV 双计持仓成本基础与市值(`portfolio.py:619-623`、`:463`)
2. `chase_up` Phase-2 静默在复权域撮合(`backtrader_engine.py:187`)
3. 全库 **ATR 滑点恒为 0**(四引擎,0 个 preset 启用)
4. `short_reversal` 窗口边界从未下发策略(`_panel_loader.py:90`)—— ⚠️ **本条结论已更正,见 §0.4**:边界从未被强制,但**实际不存在窗口外成交**,"窗口前开仓"这一后果**已被实证否定**
5. `short_reversal` 入场费 lock 后**全额退回**(`replay_strategy_v3.py:820`)
6. `short_reversal` 跳空穿越止损仍按 `sl_p` 成交(`:769-770`)
7. `short_reversal` 原始 close 与复权 MA60 混域比较(`:913`/`:927`)
8. `cycle_price_action` 宇宙成员由**窗口之后**的全表成交额决定(`data_feed.py:211`)
9. `cycle_price_action` 出场同时退回成本基础**并**计入全额卖出款(`portfolio.py:300-302`/`:383-385`)
10. **四引擎均无公司行为事件源**(分红不入 Free_Cash、拆股不调仓)
11. `short_reversal` 无任何 golden 基线,唯一相关测试空转

### 0.2 系统性(非零散瑕疵)

四类跨引擎系统性缺陷,而非个别 bug:

- **现金账/NAV 表达式把「持仓成本基础」与「持仓市值」相加** —— 四引擎全中。
- **双价体系半迁移** —— 指标已切复权价,但盯市/NAV 闸门/期末强平/部分条件比较仍在原始域或旧域。
- **ATR 滑点在四引擎「已实现但不可达」** —— 公式存在,出厂配置全为 0,`core.dual_price.atr_slippage` 在生产代码中零调用。
- **测试层守卫大面积空转** —— 详见 §2。

---

## 0.3 ⚠️ `main` 已在审计期间前移(必读)

审计开始时 `main` = `94ca15d`。审计期间**另一会话仍在向 `origin/main` 推送**,审毕时:

```
origin/main = b597d0c   Merge pull request #10 from HoLeonZ/fix/short-reversal-single-source-fees
```

`b597d0c` 含 4 个提交,针对性修复了本轮审计的 4 项发现。**我已在 `b597d0c` 的独立快照上逐条核实这 4 项修复确已落地**:

| 提交 | 修复内容 | 对应本轮发现 |
|---|---|---|
| `c06ead1` | `min_cash_ratio` 默认 `None` → `0.05`(`replay_strategy_v3.py:196`) | 上轮补充发现 S1(见 §4) |
| `244cf99` | `signal_price_domain` 默认 `raw` → `adj`(策略 `:308`、引擎 `:315`) | 本轮 B7 / 上轮 B5 |
| `7337911` | 费用真正从 `core.dual_price` 单源导入(`short_reversal/engine.py:34-39`) | §2 费用单源族 |
| `1e85d8e` | `BORROW_ASSUMPTION.borrow_cost_model` 改为 `annualized_margin_rate` | §4 借券声明矛盾 |

**因此**:本报告以指令要求的 `94ca15d` 为准;上述 4 项在**当前 `origin/main` 上已不成立**。其余发现(尤其 `chase_up` 权益双计、ATR 滑点恒 0、公司行为缺失、窗口边界、`cycle_price_action` 出场双记等)**在 `b597d0c` 上未见对应修复**。

> 对 `b597d0c` 的完整复审计**未执行** —— 若需要,应把 `b597d0c`(或届时更新的 tip)固定为新快照后重跑。

---

## 0.4 ⚠️ 更正记录:一条 BLOCKER 的后果被后续修复证伪

本报告发布后,在按 §8 顺序修复的过程中,以下结论被**实证推翻**,现予更正:

**原结论(BLOCKER 第 4 族 / §3 V7 / §2.3 §1 项)**
> `short_reversal` 窗口边界从未下发策略,**导致窗口前开仓**。

**复核结果(2026-10-15)**

- **"窗口前开仓"为假。** 把 `lookahead_trade_trace.TraceStrategy` 从"生产入场逻辑的分叉副本"改为委托生产实现后,三个窗口不变量用例**全部通过**:
  - `test_pre_window_entry_count_is_zero` ✓
  - `test_pre_window_pnl_contribution_is_zero` ✓
  - `test_no_post_window_entries` ✓
  即生产路径**确实不会**在窗口外入场。
- **原结论为何看起来"证实"了。** 该 harness 是 Round 16 **之前的化石副本**:自建 size 公式、`self.cash -= entry_fee` 单池模型、**不调用 `reserve_for_entry`**、建仓字典只写 3 个键。于是 `locked_margin` 恒为 0,每笔建仓后的下一根 bar 就被融券日费的 fail-fast 打死:
  `ValueError: margin fee 234.87 > locked_margin 0.00`。
  这三个用例因此**常年是 ERROR 而非断言失败 —— 等于零有效覆盖**。更严重的是,`feed_bt.py` 的注释恰恰引用这个**跑不起来的测试**("LAHEAD-001 实证 pre_window_entry_count == 0")作为"边界安全"的依据。

**仍然成立的部分(这才是真正的缺陷)**

1. 策略里**没有任何**窗口参数,`feed_bt.py` 注释所称的 "entry 时点检查" 并不存在;边界安全来自**指标暖机的 NaN gate**,是偶然而非强制 —— 改指标周期 / `min_bars` / buffer 常量即可静默失守,且**当时没有任何守卫能发现**。
2. 引用它的那条注释本身是**不实声明**(引用了一个从未有效运行的测试)。
3. 验证层的问题属于 §6 而非 §1:守卫常年 ERROR = 零覆盖。

**处置**:已在 `fix/discipline-remediation` 分支上把 harness 改为委托生产实现(恢复有效覆盖)、在策略中加入显式 `_in_window` 边界门并由生产入口下发、并加用例**钉住生产调用点**以防"修复做成可选开关"。窗口门对既定窗口内交易是 **no-op(零漂移,成交列表逐条一致)**。

**教训(已写入本仓库流程)**:这类"分支副本式 harness"会让不变量长期假绿/假红。凡 override 生产逻辑的测试替身,必须委托生产实现,不能复制。

---

## 1. 审计方法与覆盖边界

### 1.1 方法

- 26 个审计单元,每个单元由一名 agent 读源码产出带**逐字代码引用**的发现;每条发现再由 **1–2 名独立验证者**读同一 commit 的同一文件、以**证伪为默认立场**复核,并可给出 `CONFIRMED` / `PARTIAL` / `REFUTED` 与严重度修正。
- BLOCKER/HIGH 强制 2 名验证者(一名纯证伪、一名"是否真的可达/是否已在别处处理"),MEDIUM/LOW 1 名。
- 单元级 **3 次重试**:上一轮有 14/26 单元因推理网关 429/502 静默消失,本轮修掉 —— 本轮 0 个空手单元。
- 验证者全挂时**不再等同"被驳回"**,而是单列为"无法验证"(本轮该计数为 0)。
- 之后另有一轮**完备性批判**,专门追问"哪些面没被打开"。

### 1.2 ⚠️ 覆盖缺口:gap-fill 阶段未执行

完备性批判指出了 **6 个未被任何单元打开的审计面**。我为此设计的补齐单元**全部崩溃** —— 原因是**我自己脚本的缺陷**:补齐单元对象缺少 `dim` 字段,而 `finderPrompt()` 会读取 `cell.dim.name`,于是 6 个单元在发请求前即抛 `undefined is not an object`。

**后果**:Critic 指出的这 6 个面**没有被审计**,而且在最终结果里表现为 `gap_cells: 6`(看似已覆盖)。这是本轮报告的**已知覆盖缺口**,必须显式声明。Critic 给出的缺口方向包含 §0 可复现前提、§4 做空可行性、§2 费用单源的具体调用点等 —— 其中部分内容已被成功的跨引擎单元(`x-s2-costmodel`、`x-s3-dualprice`、`x-s3-pit`、`x-s5-stats`、`x-s6-tests`、`x-s7-hygiene`)间接覆盖,但**不能视为逐条覆盖**。

### 1.3 环境限制

- 本地数据库缺失(`data/hiagent.db` 为 0 字节占位),**未运行任何回测复现**。全部结论为**静态代码分析**。
- 凡属"事件频次 / 影响量化"的结论(如"窗口前实际开仓数")依赖数据库复现,**本报告不主张其数值**;其**结构性前提**(如 feed 未设 `fromdate/todate`)已由代码证实。

---

## 2. 全量测试套件实测状态(独立于上述审计)

在 pinned `main` 快照上实测:

```
python3 -m pytest tests/ -q --tb=no -p no:randomly
→ 61 failed, 789 passed, 18 skipped, 3 errors in 1183.93s (0:19:43)
```

失败清单(64 项)与审计前在共享工作树上测得的结果**逐条完全相同**(已 `diff` 验证),因此该结论是 `main` 精确且稳定的。

这本身就是 §6 违规。§6 要求"**Tests MUST skip(not error)when the local DB or run artifacts are absent**",并要求遗留失败是"**registered debt with an owner, not background noise**"—— 当前两者都不满足:

**(a) 失败里混着两类语义相反的东西**,红/绿信号因此失效:

- **真实违约的绊线**(要求代码合规,代码不合格 → 红):`test_corporate_actions_gap`(3)、`test_corporate_actions_dividend_deposit`(3)、`test_limit_up_guard_cross_engine`(3)、`test_section4_microstructure_gap`(2)、`test_cycle_limit_up_guard`(4)、`test_short_reversal_no_lookahead`(3 + 3 ERROR)、`test_phase3_v3_bugfixes`(3)、`test_fail_fast_deep_scan_section2`(2)、`test_immutable_state_4engine`、`test_preset_to_engine_api_conformance`(4)、`test_all_in_sizing_fraction_preservation`、`test_cycle_survivorship_bias`(2)、`test_dual_price`(2)。
- **金标准哈希基线**(`test_chase_up_no_lookahead` v5–v14 共 8 条):锁定基线与当前引擎输出已不一致,且断言对象是**陈旧产物而非重跑结果**;干净检出下以 `OSError` 报错而非 skip。

**(b) 明确回归**(测试名里直接写着 `Regression`):`chase_up/portfolio.py` 不再 import `is_limit_up`;不再使用合规的成交量参与公式。曾经合规的守卫被静默移除。

**(c) 空转守卫**(§6 最致命的腐蚀):多种守卫实际不设防 —— 子串判定(`test_reproducibility_audit.py:331`)、函数不被 pytest 收集(`test_cycle_price_action_sha256_baseline.py:94`)、无断言的 `pass`(`test_cost_constants_single_source_4engine.py:265`)、恒真断言(`test_backtest_data_integrity.py:58`)、docstring 出现某词即通过(`test_wfv_rigor_gap.py:75`)。

**结论**:在一个 61 红 / 789 绿的套件里,新增的真实回归**无法被识别**。测试层当前不提供任何可信门禁。

---

## 3. 我独立复核的 BLOCKER(逐条读码)

以下各条**由我本人读取 pinned 快照源码确认**(不依赖 agent 结论),行号均为 `/tmp/hiagent-main` @ `94ca15d` 实测。

### V1 · `chase_up` 权益/NAV 双计 —— CONFIRMED

- `chase_up/portfolio.py:51` 注释定义 `locked_margin = committed to active positions (entry cost)`。
- `:91-92`:`total_cash = free_cash + locked_margin + settling_funds` —— **已含持仓成本**。
- `:619-623`:`"equity": pf.total_cash + holdings_val` —— 成本与市值**同时计入**。
- 同式污染 NAV 闸门 `:463`:`nav_now = pf.total_cash + holdings_val`。

**后果**:开仓当根 bar 起权益即被虚增约一个仓位名义金额,NAV 闸门随之失效;`Sharpe` / `max_dd` / `exposure` 全由这条错误曲线推导。
**修复**:`equity = free_cash + settling_funds + holdings_val`(或改用 `total_cash + 未实现盈亏`,与 `uptrend_pullback/portfolio.py:592` 的孤例修复对齐);补"开仓 bar 权益不变(±费用)"回归断言。

### V2 · `chase_up` Phase-2 丢弃 `raw_*` 列 —— CONFIRMED(且在默认路径触发)

`chase_up/backtrader_engine.py:187`:

```python
panel = panel_ind[["thscode", "date", "open", "high", "low", "close", "volume", "amount"]]
```

**默认路径必然触发**:`chase_up/main.py:123-127` 的 `--engine` 默认 `"backtrader"`,且 `:146-157` **两个分支都传 `panel_ind=_panel_ind`**,因此该 `else` 分支在默认 CLI 调用下必执行。

**对照**:`uptrend_pullback` 的同构位置**已修**(`backtrader_engine.py:240-245` 显式保留 raw 列)—— 说明这是引擎间漂移,不是设计取舍。
**修复**:保留 `raw_*` 列;`_build_bt_feed` 在声明 `raw_close` 却缺列时 fail-fast。

### V3 · `uptrend_pullback` Phase-2 用次根开盘覆盖止损成交价 —— CONFIRMED

`uptrend_pullback/backtrader_engine.py:181-185`(docstring `:102-103` 亦自述"实际成交价…即 bar N+1 OPEN"):

```python
# 优先用实际成交价（bar N+1 OPEN），保证 exit_price 与 net_pnl 口径一致
if strat.actual_exit_price is not None:
    ...
    net_pnl = final_cash - initial_cash
```

**后果**:成交价一律取次根 `OPEN`,与 `exit_reason` 判定解耦 → `exit_reason="SL"` 的交易可记为盈利,胜率系统性失真。§4 只允许**开盘跳过止损时**以开盘价成交(gap-through-stop),此处是无条件覆盖。

### V4 · `chase_up` 盯市/NAV/期末强平跨价格域 —— CONFIRMED

`chase_up/portfolio.py:458 / 605 / 614` 三处均取 `pi["close"]`,而 `pidx` 的 `close` 来自 `:203/212` 的 `sub["close"]`(复权);raw 域仅在 `:407/411`(触发)与 `:502/507`(入场)使用。期末强平的成交价因此落在复权域,而入场价在 raw 域。

### V5 · `short_reversal` 原始 close 与复权 MA60 混域比较 —— CONFIRMED

`short_reversal/replay_strategy_v3.py`:

```python
:913        close_v = float(d.close[0])       # v_daily 原始价 → 原始域
:910        ma60_v = indi["ma60"][0]          # ma60 = SMA(adj_close_src) → 复权域(:295-304)
:920        if not (ma5_v < ma10_v < ma20_v < ma60_v and close_v < ma20_v):   # cascade_price 分支
:927        if close_v >= ma60_v * (1.0 + self.p.close_ma60_buffer):          # default 分支
```

指标域本身是对的(`:295-304` 用 `adj_close_src`,`:284-286` 注释也正确声明"信号/指标 MUST use adj_close,Execution broker 仍读 d.close (= raw)")—— **错的是 A 条件的 close 侧没跟着切域**。
**注入上游**:`main` 上**根本没有** `signal_price_domain` 字段(`grep` 计数 0);该开关是并发分支的产物,默认值曾是违规的 `raw`,已在 `b597d0c`(`244cf99`)改为 `adj`。

### V6 · `cycle_price_action` 出场双记本金 —— CONFIRMED(本轮新增核实)

出场路径 `cycle_price_action/portfolio.py:300-302` 与 `:383-385` 结构相同:

```python
self.credit_settling(proceeds)                          # 全额卖出款 → settling
gross_in_cost = self._buy_cost(entry, self._pos.shares)
self.release_margin(gross_in_cost)                      # 入场本金 → free_cash
```

而 `:176-180` 的 `release_margin` 是**纯池间转移**(`locked_margin -= amount; free_cash += amount`,总额不变)。

**手工推演**:初始 `free=100, locked=0, settling=0`(total 100)→ 入场成本 30 后 `free=70, locked=30`(total 100)→ 出场得款 33 后 `settling=33, locked=0, free=100`,**total = 133**;而正确值应为 `103`。**多出的是一个入场本金** —— 因为卖出款已包含本金返还,`release_margin` 又把本金"退"了一次。
**修复**:出场只应记 P&L(卖出款 − 入场成本),或改为入场时真正减记现金;并加"每轮完整交易后 `total_cash == 初始 + Σ净盈亏`"的对账断言。

### V7 · `short_reversal` 窗口边界从未下发 —— CONFIRMED(结构性)

> ⚠️ **2026-10-15 更正**:本条原本的后果表述("窗口前开仓")**已被实证否定**,详见 §0.4。

- `short_reversal/_panel_loader.py:90-95` 面板向两端扩 buffer(`PANEL_FORWARD_BUFFER_DAYS` / `PANEL_POST_BUFFER_DAYS`)。
- `short_reversal/feed_bt.py:100-104` 明确写下:

```python
# 不设 fromdate/todate: 窗口边界由 strategy 内部的 indicator NaN gate
# + entry 时点检查保证 (LAHEAD-001 实证 pre_window_entry_count == 0)。
```

即 **feed 不限制在 `[start, end]` 内**,边界完全依赖策略内部检查。同族:窗口后 buffer 的 bar 亦可成交,而单测只断言窗口**前**的计数。
**注意**:本条我确认的是**结构性事实**(无 `fromdate/todate`、边界无强制约束、测试单侧覆盖)。"窗口前/后实际发生了多少笔成交"属需数据库复现的量化结论,本报告不主张其数值。

**后续复核(2026-10-15,即 §0.4)**:策略里**根本没有** `start_date`/`end_date` 参数 —— 上面注释所说的 "entry 时点检查" 并不存在。但把 harness 修好后实测:**窗口前入场数为 0**,该不变量成立。所以缺陷是"边界未被强制",而非"边界被违反"。同时该注释引用的 `LAHEAD-001` 用例当时因 harness 分叉而**常年 ERROR**,即它引用的正是自己跑不起来。

### V8 · `cycle_price_action` 出场助手越权提交(`time` 分支)—— CONFIRMED

`cycle_price_action/portfolio.py:356-365` 四路判断后 `time` 分支同样生成 `fill`(`:365 fill, reason = float(close), "time"`),随后 `:369` 无条件写 `closed_trades`、`:387` 无条件 `self._pos = None`;而调用方 `backtrader_engine.py:144` 只在 `reason in ("SL","TP")` 时重置 `_entry_day`,并在 `:147` 注释"`reason == 'time'` → fall through to max_hold check below"。

**后果**:调用方与被调方**契约矛盾** —— 调用方以为未出场,实际已平仓。持仓在第一个未触发 SL/TP 的 bar 即被强平,`max_hold` 分支成为死代码,`_entry_day` 与持仓状态不一致。

---

## 4. 我独立发现、未进入 agent 发现集的条目

以下条目**不在**任何审计单元的产出中,由我在复核过程中独立发现并实测确认。

### S1 · `short_reversal` 生产扫描路径会崩溃 —— 已在 `b597d0c` 修复

- `94ca15d`:`replay_strategy_v3.py:170` 默认 `min_cash_ratio=None`,`:565` 与 `:740` 直接 `initial_capital * min_cash_ratio`;
- 而 `scan_signals.py:107` 构造 `Phase3V3Strategy` 时**未传** `min_cash_ratio`(`grep` 零匹配),`lookahead_trade_trace.py:48` 又继承该类;
- → 走 `scan_signals` 时在首个有 pending entry 的 bar 抛 `TypeError: unsupported operand type(s) for *: 'float' and 'NoneType'`,在测试套件中触发 **10 次失败**。

**状态**:`b597d0c` 的 `c06ead1` 已将默认值改为 `0.05`(`replay_strategy_v3.py:196`),该次崩溃消除。

> **2026-10-16 补充(附三十八)**:该表述**过窄** —— 那次只是补了**一个**参数。同一条生产扫描路径
> 在 `min_cash_ratio` → `nav_gate_ratio` 改名并改为 fail-fast 之后**再次崩溃**(同一个工具、不同的漏参),
> 且没有任何测试覆盖它。病根是「策略构造参数清单有两份、靠人手同步」。现已从根上修掉:
> 抽出 `engine.strategy_kwargs` 单源,回测入口与扫描工具共用 55 项参数。

### S2 · 不可变性守卫可被"别名"绕过,源码注释明说这是为了绕过检测器 —— **已修复(附二十八)**

`short_reversal/replay_strategy_v3.py:574-580`:

```python
# ... Local alias
# preserves runtime semantics while satisfying AST detector in
# tests/test_immutable_state_4engine.py.
pending = self.pending_entries
pending.clear()
```

三层问题:

1. 该守卫是**纯静态 AST/文本扫描**(`tests/test_immutable_state_4engine.py:85-91` 匹配 `self.<attr>.<mutable_method>(...)`),一个局部别名即可绕过,**运行时 `.clear()` 照旧原地修改**;
2. **源码注释直接承认**了规避意图 —— 这让"测试通过"不再具备任何含义,是 §6 意义上最严重的测试层腐蚀;
3. 即便如此该测试**仍然失败**(`:598` 的 `self.pending_entries.pop(code, None)` 未被别名修饰)—— 守卫既被绕过、又未被满足。

**修复**:守卫改为**运行时**断言,或 AST 层面禁止"取到可变属性后再调用破坏性方法";`.clear()`/`.pop()` 改为重建新集合(符合 §0 append-only)。

### S3 · 守卫静默跳过不存在的文件,覆盖是假的 —— **已修复(附二十八)**

`tests/test_immutable_state_4engine.py:104-105`:

```python
for path in paths:
    if not path.exists():
        continue
```

而 `:73` 列出的 `short_reversal/portfolio.py` **实际不存在**(该策略的引擎是 `replay_strategy_v3.py`)。扫描器对缺失文件**静默跳过**,对 `short_reversal` 的不可变性覆盖比表面看起来更少。同类"静默跳过"模式是 §0 Fail-Fast 的直接违反。
**修复**:路径缺失即 fail-fast;修正文件清单。

---

## 5. 未能验证 / 请自行确认

- **`b597d0c` 未做完整复审计**。我只逐条核实了 4 个修复提交;`main` 其余部分在新 tip 上是否仍有同样问题,未复核。
- **无任何回测被真实复现**(DB 缺失)。凡"实际发生了 N 笔 / 影响 X 元"类量化结论均未主张。
- **6 个 Critic 缺口面未审计**(见 §1.2 的脚本缺陷)。
- §6 完整报告中 **HIGH / MEDIUM / LOW 条目我未逐条复核**。引用其 `file:line` 前请自行打开 pinned 快照确认(该报告在生成时已被要求"每条发现必须有逐字引用",且每条都过了对抗验证,但这不等于我逐条读过)。

---

## 6. 完整审计报告(agent 产出,经对抗性验证)

> 以下为 26 单元审计 + 对抗性验证的完整产出,逐条给出 `file:line`、问题与修复方向。其中 **§3 我本人复核过的 8 条**与本节一致;其余条目为验证者确认,可信度见 §5 的说明。

# hiagent A 股量化回测仓库 · 纪律审计报告

**被审计对象：`/tmp/hiagent-main`，commit `94ca15d`（`94ca15d60e0ead5ee495be9ba9d92ff7bb86f7df`，本地 `main` 的 tip），只读检视。**
**范围约束（用户指令）：只校验 main 分支代码。本报告不引用任何其它分支的实现状态。**

审计依据：`CLAUDE.md` §0–§7（绝对确定性：时间、资本、数据真实性、执行、统计严谨、架构、产物卫生）。
校验方式：26 个审计单元（cell）分派，每个单元内的高影响结论由 1–2 名独立验证者读同一 commit 的同一文件并尝试证伪。

---

## 0. 审计规模与口径

| 项目 | 数值 |
|---|---|
| 分派 cell 数 | 26 |
| **无结果（空手而归）的 cell** | **0 个 —— 没有任何单元因故未返回结果**（证据包 `cells_with_no_result: []`） |
| 记录的 gap cell | 6 个（证据包只给了数量，未附单元名，无法逐一列出；已在第 8 节作为覆盖缺口提示） |
| 原始发现 | 208 条 |
| 通过对抗验证 | 203 条（证据包自报） |
| 被证伪（refuted） | 1 条（见第 7 节） |
| 逐条清点的严重度分布 | BLOCKER 20 / HIGH 64 / MEDIUM 74 / LOW 50 = 208 |

> 口径说明：证据包自报的 208 raw / 203 verified / 1 refuted 三者相加与 208 不完全对齐（差额 4）。本报告按 `findings` 数组逐条清点，故以 **208 条、20 条 BLOCKER** 为准；`refuted` 数组中的 1 条单独列出、不计入违规。

> 重要时效说明：`94ca15d` 是本地 `main` 的 tip，但 `origin/main`（`b597d0c`）已领先一个 merge，其中包含对 short_reversal 的费用单源化（`7337911`）、`BORROW_ASSUMPTION` 声明更正（`1e85d8e`）、`signal_price_domain` 默认改 adj（`244cf99`）。因此本报告中针对 `short_reversal/engine.py:37-38` 的费率重复、`short_reversal/presets.py:14-17` 的借券声明矛盾、以及 short_reversal A/B/C 信号域的条目，**在远端 main 上已部分修复**；其余条目在远端 main 上未见对应修复提交。审计结论按指令仍以 `94ca15d` 为准，但修复优先级一节已按此排序。

---

## 1. 总体结论

**main 未达到纪律合规。**

- **四个策略包全部违规**（chase_up / uptrend_pullback / short_reversal / cycle_price_action），无一合规。
- **20 条 BLOCKER 级发现**，去重后为 **11 个独立缺陷族**。其中 2 族的严重度在验证层存在分歧（见 4.1 表末两行的备注），另有若干族由多个 cell 独立命中同一处代码。
- 问题不是零散的代码瑕疵，而是四类**系统性**缺陷：现金账/NAV 表达式的双重计入、双价体系（原始价 vs 复权价）半迁移、ATR 滑点在全部 preset 中恒为 0、以及测试层守卫大面积空转。

---

## 2. 四个策略包逐包结论

### 2.1 chase_up（追涨）—— **违规**（6 条 BLOCKER）

违反条款：

- **§2**：`chase_up/portfolio.py:619-623`、`chase_up/portfolio.py:463`（权益/NAV 双计持仓成本基础与市值）；`chase_up/portfolio.py:247-249`、`chase_up/backtest.py:142-144`、`chase_up/backtrader_engine.py:212-214`、`:286-287`（费率常量引擎内重复定义）；`chase_up/main.py:83-90`（cash_walk 三种现金池写死为 0、`free_cash` 填 `total_cash`）；`chase_up/presets.py:53`（22 个 preset 声明 `position_fraction`，引擎从不读取）。
- **§3 / §0**：`chase_up/backtrader_engine.py:187`（传 `panel_ind` 时丢弃 `raw_open/high/low/close`，Phase-2 静默在复权域撮合）；`chase_up/portfolio.py:605`、`:614`、`:458`（盯市、NAV 门、期末强平用复权价，而入场与 SL/TP 用原始价）；`chase_up/portfolio.py:349-355`（无公司行为事件源，分红不入账、拆股不调仓）。
- **§4**：`chase_up/backtest.py:145-146`、`chase_up/portfolio.py:254`、`chase_up/backtrader_engine.py:215-216`（ATR 滑点恒为 0，0/22 preset 启用）；`chase_up/portfolio.py:426-437`（卖出侧无跌停不成交判定）；`chase_up/replay_strategy.py:80-87`（Phase-2 同 bar SL/TP 取 TP 优先，与 Phase 1 相反）；`chase_up/portfolio.py:530-537`、`chase_up/portfolio.py:350-357`（量比上限只在入场生效，出场全额成交）。
- **§1**：`chase_up/portfolio.py:614`（停牌/无 bar 时按 `entry_price` 盯市，而非最后 `raw_close`）。
- **§6**：`tests/test_chase_up_no_lookahead.py:642-656`（干净检出下 8 个 golden 守卫 ERROR；有旧产物时只校验旧 CSV，不重算引擎）。

核心：权益曲线（进而风险指标）与 NAV 门被同一个双计表达式污染；Phase-1/Phase-2 两套引擎对同一 preset 给出互相矛盾的结论。

### 2.2 uptrend_pullback（趋势回调）—— **违规**（1 条 BLOCKER）

违反条款：

- **§4**：`uptrend_pullback/backtest.py:177-178`、`uptrend_pullback/backtrader_engine.py:290-291`、`uptrend_pullback/presets.py:186`（ATR 滑点恒为 0）；`uptrend_pullback/portfolio.py:400-411`、`:404`（跌停封板仍按 SL/开票价成交）；`uptrend_pullback/replay_strategy.py:128-137`（同类问题在 Phase-2 镜像）；`uptrend_pullback/replay_strategy.py:142`、`backtrader_engine.py:176`（默认 backtrader 引擎按次 bar 开盘成交且吞掉不可成交 trade，与 Phase-1 报告口径不一致）。
- **§3**：`uptrend_pullback/portfolio.py:577`（持仓盯市用复权 close，入场基为 raw_open）；`uptrend_pullback/portfolio.py:391`（原始域执行把除息跳空记为盈亏，无分红入账）。
- **§2**：`uptrend_pullback/main.py:70-77`（cash_walk 池写死为 0）；`uptrend_pullback/portfolio.py:428`（NAV 门把 `total_cash` 与持仓市值相加）；`uptrend_pullback/portfolio.py:216-218`、`backtest.py:174-176`、`backtrader_engine.py:287-289`/`:366-367`（费率常量重复）。
- **§1**：`uptrend_pullback/portfolio.py:567`（期末强平在无 bar 时按 `entry_price` 造出成交）；`:426`（NAV 门在开盘决策瞬间读取当根 bar 收盘）。
- **§6**：`uptrend_pullback/main.py:112`（默认引擎 backtrader，而 golden 只锁 simulate 的成交列表）。

补充：本包是四引擎中**唯一**已把权益行修正为「总现金 + 未实现盈亏」的（`portfolio.py:592`），但同一函数的 NAV 门（`:428`）未同步修正——同族缺陷里的孤例修复。

### 2.3 short_reversal（做空反转）—— **违规（最严重，7 条 BLOCKER）**

违反条款：

- **§1**：`short_reversal/_panel_loader.py:90`（面板向前扩 180 天、窗口下界从未下发策略；指标按 (start,end) 年化）—— ⚠️ 原报告附带的"导致窗口前开仓"**已证伪,见 §0.4**:边界确实未被强制,但实测无窗口外成交;`short_reversal/_panel_loader.py:93` + `short_reversal/feed_bt.py:101`（窗口后 60 天 bar 可成交,单测只断言窗口前计数 —— 该单测当时因 harness 分叉常年 ERROR）。
- **§2**：`short_reversal/replay_strategy_v3.py:820`（入场佣金+印花税 lock 后又被全额 release 回 Free_Cash，现金账从不扣除）；`:388`（`settle()` 只在为正时冲刷，亏损永不回到 Free_Cash）；`:636`、`:582`、`:465`（`max_positions` 只是定仓除数不是容量上限；并发信号按代码字母序成交）；`engine.py:61`（`final_capital` 取 `total_cash`，期末持仓不计浮盈）；`engine.py:37-38`、`replay_strategy_v3.py:58-60`（费率常量重复，且注释谎称已从 core 导入）。
- **§3**：`short_reversal/replay_strategy_v3.py:927`、`:913`、`indicators_bt.py:102`、`:117`（原始 close 与复权 MA60 混域比较）；`scan_signals_fast.py:43`（线上扫描器全部指标用原始价，文档却声称与策略等价）；`replay_strategy_v3.py:546`（无公司行为事件源，做空在除息日把缺口记为利润）。
- **§4**：`short_reversal/replay_strategy_v3.py:769-770`（跳空穿越止损时按 `sl_p` 成交）；`:592`、`:23`（做空的回补是买入，却无 `is_limit_up` 守卫）；`:646`（volume 为 0/NaN 时量比上限整体跳过）；`engine.py:266`、`replay_strategy_v3.py:175`（ATR 滑点恒为 0）；`presets.py:14-17`（`borrow_cost_model` 声明与引擎实际计费矛盾，远端 main 已修）。
- **§6**：`tests/test_reproducibility_audit.py:331`（无任何 golden 基线，唯一相关测试空转通过）；`replay_strategy_v3.py:392`（策略与执行经纪融合成一层）；`scan_signals_fast.py:113`（重复实现策略条件）；`st_filter.py:44`（被声明为「纯信号层」的函数里通过 subprocess 发网络 IO）。

### 2.4 cycle_price_action（周期/价格行为）—— **违规**（2 条 BLOCKER）

违反条款：

- **§1 / §3**：`cycle_price_action/data_feed.py:211`（流动性筛选 SQL 无日期上界，成员由窗口之后的全表成交额决定）；`data_feed.py:160`、`:163`（成员判定只有 `MAX(date) >= ref_end`，窗口内 IPO 混入 as-of 宇宙）。
- **§2**：`cycle_price_action/portfolio.py:300-302`、`:383-385`（出场同时把入场成本退回 Free_Cash 又把全额卖出款计入 Settling）；`portfolio.py:179`（`release_margin` 给 free_cash 记账，与 chase_up/uptrend 的约定相反）；`portfolio.py:131-140`（`settle()` 在包内无调用点）；`portfolio.py:224`（NAV 门读被抬高的 `self.cash`）；`portfolio.py:68-69`、`replay_broker.py:68`（费率常量重复）；`backtest.py:98`（每只股票一个全新 1,000,000 账户，preset 的 `max_positions`/`position_fraction` 被 `_accepted` 白名单丢弃）；`backtrader_engine.py:174-176`、`:185-191`、`:200`（入场按决策 bar 收盘记账、丢弃 broker 成交价，出场却用成交价）。
- **§3**：`cycle_price_action/backtrader_engine.py:102-109`、`backtest.py:82-87`、`signals.py:87`（`adj_close` 被 join 后在喂给信号层前丢弃，MA 用原始价）；`portfolio.py:284`（无公司行为事件源）。
  ⚠️ **根因更正（2026-10-15 修复时发现）**：`adj_close` 不是"被丢弃"，而是**从未被提供**。`data_feed._table_exists()` 只查 `duckdb_tables()`，而 `v_daily_hfq` 是**视图**，于是探测恒为 False，`load_universe_data` 静默走 raw-only 分支 —— §3「指标必须用复权价」在本引擎的历史上从未生效。已修为同时查表与视图（`_relation_exists`）。这说明"join 到了"不等于"送达了"：审计记录的是下游症状，真正的一环在上游。。
- **§4**：`portfolio.py:356-365`（出场阶梯无跌停不成交判定）；`backtrader_engine.py:93`、`replay_broker.py:42`（ATR 滑点结构性不可达）；`portfolio.py:256-262`（10% 量比上限在 volume 不足一手时整体跳过）；`backtrader_engine.py:168`（涨跌停守卫判在决策 bar，而实际成交在次 bar）；`backtrader_engine.py:307`（出场侧完全无量比上限）。
- **§6**：`tests/test_cycle_price_action_sha256_baseline.py:55`、`:94`（无 golden 基线，且哈希比对函数不被 pytest 收集）。

---

## 3. 发现清单

> 表中凡属「事件频次 / 影响量化」的结论依赖本机数据库复现（见第 8 节）；其余全部为快照内静态代码即可断言。
> 同一处代码被多个 cell 重复命中的，归并为一行并列出全部 file:line。

### 3.1 BLOCKER（20 条，11 族）

| 严重度 | 规则 | 文件:行 | 问题 | 修复方向 |
|---|---|---|---|---|
| BLOCKER ×5 | §2 | `chase_up/portfolio.py:619-623`；同式 `chase_up/portfolio.py:463`（s1/s2/s3/s4/s6 五个 cell 各命中一次） | 权益/NAV 同时加持仓成本基础（`locked_margin`）与持仓市值（`holdings_val`），仓位被计两次；`total_cash` 本身已含成本基础 | NAV = `free_cash + settling_funds + 持仓市值`；或改用 `total_cash + 未实现盈亏`（与 `uptrend_pullback/portfolio.py:592` 一致）。加回归断言：开仓 bar 权益不变（±费用） |
| BLOCKER ×1 | §3 / §0 | `chase_up/backtrader_engine.py:187` | 传 `panel_ind` 时把 `raw_*` 列裁掉，Phase-2 在复权域撮合，却拿原始域 TP/SL 去比；同一 preset 同一窗口下 CLI 与 walk-forward 两条入口结论互相矛盾，且无任何运行期检测 | `panel = panel_ind`（或补齐 raw_* 列）；`_build_bt_feed` 在声明 `raw_close` 而缺列时 fail-fast |
| BLOCKER ×1 | §4 | `uptrend_pullback/backtest.py:177-178`；`uptrend_pullback/backtrader_engine.py:290-291` | ATR 滑点在 0/3 个 preset 中启用，成交价恒等于 bar 开盘价，§4 的 ATR×参与率模型形同不存在 | preset 显式声明非零 `atr_slip_scale`，或引擎在两者都缺失时 fail-fast |
| BLOCKER ×1 | §1 | `short_reversal/_panel_loader.py:90` | 面板起点向前扩 180 天，但窗口下界从未下发策略，边界仅靠指标暖机 NaN gate 偶然保证、无任何强制；指标仍按 (start,end) 年化。⚠️ **原表述"窗口前开仓"已证伪(§0.4)**：实测无窗口外成交 | 把 (start,end) 传进策略并拒绝窗口外 entry，或按实际成交窗口计算指标 |
| BLOCKER ×3 | §2 | `short_reversal/replay_strategy_v3.py:820`（s2/s3/s6 三个 cell 各命中一次） | `entry_cost = notional + entry_fee` 被 lock 后，`release_margin` 把含费用的全额 release 回 Free_Cash，入场费从不从现金账扣除，`final_capital` 系统性偏高 | release 只放 notional，或入场即扣 `entry_fee`；加断言 `final_capital == INITIAL + Σ net_pnl − Σ margin_fee` |
| BLOCKER ×2 | §4 | `short_reversal/replay_strategy_v3.py:769-770`；同族 `:769` | 做空的跳空穿越止损按 `sl_p` 成交（s3、s4 两个 cell 各命中一次），把跳空损失截断在止损幅度内 | 跳空分支改用 `open_p` 成交 |
| BLOCKER ×2 | §3 | `short_reversal/replay_strategy_v3.py:927`、`:913`；`indicators_bt.py:102`、`:117` | 原始 `close` 与复权 `MA60` 在同一谓词里比较（A 条件与 below_ratio 双双中招） | 两侧同域：指标与比较操作数统一使用 `adj_close` |
| BLOCKER ×2 | §3 / §1 | `cycle_price_action/data_feed.py:211`（s1、x-s3-pit 两个 cell） | 流动性筛选 SQL 全表无日期上界，宇宙成员由窗口之后的成交额决定 | 加 `AND date <= asof_date`，并用因果滚动统计替代全样本 `mean()` |
| BLOCKER ×1 | §2 | `cycle_price_action/portfolio.py:300-302`；同式 `:383-385`、`:179` | 出场同时把入场成本基础退回 Free_Cash、又把全额卖出款计入 Settling，每个回合凭空造出成本基础规模的血包 | 只记已实现盈亏，或不清退保证金；加守恒不变量测试 |
| BLOCKER ×1 | §3 | `chase_up/portfolio.py:349-355` / `uptrend_pullback/portfolio.py:355` / `short_reversal/replay_strategy_v3.py:546` / `cycle_price_action/portfolio.py:284` | 四个引擎均无公司行为事件源：分红不入 Free_Cash、拆股不调数量与成本 | 接入 ex_date 事件表；分红入账、拆股原子调仓；命中事件却无记录时 fail-fast。**注：本族严重度存在验证分歧，一名验证者主张降为 MEDIUM（有引擎实测暴露为零）** |
| BLOCKER ×1 | §6 | `tests/test_reproducibility_audit.py:331` | short_reversal 无任何 golden 基线，唯一相关测试因 `short_reversal/results/` 被 gitignore 而不可能断言任何东西 | 生成 `tests/golden/short_reversal_*_baseline.json` 并断言；缺 DB 时 `pytest.skip`。**注：两名验证者对 BLOCKER/HIGH 有分歧** |

### 3.2 HIGH（64 条，按缺陷族归并）

| 严重度 | 规则 | 文件:行 | 问题 | 修复方向 |
|---|---|---|---|---|
| HIGH ×4 | §3 | `chase_up/portfolio.py:605`、`:614`、`:458`；`uptrend_pullback/portfolio.py:577`、`:426`；`cycle_price_action/signals.py:87`、`backtest.py:82`、`backtrader_engine.py:102` | 盯市/NAV 门/期末强平用复权价，入场与 SL/TP 用原始价；cycle 甚至把已 join 的 `adj_close` 丢弃后仍用原始价算 MA | 全链路统一到执行域 `raw_close`，或显式声明并用同一域 |
| HIGH ×3 | §4 | `chase_up/backtest.py:145-146`、`chase_up/portfolio.py:254`、`chase_up/backtrader_engine.py:215-216`；`uptrend_pullback/backtest.py:177`、`backtrader_engine.py:290`、`presets.py:186`；`short_reversal/engine.py:266`、`replay_strategy_v3.py:175`；`cycle_price_action/backtrader_engine.py:93`、`replay_broker.py:42` | 全库 ATR 滑点为 0，无任一 preset 启用；零滑点比 §4 明令禁止的固定费率更乐观 | core 定义唯一滑点策略，preset 必须显式声明；否则 fail-fast |
| HIGH ×5 | §4 | `uptrend_pullback/portfolio.py:400-411`、`:404`；`chase_up/portfolio.py:426-437`、`:430`；`cycle_price_action/portfolio.py:356-365`；`short_reversal/replay_strategy_v3.py:592`、`:23` | 涨跌停规则只做了一半：买方涨停被拦，卖出侧跌停不成交无人实现；做空的回补（买入）无涨停守卫 | 用 `core.dual_price.is_limit_up` / `is_limit_down` 双向补齐，并把仓位顺延到下一可成交 bar |
| HIGH ×4 | §1 | `short_reversal/_panel_loader.py:93`、`feed_bt.py:101`、`engine.py:227`、`backtest.py:66`、`chase_up/universe.py:49`、`chase_up/walkforward.py:48`、`tests/_regen_chase_baselines.py:64`、`run_sizing_comparison.py:49` | 窗口边界与宇宙 as-of 在各入口口径不一：post-buffer 可成交、WFV 全程复用单一 asof、非交易日 asof 静默产出空宇宙 | 每窗口解析 as-of；空宇宙 fail-fast；feed 设 todate |
| HIGH ×3 | §2 | `short_reversal/replay_strategy_v3.py:388`、`:636`、`:582`、`:465`；`short_reversal/engine.py:61` | `settle()` 只冲刷正值（亏损永不回 Free_Cash，all-in 用虚高资金定仓）；`max_positions` 不是容量上限；并发信号按字母序成交；期末持仓不计浮盈 | 无条件冲刷；加容量门与显式信心排序；`final_capital` 改用 `_nav()` |
| HIGH ×2 | §2 | `cycle_price_action/portfolio.py:131-140`、`:179`、`:224` | `settle()` 无调用点，T+1 结算从不发生，亏损记账不回流 | 每 bar 开头调用 `settle()` |
| HIGH ×2 | §4 / §0 | `cycle_price_action/backtrader_engine.py:174-176`、`:185-191`、`:200` | 入场按决策 bar 收盘记账并丢弃 broker 成交价，出场却用成交价——同一生命周期两套成交约定 | 统一用 `fill.price` / `fill.date` 记账；缺口部分按 §2 保证金门重算 |
| HIGH ×3 | §4 / §3 | `uptrend_pullback/replay_strategy.py:142`、`backtrader_engine.py:176`、`:356`；`chase_up/replay_strategy.py:80`、`:33`、`:50`；`cycle_price_action/backtrader_engine.py:168` | Phase-2 引擎语义与 Phase-1 分歧：次 bar 开盘成交、TP 优先 tie-break、`skipped` 标志永不置位、涨停守卫判在错误 bar | 单一成交约定；tie-break 全部 SL-first；补 fill-bar 复核 |
| HIGH ×4 | §6 | `tests/test_chase_up_no_lookahead.py:642-656`；`tests/test_cycle_price_action_sha256_baseline.py:94`、`:55`；`tests/test_cost_constants_single_source_4engine.py:265`；`tests/test_backtrader_engine_net_return_entry_commission.py:60` | 守卫空转：写 gitignore 目录导致 ERROR、哈希函数不被 pytest 收集、无断言 `pass`、唯一 xfail 是 `strict=False`；全套 61 failed + 3 error 无 owner | 改为真正的参数化断言与内联重算；失败登记 owner 或修绿 |
| HIGH ×2 | §5 | `uptrend_pullback/iter_reverse.py:245`；`uptrend_pullback/sweep_v33_long.py:30`、`:182`、`:189`、`sweep_v33_long_v6.py:177`；`short_reversal/wf_v34_focused.py:52`、`grid_runner.py:27`；`chase_up/wf_sweep_all.py:175` | 100 次随机搜索在同一窗口选优并直接报告；网格在同一窗口排序；DSR 的 `n_trials` 只算本次网格（或直接键名错误导致永不打印）；窗口跨越已声明的 holdout | 走 `wfv_eval` / `core.walkforward`，累计 `n_trials`，先修键名 |
| HIGH ×3 | §7 | `tests/golden/chase_v19_baseline.json:12`、`:55`；`chase_up/presets.py:1049`；`short_reversal/presets.py:397`；`tests/_capture_presets.py:39`；`tests/_regen_chase_baselines.py:109` | 被跟踪的 golden 与源码注释内嵌历史业绩字段与未去偏的选优叙述；且再生成脚本会持续把 metrics 块写回 | 删除数值，只留复现方法；先修再生成脚本，且 golden 只保留哈希锁 |
| HIGH ×1 | §1 | `chase_up/portfolio.py:614`、`uptrend_pullback/portfolio.py:567`、`:577` | 停牌/退市按 `entry_price` 盯市并据此强平，等于把尾部事件抹平 | 记录 `last_raw_close` 并用它盯市 |

### 3.3 MEDIUM / LOW（124 条，按主题归并）

| 严重度 | 规则 | 文件:行 | 问题 | 修复方向 |
|---|---|---|---|---|
| MEDIUM ×4 | §2 | `chase_up/main.py:83-90`、`uptrend_pullback/main.py:70-77`、`short_reversal/main.py:97-108`、`cycle_price_action/main.py:153-160` | cash_walk.csv 把 `locked_margin`/`settling_funds` 写死为 0、`free_cash` 填 `total_cash`；且 `nav` 与 `total_equity` 同行互相矛盾 | 从引擎输出真实三池；`nav` 与权益恒等式一致 |
| MEDIUM ×6 | §2 | `chase_up/portfolio.py:247-249`、`backtest.py:142-144`、`backtrader_engine.py:212-214`/`:286-287`；`uptrend_pullback/portfolio.py:216-218`、`backtest.py:174-176`、`backtrader_engine.py:287-289`/`:366-367`；`short_reversal/engine.py:37-38`、`replay_strategy_v3.py:58-60`；`cycle_price_action/portfolio.py:68-69`、`replay_broker.py:68` | 费率常量在引擎内重复定义（值目前一致，属潜在漂移）；部分注释谎称已 import | 全部改为 `from core.dual_price import COMMISSION_RATE, STAMP_DUTY_RATE, MIN_COMMISSION` |
| MEDIUM ×3 | §2 | `chase_up/presets.py:53`、`uptrend_pullback/verify_v33_long_reverse_v4.py:25`、`cycle_price_action/backtest.py:75-76` | preset 声明的 `position_fraction` / `max_positions` / `max_volume_participation` 被引擎或白名单静默丢弃 | 接通或显式 fail-fast，不允许静默降级 |
| MEDIUM ×3 | §4 | `chase_up/portfolio.py:530-537`、`:350-357`；`uptrend_pullback/portfolio.py:493-504`、`:331`；`short_reversal/replay_strategy_v3.py:646`、`:701`；`cycle_price_action/portfolio.py:256-262`、`:307` | 量比上限在 volume=0/NaN 时整体跳过（fail-open，与 §0 悲观默认相反）；出场侧完全无量比上限 | 统一调用 `core.dual_price.volume_cap_fill`；0 成交即拒单；出场给显式策略 |
| MEDIUM ×4 | §4 | `chase_up/replay_strategy.py:80-87`、`:84`；`uptrend_pullback/replay_strategy.py:128-137`；`cycle_price_action/backtrader_engine.py:168`、`:144`；`chase_up/portfolio.py:512`、`:430` | Phase-2 TP-first tie-break；SL/TP 以绝对价交给 replay；限价守卫判在错误 bar | 统一 SL-first；改为相对百分比 + 正确 bar 复核 |
| MEDIUM ×3 | §3 | `chase_up/portfolio.py:355`、`uptrend_pullback/portfolio.py:391`、`cycle_price_action/portfolio.py:284`、`short_reversal/replay_strategy_v3.py:546` | 除息/除权日按原始价记账，无反向现金事件（做空侧方向相反，等于系统性利润虚增） | 见 BLOCKER 同族 |
| MEDIUM ×3 | §6 | `short_reversal/replay_strategy_v3.py:392`、`scan_signals_fast.py:113`、`st_filter.py:44` | 执行经纪与策略融合、条件被第二处复制实现、被声明为纯信号层的函数里发子进程/网络 IO | 抽出 broker 层；单一实现；名称解析移到控制面并缓存 |
| MEDIUM ×4 | §5 | `uptrend_pullback/sweep_v33_long.py:30`、`:182`、`:189`、`sweep_v33_long_v6.py:177`、`short_reversal/wf_v34_focused.py:52`、`grid_runner.py:27`、`chase_up/wf_sweep_all.py:175` | 见 3.2 同族；另有 `dsr['p_value']` 键名错误使 DSR 行永不输出 | 修键名；OOS 窗口；累计 `n_trials` |
| MEDIUM ×1 | §2 | `cycle_price_action/backtest.py:98` | 每只股票一个全新 1,000,000 账户，容量约束跨股票不存在 | 单一资金池 + 容量预算 |
| LOW ×~40 | §1/§2/§3/§4/§6/§7 | `chase_up/portfolio.py:172`（`LIMIT_UP_THRESHOLD` 双定义）；`chase_up/portfolio.py:463`、`chase_up/main.py:85`、`chase_up/presets.py:53`；`uptrend_pullback/portfolio.py:216`、`:390`、`:428`、`:499`、`backtrader_engine.py:399`；`short_reversal/universe.py:19`、`:73`、`presets.py:14`、`replay_strategy_v3.py:646`；`cycle_price_action/portfolio.py:224`、`:256-257`、`replay_broker.py:68`、`data_feed.py:163`、`main.py:153`；`core/dual_price.py:134`；`.gitignore:31`；`tests/test_backtest_data_integrity.py:58`、`tests/test_reproducibility_audit.py:352`、`tests/golden/uptrend_v33_long_reverse_v21_baseline.json:29` | 常量重复与口径不一、参数未生效、宇宙过宽/黑名单死路径、WFV 单 asof、`.gitignore` 无文件名级全局模式、恒真断言（`assert cov >= 0.0`）、golden 里内嵌业绩叙述 | 逐条加固；其中「恒真断言」与「子串判定」应改为真断言 |

---

## 4. 系统性模式（同一违规跨引擎重复）

1. **§2 权益/NAV 表达式把「持仓成本基础」与「持仓市值」相加**——四引擎全中：`chase_up/portfolio.py:619-623`、`:463`；`uptrend_pullback/portfolio.py:428`（其权益行 `:592` 已修，门未修）；`cycle_price_action/portfolio.py:300-302`、`:383-385`、`:179`；`short_reversal` 侧以「`settle()` 只冲刷正值 + 报告 `total_cash`」的形式出现（`replay_strategy_v3.py:388`、`engine.py:61`）。这是本次审计最普遍、影响面最大的一类。
2. **ATR 滑点恒为 0**——`chase_up/backtest.py:145-146`、`uptrend_pullback/backtest.py:177-178`、`short_reversal/engine.py:266`、`cycle_price_action/backtrader_engine.py:93`；无任一 preset 声明非零值，`core.dual_price.atr_slippage` 在生产代码中零调用。§4 的强制条款在全部四引擎上处于「已实现但永不可达」状态。
3. **双价体系半迁移**：指标域迁到了 `adj_close`，但盯市、NAV、期末强平、甚至部分条件比较仍留在旧域——`chase_up/portfolio.py:605/614/458`、`uptrend_pullback/portfolio.py:577`、`short_reversal/replay_strategy_v3.py:927/913`、`indicators_bt.py:102/117`、`cycle_price_action/signals.py:87`。
4. **涨跌停规则只做了一半**：买方涨停有守卫，卖方跌停不成交无人实现（`chase_up/portfolio.py:512` vs `:426-437`；`uptrend_pullback/portfolio.py:481` vs `:400-411`；`cycle_price_action/backtrader_engine.py:168`；`short_reversal` 有 `is_limit_down` 入场却没有 `is_limit_up` 平仓，`replay_strategy_v3.py:592`、`:23`）。
5. **费率常量在引擎内重复定义**：`core/dual_price.py:318-320` 是唯一规范源，但四个引擎各自再写一遍（chase_up、uptrend_pullback、short_reversal、cycle_price_action 共 12 处），且多处注释谎称已 import。值目前一致，属潜在漂移。
6. **公司行为事件源缺失**：四引擎均无分红入账、无拆股调仓；对做空方向后果相反（把除权缺口记为利润）。
7. **cash_walk.csv 三池硬编码为 0**：四个 `main.py` 的写法完全相同，且仓库自带的 schema 测试只断言表头，不断言取值。
8. **Phase-1 / Phase-2 双引擎语义分歧**：成交价约定、tie-break 顺序、限价守卫、不可成交 trade 的落盘口径四引擎各自不一致，而默认 CLI 走的就是 Phase-2。
9. **窗口边界与宇宙 as-of 约束不统一**：`short_reversal/_panel_loader.py:90`、`:93` 完全不下发窗口；`chase_up/walkforward.py:48`、`uptrend_pullback/walkforward.py:56`、`:grid.py:99` 全程复用单一 asof；`cycle_price_action/data_feed.py:211`、`:163` 甚至无上界；`chase_up/universe.py:49` 在非交易日静默返回空宇宙。
10. **测试层守卫大面积空转**：`tests/test_reproducibility_audit.py:331`、`:352`（子串判定）、`tests/test_cycle_price_action_sha256_baseline.py:94`（函数不被收集）、`tests/test_cost_constants_single_source_4engine.py:265`（无断言 `pass`）、`tests/test_chase_up_no_lookahead.py:642-656`（写不存在目录→ERROR / 读旧产物）、`tests/test_backtest_data_integrity.py:58`（恒真断言）。全套 61 failed + 3 error 无 owner，违反 §6「已登记的债」。
11. **量比上限 fail-open 的同一写法**：四个引擎都用 `if bar_vol > 0:` 包住限额块，volume 缺失或为 0 时整体跳过而非拒单，方向与 §0 悲观默认相反。

---

## 5. 已验证合规项（不是只挑毛病）

以下内容被逐条核查后判定**合规**，记录在此以界定审计覆盖面：

**§1 时间确定性**
- 四个引擎均无 `bfill` / `ffill` / `shift(-x)` / `rolling(center=True)`（grep 与 AST 扫描一致）。
- chase_up 指标因果性做了逐行验证：把面板在 T 处截断重算，全部指标列逐行一致（百万行量级）。
- 无全局 `.mean()` / `.std()` 归一化进入任何信号或定仓决策。
- 信号 T 日出、T+1 开盘成交的因果顺序正确；当日买入当日不可卖（T+1）在四引擎均成立。
- 停牌/缺失 bar 的「不造 bar、不产生成交」这一半在引擎内是成立的（另一半盯市价问题已单列）。

**§2 资本与状态**
- 所有 preset 都**显式声明**了 `max_positions` 与 `position_fraction`（chase_up 22/22、short_reversal 47/47、uptrend_pullback 3/3），满足「不得隐式」这一条。
- 单发子弹排序存在：chase_up/uptrend_pullback 按 `score` 降序后按容量 `break`，超容量信号直接丢弃、不排入 T+1。
- 三池状态机在 chase_up / uptrend_pullback / short_reversal 中真实存在且被使用（`free_cash` / `locked_margin` / `settling_funds` + 每 bar `settle()`）；cycle_price_action 侧是「有定义无调用」。
- 保证金守门人是「减一手或拒单」而不是借入（chase_up / uptrend_pullback / short_reversal / cycle_price_action 均如此）。

**§3 数据真实性与双价体系**
- 四个引擎的 TP/SL 一律以**相对百分比**下达，未发现「用复权价推出的绝对点数」。
- 宇宙查询在 chase_up / uptrend_pullback / short_reversal 的引擎入口均显式传 `asof_date=<窗口起点>`；uptrend_pullback 的 `universe.py` 是正确参考实现（两侧都解析到最后一个交易日，且空宇宙 fail-fast）。
- short_reversal 的 MA/MACD/RSI/ReturnN/MA20Slope 确实建立在 hfq 复权线上；chase_up/uptrend_pullback 的信号面板是复权源。
- 无硬编码成分股清单（无 `if symbol in <INDEX>` 之类），无跨组织数据泄漏。

**§4 微观结构与流动性**
- 跳空穿越止损在 chase_up / uptrend_pullback / cycle_price_action 中按开盘价成交（正确）；只有 short_reversal 相反。
- 同 bar SL/TP 最坏情形在**Phase-1 引擎**中正确实现为 SL 优先，且 `intraday_tiebreak != "sl_first"` 会 raise。
- 10% 量比上限在入场侧存在、按手取整、剩余部分取消且不排队，未动用的现金从未离开 `free_cash`（即部分成交的现金回退语义正确）。
- 做空侧存在明确的融券假设声明（`BORROW_ASSUMPTION`），长仓引擎不适用该条款。

**§5 统计严谨**
- `core/walkforward.py` 的 `walkforward_windows()` 强制 `train_end < test_start`，不可满足时 raise。
- `uptrend_pullback/wfv_eval.py` 要求显式 `--n-trials` 并逐候选评估，是仓库内 §5 的正确范式。
- `cycle_price_action/sweep_thresholds.py:33-38` 曾把回测窗口从 train 改为 test 并留了记录，其 Bonferroni / DSR 键名正确。
- `dna_stats/deflated.py` 的 DSR 与 Bonferroni 实现诚实，并把 `observed_sharpe` 先年化再比较。

**§6 架构与验证层**
- `uptrend_pullback` 的 golden 基线在测试内**重算**成交列表、缺 DB 时 `skip`（实测 3 skipped / 0 failed）——四引擎中唯一真正满足 §6 的实现。
- 除 `short_reversal/st_filter.py` 外，信号层无 DB/网络访问；`signals.compute_indicators` 是纯函数。
- `core/walkforward` 的 WFV 生成器本身正确（问题在于各 sweep 脚本绕开了它）。

**§7 产物卫生**
- 工作树内无任何被跟踪的运行产物：`git ls-files` 中不存在 `trades.csv` / `*_metrics.json` / 结果目录（仅 `cycle_price_action/results/.gitkeep`）。
- 各 `results/` 目录均被 `.gitignore` 覆盖（逐条用 `git check-ignore` 验证）。
- `README.md` 无业绩表；`docs/uptrend_pullback_preset_search.md` 是仓库内 §7 合规的范例（明确声明不含历史指标，数值一律留在 gitignore 的 results/ 下）。

---

## 6. 未确认线索（未确认线索 / 不是违规认定）

**证据包的 `could_not_verify` 为空（`[]`）**——不存在「验证者自己失败导致线索滞留」的条目。

但审计的批判层（critic）另指出 **6 个没有任何 cell 覆盖的面**。这些**不是违规认定**，只是「未审查到」的空白，需后续单独立项确认。

> **2026-10-15 更新:六个面已逐条查证**,见 **附七**。其中三条是可证实的真缺陷（§0 时区、§0 夹具播种、黑名单死路径）已修并配双向验证的守卫;一条（`render_top5` 工具）经查证后**审计表述过重**,真实分歧已修;一条（§5 归因）补上了报告级标注;**最重要的一条（raw/adj 语义前提）已用本机活库核验,§3 前提成立,三条相关发现无需重新推导**。下列六条保留原始表述,以便对照审计当时的口径。

1. **§0 时区条款无实现、无检查**：`tools/update_db_direct.py`（写 `raw_kline_daily` 的入口，无测试）用本机时区把日期与毫秒时间戳互转，同一 API 负载在不同机器上会落成不同的 bar 日期。
2. **§0 可复现性**：`requirements.txt` 只有版本范围、无 lockfile；`tests/conftest.py` 的合成库用 `hash(code)` 播种（受 PYTHONHASHSEED 影响），环境与夹具都不满足「同输入同输出」。
3. **§5 Attribution Mandate 从未被任何 cell 检查，且全库无实现 —— 已补齐(附三十四)**：`core/trade_schema.py`、`chase_up/backtest.py`、`cycle_price_action/metrics.py`、`tools/render_top5_presets_html.py:905` 都只报裸收益，无基准超额；`tests/` 中 `benchmark|excess` 零命中。
4. **`data/exclude_thscodes.txt` 在多数引擎中是死路径**：harness 点名了它，但 chase_up / uptrend_pullback / cycle_price_action 的所有调用点都不传 `exclude_path` 且无 `DEFAULT_EXCLUDE_PATH`；文件本身还含重复代码。short_reversal 侧有两个 LOW 发现，其中一个被验证者判为「静默空转」，另一个被判为「在默认 preset 上不可达」。
5. **raw/adj 语义的前提不可核（最重要）**：`v_daily` / `v_daily_qfq` / `v_daily_hfq` / `raw_kline_daily` 的 DDL 不在仓库；`sql/migrate_v_daily_dual.sql` 只是其消费方；`tests/conftest.py` 造的 `v_daily` 没有 adj/raw 列；`data/hiagent.db` 是 0 字节占位。**多个 §3 发现的载荷前提依赖这一条**：若生产库中 `v_daily` 实为复权价，则 `short_reversal` A 条件、cycle 指标域、公司行为三条需要重新推导。
6. **`tools/render_top5_presets_html.py`（1162 行，无测试）** 重新实现了两个引擎的指标与 A/B/C 判定，并带着自己的第三个 metrics 函数，与 §6 的单一实现要求冲突。

另附 1 条**被证伪**的线索（不作为违规）：`uptrend_pullback/backtrader_engine.py:170`「TP/SL 以绝对价而非相对百分比交给 replay」——验证者指出这些绝对价位是「相对百分比 × 该笔成交域入场价」推出的，且两阶段同域比较，规则要防的灾难情形在结构上不可能发生，故证伪。

---

## 7. 未能验证的事项与验证边界

**本地数据库缺失（关键局限）**：被审计快照内 `data/hiagent.db` 为 **0 字节占位文件**（`.gitignore` 第 40 行覆盖），因此**在快照内部无法重跑任何实盘回测**，无法端到端复现任何业绩或现金账结果。

这带来两层后果：

1. **部分验证者越过快照去跑机器本地库**（用户目录下的 `market.duckdb`）。该库未被纳入快照 pin，版本随时可能变化，因此这些复现**不能由快照自行重放**。本报告已把这两类结论分开陈述。
2. **静态不可判定项**：`v_daily` 等视图的 DDL 不在仓库（第 6 节第 5 条），所以「原始价/复权价」的确切语义无法从快照核实。这是上游前提，不是本次审计可以自行消解的。

**仅凭静态代码即可断言的结论（不依赖任何数据库）**：
- 全部 §2 现金账/NAV 表达式问题（`chase_up/portfolio.py:619-623`、`:463`；`cycle_price_action/portfolio.py:300-302`、`:179`；`short_reversal/replay_strategy_v3.py:820`、`:388`）。
- 全部 §3 域混用（`chase_up/portfolio.py:605/614`；`uptrend_pullback/portfolio.py:577`；`short_reversal/replay_strategy_v3.py:927/913`；`cycle_price_action/signals.py:87`）。
- 全部 §4 滑点/涨跌停/量比公式与分支顺序（`chase_up/backtest.py:145-146`、`portfolio.py:426-437`、`530-537`；`short_reversal/replay_strategy_v3.py:769-770`、`:646`；`cycle_price_action/backtrader_engine.py:168`、`portfolio.py:256-262`）。
- 全部 §6 守卫空转与 §7 文档卫生（`tests/test_reproducibility_audit.py:331`、`:352`；`tests/test_cycle_price_action_sha256_baseline.py:94`；`tests/test_cost_constants_single_source_4engine.py:265`；`tests/test_backtest_data_integrity.py:58`；`chase_up/presets.py:1049`）。

**需要本机数据库才能定量的结论（本报告中不作数量断言）**：
- 各引擎窗口内的事件频次（跳空触发、跌停封板数、停牌 bar、EOD 强平笔数）。
- 宇宙 PIT 与非 PIT 的差集规模（`cycle_price_action/data_feed.py:211`、`:163`）。
- §7 中 golden 被跟踪的具体数值、以及各 carve-out 的实测偏差幅度。
- 影响面的量级（例如双计对风险指标的放大倍数、滑点缺失的成本量级）。

**另一项可信度提示**：有一名验证者报告 `/tmp/hiagent-main` 在会话中途被并发改动（`uptrend_pullback/portfolio.py:612` 出现又消失的调试打印），其后所有动态验证改在自己的 `/tmp/audit_pristine` 副本上进行。这提示快照的只读性未被完全保证；本报告的结论以静态引述为准，关键行已在报告中逐条回读确认。

---

## 8. 修复优先级（建议顺序）

**P0 —— 会污染头条指标与现金账，先修**
1. `chase_up/portfolio.py:619-623`、`:463`：NAV/权益只加总现金与未实现盈亏。同步核对 `chase_up/main.py:83-90` 的产物口径，并按 §6 重新生成 golden、在 PR 中说明漂移。
2. `cycle_price_action/portfolio.py:300-302`、`:383-385`、`:179`：出场不得同时退回成本基础并计入全额卖出款。注意：`settle()` 目前无调用点，**只删 `release_margin` 会直接饿死引擎**，必须与「每 bar 调 `settle()`」一起改。
3. `short_reversal/replay_strategy_v3.py:820`：入场费必须真实从现金账扣除；补现金守恒断言。

**P1 —— 会让回测结论不成立的执行真实性问题**
4. `chase_up/backtrader_engine.py:187`：恢复 `raw_*` 列，或在缺列时 fail-fast。这条同时是 §0 可复现性问题（同 preset 同窗口两条入口给出相反结论）。
5. `short_reversal/_panel_loader.py:90`、`:93`：把窗口上下界真正下发到策略与 feed。
6. `cycle_price_action/data_feed.py:211`、`:163`：宇宙成员加因果上界与双侧listing 判定。
7. 全库滑点（§4）：在 core 定义唯一滑点策略，preset 显式声明，缺声明 fail-fast。
8. 涨跌停双向守卫：用 `core.dual_price.is_limit_up` / `is_limit_down` 补齐卖出/回补侧，并顺延到下一可成交 bar。

**P2 —— 账实一致性与可执行性**
9. `short_reversal/replay_strategy_v3.py:388`、`:636`、`:582`、`engine.py:61`：无条件冲刷 settle、加容量门与信心排序、`final_capital` 改用 NAV。
10. 公司行为事件源（四引擎）：接入 ex_date 事件表并加「NAV 跨事件 bar 连续」不变量测试。
11. 费率常量单源化：四引擎共 12 处重复定义全部改为 import；注意 `short_reversal/engine.py` 与 `BORROW_ASSUMPTION` 两处远端 main 已修，本地 rebase 后即可消解。
12. `cycle_price_action` 的入场记账与资金池：统一用 broker 成交价记账；容量约束改为单一资金池。

**P3 —— 验证层与统计严谨**
13. 修空转守卫（`tests/test_reproducibility_audit.py:331`/`:352`、`tests/test_cycle_price_action_sha256_baseline.py:94`、`tests/test_cost_constants_single_source_4engine.py:265`、`tests/test_chase_up_no_lookahead.py:642-656`、`tests/test_backtest_data_integrity.py:58`），并把 61 failed + 3 error 登记 owner 或修绿。
    → **2026-10-17 更正(附四十三)**:本条此前**只做了一部分** —— 该文件里的无断言 `pass` 当时**仍在**(扫描器也同时在同一文件里误报)。现已修:扫描器改按名字判定、四个用例统一为真断言,并以正/负对照双向验证。
      教训:修复计划里列了条目 ≠ 条目被修 —— 「账实不符」这是本审计第 6 次。
14. 补 `tests/golden/short_reversal_*_baseline.json`（先修守卫，否则加了基线也无人执行）。
    → **已完成(附三十九)**：`v50_slope`(28 笔) + `v58_mp_2`(58 笔)，守卫在测试内重算后比对；
      生成时连续两次重算一致才 pin。`test_reproducibility_audit` 里的登记用例随之自然通过。
15. §5：`dsr['p_value']` 键名错误、`n_trials` 累计口径、sweep 的 OOS 窗口（`uptrend_pullback/sweep_v33_long*.py`、`short_reversal/wf_v34_focused.py`、`chase_up/wf_sweep_all.py`）。
    → **已处理(见附十三)**:键名、`n_trials` 口径、DSR 分子/分母一致性、收益率当 Sharpe 均已修;
    **附三十二再补两处输入口径**:年化常量单源(引擎 243 / dna_stats 曾 252)、
    `n_returns` 不再硬编码(10 处写 252 → 来自本次运行的观测数);
    **2026-10-17(附四十)**:F/G/H/I/K 已实现,指标走 `indicators_bt` 的 pandas 对偶并**逐值对拍**
    (14 个指标全部在 rtol=1e-6 内一致),信号集端到端对拍扩到 11 个 preset ⇒ **可信 68/75**
    (余 7 = J 3 + breadth 1 + ensemble 3,均原理性不可向量化)。
    取舍如实记录:**未**把引擎指标层抽成纯函数(结果敏感的手术),而是『两份实现相邻 + 两级对拍』。
    **2026-10-16(附三十八)**:`scan_signals_fast` 的参数已改读声明(可信 1→35/75),**对拍已就位**
    (`tests/test_fast_scanner_matches_engine.py`:6 preset × 真引擎路径逐只比较);
    **仍未闭合**:F–K 的实现需要先把 backtrader 指标抽成纯函数(否则就是新增重复实现),继续登记。
    另:4 个脚本引用已删除的 preset(已登记 `KNOWN_DEAD_REFERENCES`)、以及原文点名的
    「窗口跨越已声明的 holdout」(需使用者确认 holdout 边界)。
16. 补 §5 Attribution Mandate 的实现（基准超额），这是目前完全空缺的一项。
    → **已实现(附三十四)**：基准 = 窗口 PIT 宇宙等权买入持有(实机库无指数数据，§5 允许
      index **or style basket**)，`benchmark_kind` 随产物发布；chase/uptrend/short_reversal
      均已接入，cycle 未改(另一 workstream 正在改该包，避免冲突)。

**P4 —— 产物卫生与低危加固**
17. §7：先修 `tests/_regen_chase_baselines.py:109`（否则清理后的数字会被再次写回），再清 `chase_up/presets.py`、`short_reversal/presets.py`、`tests/golden/*.json` 内嵌的业绩字段与选优叙述。
18. cash_walk 三池（四个 `main.py`）、`.gitignore` 增加文件名级全局模式、`chase_up/portfolio.py:172` 常量单源化、`short_reversal/universe.py:19`/`:73` 的黑名单与宇宙上界、`uptrend_pullback/backtrader_engine.py:399` 的 schema 一致性。
19. 6 个未覆盖面（第 6 节）立项确认，特别是 `tools/update_db_direct.py` 的时区处理与 `data/hiagent.db` 缺失导致的 raw/adj 前提不可核问题——后者是多个 §3 结论的共同前提，建议优先于其它 P4 项。
---

## 附:修复进展(分支 `fix/discipline-remediation`,基于 `b597d0c`)

本审计的 P0/P1 修复正在独立分支推进,**未合入、未 push**。提交与依据:

| 提交 | 内容 | 验证 |
|---|---|---|
| `d43aee7` | P0:权益/NAV 双计、raw 域建仓被复权价盯市、cycle 出场双记本金、short_reversal 入场费从不扣账、cash_walk 三池假账 | 实测单 bar 权益收益 107.70% → 9.99%;一轮往返 `total_cash` 1330 → 1030;全量测试失败集合与基线逐条一致(零回归) |
| `38c57aa` | `short_reversal` 显式窗口门 + 修复分叉 harness(即 §0.4) | 三个窗口不变量首次真正通过;窗口门对成交列表为 no-op |
| `35cb829` | `cycle_price_action` 宇宙:幸存者偏差(中途退市被剔除)+ 流动性均值无日期上界(未来函数) | `test_cycle_survivorship_bias.py` 4/4 通过(原 2 红);**宇宙成员 2990 → 2876:恢复 3 只窗口内退市标的,剔除 117 只「仅因窗口后成交额才达标」的标的** |
| `f561198` | `cycle_price_action` 遇停牌**中止整个回测**(§1 规定缺 bar 语义);区分停牌与数据缺口,保留 fail-fast | 原本无法完成的回测可越过原崩溃点继续 |
| `8a4f806` | §4/§6 滑点策略单源(`core.effective_slippage`);原 `atr_slippage` 被写出却**无任何引擎调用** | 192 点网格穷举等价(零行为变更);新增守卫经反证测试非空转 |
| `d77460e` | `chase_up` Phase-2 补回两处 §4 守卫(涨停入场跳过、同 bar SL-first),并把 Phase-1 内联的涨跌停谓词改为 core 单源 | 三处既有红用例转绿;Phase-2 成交列表 34 笔、字段 0 差异(**no-op**) |
| `10e8a2f` | 修补前述提交引入的 **4 处回归**(见下) | 4 条转绿,失败集合无新增 |
| `dd77584` | `chase_up` 出场侧跌停 no-fill 守卫 | 新增用例含反向对照;Phase-1 成交列表 34 笔、0 差异(no-op) |
| `c3dafa7` | `uptrend_pullback` 同守卫 + 入场谓词单源 + **§6 重刷 3 个基线**(幻影止损,见附二) | 基线与逐笔归因如上;sha256 重算两次一致 |
| `a59839d` | `cycle_price_action`:`time` 分支不再提交(调用方/被调方契约矛盾,`max_hold` 曾是死代码)+ `can_fill` 前置检查(修掉停牌修复引出的顺序问题) | 反事实 A/B 量化(见附三);3 个月回测由**崩溃**变为**跑通** |
| `2fade0a` | `short_reversal` 回补侧涨停守卫(四引擎镜像守卫补齐) | 新增用例含反向对照(+6% 未封板仍应止损) |
| `9a1d416` | §2/§4/§6 费率常量单源化(含类属性遮蔽、内联字面量、`BORROW_RATE_ANNUAL`);两个「只比对数值」的守卫改为断言**单源**本身 | 数值逐一相同;chase_up 成交列表逐字节一致(**零漂移**);新守卫经反证对四引擎旧代码全部命中 |
| `091e512` | §3 事件化公司行为(chase_up):分红入 `Free_Cash`、送股原子调量/重定成本价;`EQUITY_COLS` 增 `cum_dividends` | 守恒恒等式**精确闭合 0.000000**;窗口内分红 ¥4,340;3 条新守卫 |
| `545d7fc` / `b7cf3bb` | 公司行为逻辑提到 `core.corporate_actions` 单源;接入 `uptrend_pullback`;把"子串启发式"handler 守卫改为 AST(导入+调用) | uptrend 为 **no-op**(独立核算:窗口内仅 1 笔跨越除权日且**在除权日入场** → 不享有);修掉一处我自己引入的回归 |
| `c97515f` | §3 公司行为接入 `short_reversal`(**做空付出分红**,符号由引擎取反;从 locked_margin 扣出并记账) | 新增 2 条守卫;修绿 `test_corporate_actions_gap[short_reversal]` |
| `26e781d` | §3 公司行为接入 `cycle_price_action`(四引擎全齐) | 4 条新守卫;顺手抓到该文件**没有 `logger`**,配股告警路径会 `NameError` |
| `f7cd63f` | **根因修复**:`_table_exists` 只查表不查视图 → `v_daily_hfq` 探测恒 False → cycle 的 `adj_close` 从未送达信号层 | 3 个月窗口:10 笔成交字段变化,Σpnl 813,569 → **1,011,092**(+197,524);典型一笔 30% 送股所致"−253,403 → −48,320" |
| `7ce982e` / `61f5f23` | **P1-B2 完成**:滑点标定值必须显式声明,`resolve_atr_slip_scale` 缺声明 fail-fast;100 个 preset + cycle 显式写入 `SLIP_NONE_ACKNOWLEDGED`;cycle broker 首次真正收到该值 | 100 个 preset 逐字段核验(除新增键外零差异);chase_up Phase-1 **逐字节零漂移**;端到端 fail-fast 已验证;11 条新守卫 |
| `4acfc2e` | §5 walk-forward DSR 的 `n_trials` 由**窗口数**改为**配置数**(消费 preset 的 `n_comparisons`);`n_returns` 由硬编码 252 改为 126 | 逐文件分类 25 处:7 处网格本就正确(未动)、15 处 WFD 修正;32 条新守卫;**未跑完整 wf 回测**(仅编译+导入+取值验证) |
| `5c731cd` | §7 清除内嵌绩效声明(13 个 golden 的 `metrics`/`vs_*` 块、回写脚本、57 行 preset 注释、4 处 docstring/注释、v21 的 `pinned` 块**保留负面证据**);并把 2 个空转守卫改为可证伪 | 22+75+3 个 preset 与 HEAD **逐字段一致**;终检全库清洁;Layer 5 由"存储数字 + 30% 容差"改为**精确恒等式**并转绿 |
| `e063c43`…`eea8cb3` | **§6 `chase_up` 金标准守卫修复**:8 个用例改为"一律重跑、无 DB 则 skip";重刷 13 个基线;regen 脚本修掉硬编码绝对路径与产物写入 | **8/8 转绿**;关键发现:**旧 pin 相对 main 早已陈旧**(v5/v8/v19 旧 pin 107/82/33 vs main 重跑 38/27/12,而整改后重跑与 main 完全一致) |
| `008ea11` | §5 归因机制(`dna_stats/attribution.py`:复利区间收益/超额/beta,fail-fast 而非猜测)+ 修 9 处 `dsr['p_value']` **活 KeyError** | 判据为 **beta 调整后 alpha**(原始超额无法区分技术与杠杆:纯 2× beta 的原始超额 +1.30% 全来自复利,而 beta 调整后恒为 0);**基准数据缺口已显式登记**(库中无任何指数) |
| `5efcfbb` | §6 `cycle` 涨停守卫移入**执行层**(另三引擎本就在那);消除**两个测试文件对归属层的互相矛盾**;引擎改为只传 `prev_close` | `test_cycle_limit_up_guard` 4 条 + cross-engine 2 条转绿;`test_round30` 的两条结构断言改为**钉住调用点**(守卫可达) |
| `548d8a0` | §0 静默 except 扫描器:口径改为「既不记录也不抛出」;修其**漏检 `return None`** 的缺陷;守卫改为**灵敏度测试**(植入三种裸处理器必须命中,两种有记录处理器必须不命中) | 2 条转绿;顺带纠正 `scan_signals.py`(它是 `raise`,本就不该算静默) |
| `b8c1539` | **§0/§2/§3/§4 preset 声明到达引擎**:11 个键、180 处"声明了却无人读取"接通(权重/仓位比例/参与率/执行价源);新增 `core/preset_contract.py` 单源契约;修正扫描器 `.get()` 盲区(它曾把**真实消费**误报为丢弃);把已失效的历史缺口元用例换成栽桩灵敏度,并新增**行为**守卫 | **5 条 RED→GREEN,新增失败 0**(27→22 failed / 915→934 passed,逐条 diff);`chase_up` golden 33 项全绿 = 接通声明**未移动任何历史数字** |
| `e6c1642` | **§4 cycle 成交量上限改用规范助手**(唯一自写 round-to-0 公式的引擎;薄量 bar 上守卫被跳过 → 幻影成交);清掉 10 条「用红灯表达待办」的用例 | 5 条由失败转为 §6 合规的 skip(产物边界);5 条断言**能力不存在/陈旧**的用例翻正;**新增失败 0** |
| `4cbc66c` | **§0 cycle 的第一条成交列表基线**(此前一条都没有):`_regen_cycle_baseline.py` 固化 + 重跑比对;默认 skip(单次重跑约 6.5 分钟),`DNA_RUN_SLOW_GOLDENS=1` 开启 | 两方向验证:篡改 pin → FAIL(打印实际哈希=原 pin,证明两侧重算一致);还原 → PASS。两次重跑基线文件**逐字节相同** |
| `8becfa2` | 清掉剩余全部红灯:§2 short_reversal `nav_gate_ratio` 静默默认(75/75 未声明)接通 + 参数更名;§3/§6 cycle 入场价改经 `extract_execution_bar`;§4 补全 65 个 preset 合规头(62 个由声明值生成);另修 8 条**判据本身错**的断言 | **12→0 failed / 941→954 passed**;逐条先判"代码错还是断言错"再动 |
| `1e2bedd` | **查证审计自认「未审查」的六个面**:§0 时区(`update_db_direct.py` 按本机时区转换 → 同一负载落成不同 bar 日期)、§0 夹具 `hash()` 播种(逐进程随机 → 每次价格不同)、黑名单**未被跟踪文件从未加载**(默认路径指向不存在的文件 + docstring 给错原因 + 静默空集);并**用本机活库核验掉审计最重的未知**(raw/adj 前提) | 三处守卫**双向验证**(旧实现下必然失败);黑名单改动经模式门控,对 **73/75 出厂 preset 行为中性** |
| `834cfc4` | §5 归因:让「未归因」标注随**每一份报告**一起走(写在唯一规范渲染点 `core/trade_report.py`);§6 展示工具 CAGR 口径统一为**交易日**(此前日历日 → 同一回测两个 CAGR) | 已双向验证;并给此前**零测试**的 1162 行工具补上首道守卫 |
| `72633e8` | **新发现(不在原发现集内)**:cycle 的 `total_pnl` 缺分母 —— 引擎按**每股一个独立账户**跑,合计的分母是 `n_accounts × 每账户资金`(实测 **29.5 亿**),而另外三引擎是单个 100 万组合。`cagr/max_dd/sharpe` 已诚实返回 `None`,唯独 `total_pnl` 无标注 | 口径随产物发布(必填参数 → 忘记标注即在调用点失败);接线守卫验证 `n_accounts == len(universe)`;附八 |
| `512b06e` | **新发现(不在原发现集内)**:全胜窗口下 `profit_factor=inf` → `json.dumps` 写出 `Infinity`,而那不是合法 JSON。Python 的 `json.loads` 宽松接受,故自家 round-trip 读得回来、缺陷长期隐形;JS/Go/Rust/jq 一律拒读 | 分母为 0 时返回 `None`(与 `max_dd=None` 同口径);四个引擎 **8 个写出点**加 `allow_nan=False`(让将来的非有限值在写出时失败);守卫双向验证;附九 |
| `998447a` | **新发现(不在原发现集内)**:年化口径**三处不同** —— 两引擎 `交易日/243`(且同值各写一份)、`short_reversal` `日历日/365`、`dna_stats` 默认 `252`。实测同一窗口同一 10% 收益,CAGR 差 **8%~26%**(连整年窗口都差 8%) | 新增 `core.trade_schema.TRADING_DAYS_PER_YEAR` 单源;两引擎零漂移接入,short_reversal 切交易日口径(**有意漂移,量级已记**);`n_trading_days` 写进产物;`dna_stats` 的 252 属 §5 统计口径另行登记;附十 |
| `048bedf` | **新发现(不在原发现集内)**:`sharpe` 在三个引擎里**不是同一个量** —— 两引擎是日收益年化 Sharpe,`short_reversal` 是逐笔 net 的交易级比率。而 sweep 脚本**按它排序**,跨引擎比较无意义,键名却看不出来 | 四个发布点加 `sharpe_kind`;守卫要求两类字符串真的不同 + 凡发布 `sharpe` 必发布 `sharpe_kind`;附十一 |
| (本轮) | **新发现(不在原发现集内)**:把库拿掉再跑 —— **fresh clone 拿到的是红的套件**。无库时 15 failed + 5 errors,0 字节占位时 8 failed + 3 errors,合计 **31 个**用例违反 §6「无库必须 skip,不得 error」 | 单一共享助手 `require_market_db()` / `market_db_available()`(检查**存在且非空** —— 原实现只查存在性,恰好让 0 字节占位漏过);两种缺库形状均跑成 **0 failed / 0 errors**;附十二 |
| `5a413d8` | **§5 的执行层在 25 个研究脚本里**(不在引擎里):(a) 14 个 WF 脚本的 DSR **分子是 max(窗口)、分母是配置数** —— 两次不同的选择,窗口那层没被折减;(b) `chase_up/wf_sweep_all.py` 把**收益率**当 Sharpe 传进 DSR(12% 当 0.12 → p=0.966,而真 Sharpe=1.20 → p=0.772);(c) 4 个脚本引用**已删除**的 preset,启动即退出 | (a) 分子改跨窗口均值 + **数值验证**(断言收到 0.9 而非 1.9);(b) 用现成的 `mean_sharpe` 列;(c) **不改名字**(无重命名映射可推断 = 编造记录),改**登记债务** + 登记表必须等于实际集合;11 条守卫均双向验证;附十三 |
| `a714e64` | **同族缺陷的另一半**:`cycle_price_action/sweep_thresholds.py` 在**展平网格**(阈值×窗口)上取 max,却按**阈值个数**折减 —— 且它**自己打印的表**(逐阈值均值)与它实际传给 DSR 的数**不是同一个**。另:`cycle` 的 `n_comparisons=1` 理由写作「无 sweep」,而其 `sweep_thresholds.py` 的**默认候选恰好包含出厂的 threshold=2.0** | 分子改为「阈值均值的最大」+ **数值验证**(0.9 而非 1.0);注释更正;`n_comparisons` 的**真实值交还给使用者**(无迭代记录即无法据实填写,填 3 是伪精确);新增"max 取几项/n_trials 数几项"守卫(只罚不匹配的那种组合);附十三 §4-6 |
| `9992f6e` | **`tools/` 面查完(此前 2/5)**:三处干净(调规范引擎、无硬编码路径、只写 gitignored 目录);但 `run_all_backtests_html.py`(710 行零测试)**把 cycle 的「无法定义」换成 0.0 并带入跨策略排名**、**按 Sharpe 跨引擎排名**(附十一那条)、以及**守卫实测发现的 `width:nan%` 泄漏进 CSS** | 保持 `None`(渲染为「—」且退出排名);`sharpe_kind` 随产物发布 + 写明不可比;加 finite 保护;该工具补 **8 条**守卫(双向验证);并**更正我自己上一轮对 tools 的假阳性死 preset 扫描**;附十四 |
| `e081a48` | **`dna_data/` 面查完(此前 0/3)**:两个 loader 的 SQL 有因果上界 ✓、无 §1 禁用函数 ✓;但 `dual_price_resolver.execution_open` 的回退链是 `("raw_open","adj_open","open")` —— **执行价缺失时静默变成复权价**,与**同文件两个兄弟函数**注释里写明的「skip the OTHER family」自相矛盾。另:**§1 守卫的 `SCAN_DIRS` 漏掉了 `dna_data` 与 `tools`** —— 而 `dna_data` 是 panel 的生产者 | 回退链改 `("open",)`(与 `execution_close` 对称),缺 raw 即 fail-fast;扫描面补上两个目录(`sql/` 因 AST 限制另行登记);两组守卫双向验证(植入 `bfill` / 还原旧回退链都正确失败);附十五 |
| `1f30818` | **修复审计 §3.2 HIGH**:`uptrend_pullback/iter_reverse.py` 做默认 **100 次** Monte-Carlo 搜索、排完 TOP-K,却**无 DSR / Bonferroni / n_trials** —— 违反 §5 Penalty Metrics;而**姊妹脚本 `sweep_v33_long.py` 本来就有**。另纠正审计表述:它用的是 22 个滚动窗口,不是"同一窗口" | 量化**已做过的选择**(`observed`=被选中配置的 Sharpe;`n_trials`=**实际评分**的配置数;`n_returns`=21/月,取自仓库既有 126/6 口径)+ 显式 **in-sample** 警告;6 条守卫,**含一条把我自己写空转的第一版守卫修好**的过程;附十六 |
| `a3c1f43` | **`chase_up/sweep.py` / `sweep_all.py`**:在**单一窗口**上选优并报 DSR,却**不声明这是样本内选择**(而仓库已有滚动窗口版本 `wf_sweep_all.py`,读者没理由当它是 OOS)。核对确认两处**不是**缺陷:`max/n_trials` 成对 ✓、`n_returns=252` 对 12 个月窗口 = `21×12` ✓ | 两脚本各加 in-sample 声明并**指名**滚动窗口版本;守卫含"**max 与 n_trials 必须成对**"的回归项 + 行为项(桩化后断言警示真的被打印,产物写 `tmp_path`);双向验证;附十七 |
| `88c7643` | **把登记债务往下推一格**:`git log -S` 查清 4 个失效脚本的 preset 是**被裁剪**(`4b7eab0` 减 212/增 66 行)而**非改名** —— 故无可安全回指的替代名,回指即编造记录;**保留**(其中 `v41_*` 本就是过拟合失败案例 = 负面证据) | 把由来写进脚本**自身失败信息**(裁剪提交 + 登记位置),下一个人不必重查 git 史;守卫改为**执行脚本并检查输出**;**并修掉我自己又一条空转守卫**(断言 `in src` 被注释满足);附十八 |
| `714ace3` | **§3.3 复核第一条**:`short_reversal` 的 cash_walk 把三池写死为 0,理由是"**等 H5.1**"——**而三池早已落地**("登记逾期":记录所依赖的前提消失了,而注释从诚实延期变成误导辩护)。另:我第一版把 NAV 写成含 `locked_margin`,**正是审计 P0-1 的双计** —— 引用了 `portfolio_nav` 却**没读它** | 逐 bar 行补三池 + 如实落盘 + **缺字段 fail-fast**;NAV 改为**调用** `portfolio_nav`(不内联公式);3 条守卫双向验证(NAV 双计与写死 0 两个变体都正确失败);附十九 |
| `fa5801a` | **§3.3「常量重复与口径不一」清完**:`chase_up/replay_strategy.py` 自己写了一份 `prev_close_limit=0.098`(注释称"与 portfolio 一致"——注释保证不了任何事);核对中发现更实质的:四引擎在这条阈值上**2 对 2 分歧**(0.098 vs 0.095),chase_up 自注为"历史 override" | 同值不同源 **已修**(import 常量,行为中性);**分歧不改**——统一会改变 ch/u 的成交列表(需重刷 golden),属结果变更;守卫刻意**不**要求两侧相等,只要求分歧**被看见**;附十九 §3 |
| `bc453ee` | **§3.3「量比 fail-open」复核确认成立**:四引擎把量比约束挂在 `if bar_vol > 0` 上 → **零成交 bar 上订单不限量**。而 helper 对 `bar_vol<=0` **本就返回 0**,契约还有测试钉着——**规则存在 ≠ 规则被应用**,缺的是调用点遵从。实测 `v_daily` 1036 万行中 `volume<=0`/NULL **均为 0 行** → **潜在**缺陷(故一直未被发现) | 零成交走 helper 得 0 → 由各引擎既有"过小即拒"分支如实拒单;None/NaN 与"零成交"在代码里明确分开(helper 也不能吃 NaN);10 条守卫,**含把我自己第一版宽正则误伤"除法保护"修好**的过程;附二十 |
| `5789f72` | **§3.3 的 LOW 三清**:①`.gitignore` 只忽略 `results/` **目录**,于是散落的 `trades.csv` / `metrics.json` **仍可提交** —— §7 那条要求此前**只是写在文档里**;②「恒真断言」早已修(并核对另 5 条区间断言为**真**不变量,不误报);③「WFV 单 asof」核对后**不是缺陷**(用窗口 0 的宇宙 = 更**保守**的一侧,非前视,且已文档化) | 补 9 类**文件名级**全局模式并逐条核对不误伤已跟踪文件;守卫用 `git check-ignore` 断言"在仓库根也被忽略"(断言的是**被执行**,不是**被写下**);**新守卫当场抓出我自己漏的裸 `metrics.json`**;附二十一 |
| `d80e7dd` | **§3.2 HIGH 复核**:`final_capital` 用 `total_cash`(**不含**期末未平仓浮盈),而 `equity_curve` 末行 `equity` 用 `nav`(**含**)—— **同一次回测两个互相打架的"期末权益"**;`total_yield`/`cagr` 都据此前推 → 期末持仓时收益率即错。同族的另一条(`settle()` 只冲刷正值)**经逐行核对不成立** | `stop()` 增写 `final_nav=_nav()` + 缺即 fail-fast;空窗口边角在 holder 初始化时给正确的 `final_nav=INITIAL_CAPITAL`;4 条守卫(**判别性**:构造 cash≠nav 断言取 nav);双向验证;**并标注为一次结果变更**(未量化,附二十三) |

**测试层净效果**(失败集合逐条 `diff`,非仅比数量):

| | 基线 `b597d0c` | 当前 `10e8a2f` |
|---|---|---|
| failed | 54 | **48** |
| passed | 796 | **827** |
| errors | 3 | **0** |
| 新增失败 | — | **0** |

9 条既有红用例转为绿;新增 22 条守卫用例。`3 errors` 归零即 §0.4 所述的 harness 修复。

**过程中发现的自身回归(已修,记录在案)**:`d77460e` 之后失败数 57 → 52,看似改善,但逐条 diff 显示**修好 9 条、弄坏 4 条** —— 数量相同完全掩盖了问题。4 处分别为:`has_any_bar` 新查询缺 `ORDER BY`(违反 §1 可复现性纪律);两个 cycle 端到端 fixture 在因果上界下只剩 ~42 个交易日、达不到流动性门的 `lookback=60` 而宇宙为空(经查是 **fixture 未满足该门既有的前置条件**,补足 pre-window 历史后原样通过);以及一条 trace 侧的 min-commission 守卫扫描了已不再承载该逻辑的位置。**教训:回归判据必须是失败集合的逐条 diff,不是失败计数。**

**已知的漂移(§6)**:P0 使 `short_reversal` 成交列表 50 → 51 笔(引擎过去从不支付入场佣金,现在真实扣账)。这是正确性驱动的漂移;该引擎**没有任何 golden 基线**可供重生成(其唯一相关复现性用例长期空转),故此前无人报警 —— 补基线仍是未结事项。

**涨跌停镜像守卫(P1-8/P1-9)已完成**:chase_up / uptrend_pullback 出场跌停、short_reversal 回补涨停、cycle_price_action 出场跌停 —— 四处均配反向对照用例。

**公司行为(P2-10)**:**四个引擎已全部接入**同一 `core` 实现(做空为**付出**,符号由引擎决定;统一"除权日当天建仓不享有"的权益归属规则)。

**P1 已全部完成**(窗口边界、宇宙因果性与幸存者偏差、停牌语义、滑点单源与显式声明、涨跌停四引擎镜像守卫)。

**仍未处理(按 §8 顺序)**:全套件 0 failed。下列为**已登记**的未结事项(逐条见附六/附八/附九末尾):

1. **§5 基准归因**(数据缺口):本地行情库无任何指数序列,归因不可计算;取数需联网写库、选哪个基准属研究决策。机制与"未归因"标注均已就位。
2. **§4 滑点的实质**:100 个 preset 仍是 `SLIP_NONE_ACKNOWLEDGED`(=0.0)。换成真实标定值会改变每一个成交价,属研究决策,且按 §5 须计入 `n_trials`。
3. **§0 依赖锁定**:`requirements.txt` 只有版本范围、无 lockfile。本机为 conda 环境,`pip freeze` 会产出**误导性**锁定,故不代做 —— 建议用 uv / pip-tools 在指定 Python 下生成。
3b. **§5 统计口径**:`dna_stats` 的 `trading_days_per_year` 默认 `252`,而引擎侧单源为 `243`(A 股)。改动它会影响 DSR / Bonferroni 的收缩量、使既往比较失效 —— 属统计口径变更,需使用者拍板(附十)。
3c. **§5 迭代数**:`cycle_price_action/PRESET_V1` 的 `n_comparisons=1` 与仓库自身矛盾(其 sweep 的默认候选含出厂的 `threshold=2.0`)—— **需使用者提供迭代记录**才能据实填写;已登记于 `tests/...::KNOWN_UNRECORDED_TRIAL_COUNTS`(附十三 §5)。这是本轮唯一一处我明确交还给使用者的**数值**。
4. **§7 产物 writer**:**更正(附三十七)** —— 该说法不成立:四个 `main.py` 里都有 `_write_equity_curve`。真实缺口是**接线**:`short_reversal` 的 metrics 此前不带 `equity_curve` 键(writer 恒不执行,已修);`cycle_price_action` 的 writer **无调用点**(已登记并由守卫钉住)。注:`cycle` 的 `cagr/sharpe/max_dd` 返回 `None` 是**诚实**的"横截面无法定义",不是缺口。
5. **§6 展示层重复**:`tools/render_top5_presets_html.py` 重述逐 bar 指标与 A/B/C 文案(回测本身调用真引擎);消解需引擎暴露逐 bar 指标序列,属重构。
6. **"有实现、无消费者"的库函数**:`tail_objective.tail_stats`(测试外无调用点)与 `render_top5` 同类;建议统一清理而非逐个顺手改。
6b. **§1 扫描器的覆盖面**:`sql/` 未被扫(AstScanner 是 Python AST 实现,SQL 视图/迁移需另一套检查)。当前 `sql/` 只有 `migrate_v_daily_dual.sql`,且本机活库的视图定义已人工核验过(附七);但**没有任何自动检查**防它将来被改坏。
7. **§3 公司行为**:配股/缩股未建模(全库 1 例),`apply_corporate_action` 已显式告警。
7b. **§4 滑点侧的"未知成交量"**:本轮修完**下单量**侧的零成交 fail-open 后,同族还剩一处落在**滑点**侧 —— `if bar_vol > 0: participation = ... else: 0.0`,即成交量未知时 **ATR 滑点被静默置零**(乐观方向)。production 面板必有 volume 列(`v_daily` 无 NULL),故当前不可达;要改须先定"无列"与"零成交"在滑点侧的语义 —— 登记,不顺手改(附二十末)。
7c. **§6 信号层的 IO**:`short_reversal/st_filter.py` 在声明为纯信号层的路径上发子进程(已文档化、调用量小);需把名称解析移到控制面并缓存 —— 属重构。
7d. **§6 条件被复制实现(漂移风险)**:`short_reversal/scan_signals_fast.py` 用 pandas 重算引擎的 5 条件(文件头已**主动声明**并点名 `Phase3V3Strategy._all_conditions`,动机是"秒级"快扫)。风险不在重复本身,而在**漂移**:引擎改了条件、扫描器没改 → 使用者据以挑票的候选名单与引擎实际评估的名单不一致。**推荐次序**:先把 5 条件抽成**纯函数**由两处共用(现在 `_all_conditions(self, d)` 依赖策略实例状态,不可独立调用),再补"两处实现必须给同一结论"的**对拍守卫**(附二十二)。
8. ~~§7 源码内嵌业绩数字清理~~ → **已完成(`5c731cd`)**;~~`chase_up` 金标准基线仍红~~ → **已修复(`e063c43`)**;~~cycle 无成交列表基线~~ → **已补(`4cbc66c`)**;~~审计自认的六个未覆盖面~~ → **已查证(附七)**。

**当前测试状态**(截至 `d80e7dd`)——**三种条件都跑过**(§6 的验收条件就是 fresh clone 的条件):

| 条件 | 结果 |
|---|---|
| 有本机行情库 | 1074 passed / 30 skipped / **0 failed** |
| 无库(路径不存在) | 1030 passed / 74 skipped / **0 failed / 0 errors** |
| 无库(0 字节占位) | 1030 passed / 74 skipped / **0 failed / 0 errors** |

(注:套件耗时 ~21 分钟 —— 其中新增的行为型守卫会起子进程跑失效脚本、并桩化若干研究
脚本以验"警示真的被打印"。属可接受的代价,但若将来要压缩,优先看这些。)

基线 `b597d0c` 为 failed 54 / passed 796 / errors 3。改动全程逐条 diff 失败集合,**新增失败 0**。
30 条有库 skip = 22 条既有的 + 8 条本轮登记(产物边界 7 + cycle 慢 golden 1),全部带
**点名缺口的** skip 文本,无静默跳过。剩余事项见 §8 与附六末尾。

**修复带来的结果变化(不得按「改善」叙述)**:每处修复都会改变结果,方向不一。

- P0:short_reversal 成交 50→51 笔。
- 幻影止损:uptrend v19/v20/v21 基线重刷,**数字变差**(那是真实数字)。
- cycle `max_hold` 复活:持有期均值 4.80→6.19 天。
- 公司行为(chase_up,`chase_v1_atr_tp4_sl1`):分红入账 **+¥4,340**,`init + Σnet_pnl` 由 840,306(无分红时二者相等)→ 823,595,**期末权益(含分红)= 827,935**。

  ⚠️ 该案例曾在本报告中把 823,595 误标为「期末权益」—— 那是 `init + Σnet_pnl` 口径。分红是独立于逐笔 P&L 的现金流,两者在有分红后不再相等;correct 口径的权益是 827,935。

**净值口径的教训**:`init + Σnet_pnl` 只在「无分红」时等于权益。任何以它为权益替代品的比较,在引入分红后会静默偏差一个分红总额 —— 这正是本仓库反复出现的"两套口径"问题。

---

## 附二:修复中最有分量的一条发现 —— 幻影止损

「卖方跌停 no-fill 守卫」(P1-9)落地时,uptrend_pullback 的金标准基线发生了可归因的漂移,归因结果说明**修复前的回测系统性低报了亏损**:

| 日期 | `603272.SH` raw_open | 相对前收盘 | 是否封板 |
|---|---|---|---|
| 2026-04-20 | 27.54 | **−10.00%** | **封板** ← 旧代码在此"止损成交" |
| 2026-04-21 | 24.79 | −9.99% | **封板** |
| 2026-04-22 | 22.31 | −10.00% | **封板** |
| 2026-04-23 | 21.08 | −5.51% | 可成交 ← 修复后在此出场 |

旧代码在一个**开盘即跌停封板、根本没有卖方能成交**的 bar 上,声称按 27.54 完成了止损。该股随后又连封两个跌停日。修复后持有穿越三个封板日、于 04-23 以 21.08 出场 —— 这一笔 `gross_pnl` 由 **−92,380 变为 −284,888**。基线行数 v19 105→98、v21 57→68,其余差异均为资本被多占用三日引发的连锁(§6 要求的漂移归因已写入各 golden 文件的 `repinned` 块)。

**含义**:受影响引擎(长仓出场侧)此前的绩效被**幻影出场流动性**美化 —— 这比"四舍五入偏差"严重得多,属于 §3 Reality Mapping 与 §4 的直接违反。修复后的数字更差,但是真实的。

**顺带记录一次方法教训**:我第一次归因时对前后两棵树都报出"出场 bar 封板数 = 0",那是错的 —— 我统计的是**结果**成交的出场 bar,而守卫恰恰把出场**推迟**掉了,受影响的 bar 根本不会出现在结果里;此外成交日期字符串是 `2026-04-20 00:00:00`,与面板的 `%Y-%m-%d` 永不匹配,匹配静默全空。**一个"什么都没匹配到"的检查会给出一个看起来干净的错误答案。**

---

## 附三:`cycle_price_action` 的 `max_hold` 曾是死代码(契约矛盾)

审计 B6/V8 的落地与量化。

**缺陷**:`Portfolio.try_exit_with_intraday_check` 是"检查并出场"的助手,但它在**所有**分支(含 `reason == "time"`)都提交成交 —— 写 `closed_trades`、记现金、清 `self._pos`。而调用方明确只在 `reason in ("SL","TP")` 时重置状态,并注释 "reason == 'time' → fall through to max_hold check below"。于是:

- 持仓在**第一根未触发 SL/TP 的 bar** 就以收盘价被强平(入场后一根 bar);
- 调用方的 `max_hold` 分支**不可达**(其 `_pos is not None` 前提已为假),而 `max_hold` 是每个 cycle preset 都声明的参数;
- `_entry_day` 与实际持仓状态不一致。

修法:把提交动作限定在真正触发的分支,`time` 只返回判定;时间出场由调用方的 `max_hold` 分支经 `try_exit()` 完成。

**量化**:由于**任何修复前的树都无法跑完回测**(见附四),不存在可比的前驱,故采用**反事实对照** —— 在已修树上还原 `time` 提交行为,同 DB、同 preset、窗口 2026-04-01..2026-06-30(3 个月子窗口;整年 cycle 回测因引擎逐笔新建 DB 连接而过慢,该问题审计另有记录):

| | 反事实(`time` 提交) | 修复后 |
|---|---|---|
| 成交笔数 | 2892 | 2844 |
| `hold_days` 均值 / 中位 | 4.80 / 4.0 | **6.19 / 7.0** |
| `hold_days == 2` 占比 | **869 笔(30%)** | 258 笔 |
| Σpnl | 2,650,546 | **813,569** |

`hold_days == 2` 的尖峰正是该缺陷的签名(入场日 + 1 = 2 个日历日)。**这是量级差异,不是舍入差异** —— 意味着 `cycle_price_action` 此前报告的结果,对应的是一个实际只持有一根 bar 的策略。

---

## 附四:被自己的修复引出的顺序缺陷(已修,记录在案)

把 `submit_buy` 改成"停牌返回 `None`"之后,`cycle_price_action` 暴露出一处既有的顺序问题:

```
RuntimeError: backtest failed for 000639.SZ: cannot sell more than held
```

**成因**:入场分支先调 `try_enter()`(**无条件**在组合账本建仓),再调 `submit_buy()`。停牌时 `submit_buy` 无成交,但组合已经有仓位、broker 的 `_open_positions` 却没有 —— 两套账本从此不一致,后续 `submit_sell()` 便抛 "cannot sell more than held"。

**修法**:新增 `ReplayBroker.can_fill(thscode, decision_date)`,入场前**先确认次根 bar 可成交再建仓**;若 `can_fill` 通过而 `submit_buy` 仍无成交(真正的矛盾状态),按 §0 fail-fast 抛错,不静默留下一个卖不掉的仓位。数据缺口仍由 `_open_price` fail-fast,不受影响。

**验证**:同一 3 个月窗口,修复前**崩溃**、修复后**跑通**(universe=2953,trades=2844)。

---

## 附五:被声明却无人读取的 preset 键(元缺口,已修)

§0 的 Pessimistic Default 说"声明的承诺必须被强制"。本仓库有 **11 个不同的键、180 处声明**违反了这一条 —— 声明写在那里,而引擎从不读取它,于是缺口靠沉默存在:没有报错、没有日志、没有断言。

三种形态,机制各不相同:

| 形态 | 例子 | 为什么没人发现 |
|---|---|---|
| **装饰性声明** | `cycle_price_action` 的 `weight_kline/weight_cycle/weight_calendar` | 同样的 (1.0, 0.7, 0.5) 被硬编码成 `signals.fuse_scores` 的**默认参数**。预设与代码看起来完全一致 —— 改预设什么都不会发生,而回测仍"正常"跑出结果。 |
| **结构性替代** | `short_reversal` 的 `position_sizing` | 真正决定走集成路径的是 `"ensemble_substrategies" in cfg`。声明与开关是**两个**东西,不一致时无人体检。 |
| **无处可去** | `chase_up` 的 `position_fraction`;`cycle` 的 `max_positions` / `max_volume_participation` / `price_source_for_execution` | 引擎结构上只用另一个键(`position_sizing`),或用同名类常量(`MAX_VOL_PARTICIPATION`)——声明纯属装饰。 |

**为什么"同值硬编码"是最坏的一种**:它让"声明生效"与"声明无效"在**输出上无法区分**。任何以结果为判据的检查都为绿,只有以**来源**为判据的检查才能发现。

### 审计方法本身的假阳性——比假阴性更毒

源文本扫描器只认 `["key"]` / `key=` / `.key`,**不认 `.get("key")`**。于是 `short_reversal/engine.py:148` 的 `cfg.get("ensemble_weight", 1.0/n)`(真实消费)被报成"从未被读"。

误报比漏报更毒:漏报只是没抓到,误报会**诱导人去"修"一个根本没坏的地方**。修法是把 `.get(...)` 与 dict 字面量一并纳入模式。

同时,`test_audit_method_finds_intraday_tiebreak_in_cycle` 钉的是 Tick 30/31 的**历史**缺口。该缺口已闭合,于是这条用例退化成永久噪音(它现在断言"审计必须检测到一个已不存在的缺陷")。改为**栽桩灵敏度**用例:人造一个必然无人消费的键,断言审计抓得到 —— 与 silent-except 扫描器同一处理。

### 源文本审计可以被"空泛地满足"——必须有行为守卫

文本审计有个致命弱点:往 `params = dict(weight_kline=1.0, ...)` 里加一个默认值就能让它变绿,**而声明依然被忽略**。所以本次并列新增 `tests/test_preset_declarations_are_load_bearing.py`,用**行为**断言:两个不同的声明值必须产出两个不同的结果(如 `position_fraction=0.5` 必须让成交股数减半),声明与引擎容量冲突必须 fail-fast。

反面教材警告:用"某文件源码里含某字符串"来证明接线是不作数的。

### 量化与验证

同机、同 DB,逐测试比对失败集合(而非只比失败数量):

| | 失败 | 通过 | 跳过 |
|---|---|---|---|
| `548d8a0`(修前) | 27 | 915 | 22 |
| `b8c1539`(修后) | **22** | **934** | 22 |

**零新增失败;5 项 RED→GREEN**(4 项 preset 一致性 + `test_all_in_sizing_fraction_preservation::test_chase_up_uses_position_fraction_in_sizing`,后者在修前确实是 RED)。通过数 +19 = 5 修复 + 14 新增用例。

行为中性已单独验证:`chase_up` 的 golden baseline 33 项全绿 —— 接通声明**没有移动任何一个历史数字**(出厂值全是常量)。若将来有人改了预设值,行为应当随之改变:那时它是真的生效了。

### 附带发现:钉字面量的测试钉住的是拼写,不是缺陷

`test_volume_cap_rounding_constant_pin_cycle` 钉的是完整字面量 `int(bar_volume * self.MAX_VOL_PARTICIPATION // 100) * 100`。把参与率改为声明驱动后属性名变了、**缺陷一字未改**,旧断言却把这次无害重命名误报成"已修复"。已改为钉 **round-to-0 形状本身**(`// 100) * 100`),对属性重命名免疫。

---

## 附六:「用红灯表达待办」——一种会吃掉真实回归的测试用法

修复过程中最有价值的一类发现,不在引擎里,而在测试里。本仓库有约 11 条用例是**故意失败**的:它们断言的是一个缺口**存在**,以此当作待办清单。这有三个代价,和前附五的"假阳性"同源:

1. **红成了常态 → 真实回归藏身其中。** 本分支整改过程中实际发生过一次:某轮改动 57→52 条失败看似改善,逐条 diff 才发现"修好 9 条、弄坏 4 条"。若红灯本就是预期状态,这 4 条不会被任何人注意到。
2. **缺口闭合后,用例不转绿,而是变成假阴性。** 例:`test_corporate_actions_dividend_deposit` 的三条只在**引擎目录**里搜处理器的**定义**;而 §2/§6 恰恰要求共享逻辑收敛到 `core/` —— 于是**把代码放对地方,反而让测试看不见了**。
3. **它们与 §7 直接冲突。** 多条断言"`results/` 下存在某产物",而 §7 明令 `results/` 必须 gitignored。于是这个断言既不反映仓库状态(fresh clone 必然全红),也拦不住假绿(本机随便一个 `*ledger*.csv` 就能把它蒙绿)。

**处置原则:先判"是代码错,还是断言错"。**本轮 11 条里没有一条是靠"改断言让它变绿"了事的:

| 断言错在哪 | 例 | 修法 |
|---|---|---|
| **判据选错**(修好了也报缺口) | v3a 的 LEFT JOIN 用例把补丁打在 `eng.duckdb`,而连接早已按 §6 收进 `_panel_loader` | 移到真正的连接点 |
| **自相矛盾** | `test_dual_price` 两条**同时**要求"raw_close=NaN 时 raise"与"取 0.0" —— 没有实现能同时满足 | 按当前(Round 30)契约重写:回退 adj,而非归零 |
| **超出章程原文** | `test_claudemd_full_audit` 断言 `max_positions==1`;而 §2 verbatim 说 "Capacity is bounded by the preset's `max_positions`" | 按原文重写 —— 该规则曾把 v58 多仓与 v63/v64/v79 集成三类**合规**设计判成违规 |
| **物理不可达** | `test_sl_gap_fill_uses_sl_p_loss_cap_semantics` 造出 +12.6% 的跳空(已越涨停),却期望在封板那根回补 | 见下 |

### 一条值得单独记的:被 §4 守卫正确拦下的"幻影断言"

那条用例报「未触发入场」。实际链条是:bar 202 跳空 **+12.6%**,**已越过 A 股 ±10% 涨停** → §4 的涨停守卫**正确地拒绝回补**(做空平仓 = 买入);随后夹具又把价格写回 22.20(止损**下方**)→ SL 永不触发、面板结束前平不掉 → 无成交。

夹具改为**让价格留在跳空价位**后,§4 的真实语义才显形:封板那一根不成交,**回补推迟到下一根可成交 bar**,损失仍被 `sl_pct` 截断。这条用例因此从"噪音"变成了 §4 涨停守卫的**正面证据**。

同型的一条:`test_immutable_state_4engine` 把挂单队列的 `pop` 记为 §0 违规 —— 而"取消无法成交的挂单"恰恰是 §4 要求的 IOC 行为,且成交列表(历史)不受影响。现把**瞬态控制状态**显式划出 §0 的射程,并新增守卫钉住该名单**必须极窄**(否则它就成了绕过 §0 的后门)。

### 仍未闭合的缺口(30 条 skip,均带点名文本,无静默跳过)

- **§7 产物边界(8 条)**:**更正(附三十七)** —— writer 存在,缺口是接线(见该附录)。该文件的四条守卫已由『等本机产物』改为**自己产出再校验**(合成输入 + 一条真跑端到端),不再真空。`results/` 按 §7 不入库,故这些断言只在产物存在时校验 schema、缺失时 skip 登记。§2 的实质要求(NAV 恒等式 + 现金守恒)已由 `test_nav_cash_ledger_invariants.py` 在内存中确定性覆盖。
- **§0 cycle 慢 golden(1 条)**:需 `DNA_RUN_SLOW_GOLDENS=1` 显式开启(单次约 6.5 分钟)。
- **§5 基准归因**:本地行情库**无任何指数序列**,归因无法计算(已由 `test_benchmark_data_gap_is_registered` 显式登记)。补齐需 `hithink-finance index history`,**选哪个基准是研究决策**。
- **§4 滑点的实质**:100 个 preset 仍是 `SLIP_NONE_ACKNOWLEDGED`(= 0.0,"已知缺口"的确认值)。换成真实标定值会改变每一个成交价,属研究决策,且按 §5 必须计入 `n_trials`。
- **§3 公司行为**:配股/缩股未建模(全库 1 例),`apply_corporate_action` 会显式告警而非静默。

---

## 附七:把「未审查」的六个面逐条查证(三条真缺陷 + 一条重要核验 + 两条纠正)

附六列出的 §6 六条"没有任何 cell 覆盖"的面,本轮逐条查证。**结论先行:其中三条是可证实的真缺陷,已修并配双向验证的守卫;一条是审计自身表述的纠正;一条把审计最重的未知直接核验掉了;两条属研究决策/仓库级决策,维持登记。**

| # | 面 | 查证结论 | 处置 |
|---|---|---|---|
| 1 | §0 时区 | **真缺陷** | 已修 + 守卫 |
| 2 | §0 可复现性(夹具) | **真缺陷** | 已修;lockfile 仍登记 |
| 3 | §5 归因 | 机制已就位,缺**报告级标注** | 已补标注;数据缺口仍登记 |
| 4 | 黑名单死路径 | **真缺陷**(四处叠加) | 已修 + 守卫 |
| 5 | raw/adj 语义前提 | **已核验**,前提成立 | 无需重推 |
| 6 | `render_top5` 工具 | 审计表述**过重** | 真实分歧已修 + 首个守卫 |

### 1 · §0 时区(真缺陷)

`tools/update_db_direct.py` 用 naive datetime 的 `.timestamp()` / `fromtimestamp()` ——
两者都按**本机时区**解释。实测:同一组日期在 `TZ=UTC` 与 `TZ=Asia/Shanghai` 下产出
`1472745600000` vs `1472788800000`(**相差 12 小时**),足以让同一份 API 负载落成不同的
bar 日期。CLAUDE.md §0 明写 "normalize timestamps to a single exchange timezone"。

修:锚定 `EXCHANGE_TZ = UTC+8`(A 股无夏令时),`to_ms`/`from_ms` 构成与时区无关的往返。
守卫在**子进程里换三种 TZ** 比对输出 —— 已双向验证:换回旧实现时该守卫必然失败,且打印出
三个不同的输出。该工具此前**无任何测试**。

### 2 · §0 可复现性:夹具用 `hash()` 播种(真缺陷)

`tests/conftest.py`:`base = 10.0 + (hash(code) % 100) / 10.0`。CPython 对 str 的 `hash()`
**逐进程随机化**(PYTHONHASHSEED),于是同一份夹具每次运行生成**不同的价格** —— 直接违反
§0 的可复现性要求,也是潜在的 flaky 来源(数值不同 → 可能触及不同分支)。

实测(这正是"证据"):`PYTHONHASHSEED=0` 得 `11.3, 11.1, 14.5…`,`=12345` 得 `15.3, 10.4, 13.5…`。
修:改用 `zlib.crc32` 确定性摘要;三种 seed 下输出完全一致。

**顺带完成的 §0 全库扫描**(结果:干净):生产代码中唯一的 `random` 用法是
`uptrend_pullback/iter_reverse.py` 的 `random.Random(args.seed)`(显式种子实例,优于全局
seed);`time.time()` 的全部出现都只用于**耗时打印**,不进入任何被计算的值(唯一的例外是
`update_db_direct.py` 的 batch id,属元数据)。既有的两道随机性守卫共 14 项全绿。

**仍登记**:`requirements.txt` 只有版本范围、无 lockfile。本机是 conda 环境,直接
`pip freeze` 会产出一份**误导性**锁定(把 conda 提供的包当成 pip 依赖钉死),故不代做 ——
建议用 uv / pip-tools 在指定 Python 版本下生成。

### 3 · §5 归因:让「未归因」随每一份报告一起走

机制(`dna_stats/attribution.py`)此前已就位,缺的是**读者可见的标注**:该限制只活在模块
说明、一条测试的 skip 文本和本文档里 —— 而**报告读者看不到**。§5 要求无基准时必须把结论
标注为"未归因",否则就是它要防的"把 beta 当 alpha"。

修:标注写在**唯一的规范渲染点** `core/trade_report.py::_summary_html`(§6 纯函数),并以
命名常量 `UNATTRIBUTED_NOTICE` 单源导出 —— 四个引擎的报告一并生效。守卫钉住"报告必须含该
标注且文本取自该常量"。补齐基准数据仍是研究决策。

### 4 · 黑名单:被跟踪的文件从未被加载(真缺陷,四处叠加)

- `DEFAULT_EXCLUDE_PATH` 指向 `short_reversal/data/exclude_thscodes.txt` —— **不存在**;
- 真正被 git 跟踪的黑名单在仓库根 `data/exclude_thscodes.txt`(**提交于 `ffe29be`**);
- 模块 docstring 把 no-op 的原因写成"该文件不存在" —— **而它存在且被跟踪**。
  一句错误的说明会把后来人引向完全错误的结论,**这本身就是需要修的缺陷**;
- `_load_exclude` 在路径缺失时**静默返回空集** → "要排除 29 只"与"排除 0 只"不可区分
  (chase_up / uptrend_pullback 的副本同型)。

修:单一共享路径 + **按模式门控**。门控是刻意的:名单内容是**大盘金融股**(工农建招、
中信/华泰/海通等券商),那是一个**研究口径**的排除,不是安全清单 —— 让它在 `mainboard_only`
下也生效,等于用一次"修 bug"偷偷改掉所有 preset 的股票池。实测 73/75 个 preset 用
`mainboard_only`、2 个用 `broad_only`、**0 个**用那个以"排除"命名的模式,故本次改动对
**全部出厂 preset 行为中性**。另:显式传入缺失路径 → 三引擎一致 fail-fast;文件里的重复项
`601995.SH` 已去除(30→29 行)。

### 5 · 审计最重的一条未知:**已核验**(§6 第 5 条)

报告原文:"若生产库中 `v_daily` 实为复权价,则 `short_reversal` A 条件、cycle 指标域、
公司行为三条需要重新推导"。本轮直接查了本机行情库的**视图定义**:

```
v_daily      = SELECT ... FROM raw_kline_daily                       ← 不施加任何因子
v_daily_hfq  = raw_* × COALESCE(backward_factor, 1)
v_daily_dual = hfq AS adj_* , raw AS raw_* , lag(raw close) AS raw_prev_close
```

实测 `v_daily EXCEPT raw_kline_daily` = **0 行**(完全一致),而 hfq 在有除权事件的票上确实
分叉(`000905.SZ`:raw 5.40 vs hfq 5.644)。**故 §3 的 raw 执行前提成立,三条相关发现无需
重新推导。**

诚实边界:该结论依赖**本机活库**(不在快照内),属"活库核验"而非快照可重放 —— 与 §7
所述边界一致。

### 6 · `render_top5_presets_html.py`:审计表述过重,但确有一处口径分歧(已修)

原文称它"重新实现了两个引擎的指标与 A/B/C 判定,并带着自己的第三个 metrics 函数"。
逐行查证后:**它调用真的引擎**跑两个回测(`chase_up.backtest.run_backtest` /
`short_reversal.engine.run_backtest_v3`),并复用 `load_universe` / `compute_indicators`
—— **回测本身没有被重实现**。重复的是**展示层**(`_compute_short_indicators` 重述逐 bar
指标序列、`_build_entry_reasons_*` 重述 A/B/C 文案);消解它需要引擎暴露逐 bar 指标序列,
属重构而非顺手改,已登记。

但其中确实有一处**可证实**的分歧:`_summary_metrics` 用**日历日**年化
(`(last-first).days / 365.25`),引擎用**交易日** (`len(equity) / TRADING_DAYS` = 243)。
同一次回测因此有两个 CAGR —— 220 根 bar 的窗口下 years≈0.843 vs ≈0.905,页首数字与引擎
metrics 对不上,**而两边看起来都"很合理"**,正是最难发现的一类漂移。已统一为交易日口径。

顺带给这个此前**零测试**的 1162 行工具补上第一道守卫:断言其汇总指标与引擎规范实现逐位
一致(1e-12),并单独钉住年化口径本身。已双向验证 —— 换回日历日口径时,恰好那两条 CAGR
用例失败。

---

## 附八:一个「缺了分母」的数字 —— `cycle_price_action` 的 `total_pnl`

这是本轮**唯一一条既不在原审计发现集、也不在那六个未覆盖面里**的发现,来自"按 §2 的原话
去核对每一个对外发布的数字"。

### 模型

`cycle_price_action/backtest.py` 对 universe 里**每个成员各建一个独立账户**
(`for code, slice in universe.items(): cerebro.broker.setcash(cash)`),再把所有账户的
成交并成一张表。`cash` 是**每账户**资金(默认 100 万)。

### 后果:一个没有分母的合计

`compute_metrics` 诚实地把 `cagr` / `sharpe` / `max_dd` 返回 `None` —— 横截面研究里
这三者**无法定义**,返回 None 正是"算不出就不算"。但 `total_pnl` 是裸的合计:

| | 值 |
|---|---|
| 实测窗口 2026-04-01..05-01 | 492 笔成交 / **472** 只股票 |
| `n_accounts`(universe 成员数,独立复核一致) | **2953** |
| `notional_capital` | **¥2,953,000,000** |
| 对照:chase_up / uptrend_pullback / short_reversal | 单个 **¥1,000,000** 组合 |

也就是说 cycle 的 `total_pnl` 分母是 **29.5 亿**,与另外三个引擎的 100 万相差约 **2953 倍**。
把它们的数字并排放在一张表里比较,读者会得到错误结论 —— **而引擎并没有算错**:
错的是发布出来的数字**缺了它自己的分母**。

### 一个正确的参照就在旁边

`short_reversal` 的集成路径(`_run_ensemble`)做对了同一件事:`final_capital =
sum(sub_i.final_capital × w_i)`,其中 `w = ensemble_weight`。实测三个集成 preset 都有
**`n × ensemble_weight = 1.0`**(2×0.5 / 3×0.3333 / 2×0.5),即权重**归一**,结果与
"一个 `INITIAL_CAPITAL` 组合"直接可比。同族问题在本仓库已有一处正确实现 —— 这让
cycle 的缺口更像是遗漏,而不是设计选择。

### 修法

`compute_metrics` 新增**必填**的 `cash_per_account` / `n_accounts`,并把
`account_model` / `capital_per_account` / `n_accounts` / `notional_capital` 写进返回值 ——
于是**口径随产物一起发布**(这些字段会进入 `results/<preset>_metrics.json`)。

必填而非可选是刻意的:让"忘记标注"在**调用点**就失败,而不是悄悄发布一个含义不明的合计。
`run_backtest` 传的是 **universe 成员数**,不是成交过的股票数 —— 每个成员都开了账户,
即使一笔未成交(这正是 472 与 2953 的差别)。

守卫:单测覆盖两类返回路径 + `notional_capital` 恒等式 + 缺参数必须 `TypeError`;
另有**接线**守卫用合成库验证 `n_accounts == len(universe)`(分母来自真实宇宙)。

### 一般原则

这与附七的 §5「未归因」标注是**同一条**:

> **当一个数字的含义依赖某个未被说明的模型时,就不能只让那个模型活在 docstring 里。**

本仓库反复吃亏的形态是"缺口靠沉默存在"(静默默认值、未接线声明、用失败表达待办)。
"缺分母的数字"是它的**输出侧**版本 —— 它不需要代码有 bug,只需要读者不知道模型。

---

## 附九:`results/backtest.json` 在「全胜窗口」下是**非法 JSON**

沿用附八的方法(逐个核对对外发布的产物),发现第二条输出侧缺陷。

### 现象

`profit_factor` 在**无亏损笔数**时返回 `float("inf")`(`chase_up/backtest.py`、
`uptrend_pullback/backtest.py`)。而 Python 的 `json.dumps(float("inf"))` 写出的是:

```json
{"profit_factor": Infinity}
```

**`Infinity` 不是 RFC 8259 的合法值。** 关键在于:Python 自己的 `json.loads` 默认
**宽松接受**它 —— 所以自家 round-trip 读得回来,缺陷因此长期隐形。而 JS 的
`JSON.parse`、Go、Rust、`jq` 一律拒绝:**任何非 Python 的消费者都读不了这份产物**。

实测(修复前):

```
profit_factor = inf
严格 JSON 写出 → 失败: Out of range float values are not JSON compliant: inf
```

"全胜窗口"在短区间里很常见(样本少、行情顺),不是理论边角。

### 修法

1. `profit_factor` 分母为 0 时返回 **`None`** —— 与仓库既有的"算不出就 None"口径一致
   (`max_dd=None` / `cagr=None` / `beta=None`),既合法,又不去冒充一个数字。
2. 四个引擎的**全部 8 个产物写出点**加 `allow_nan=False`。这是**系统性的那一半**:
   将来再引入非有限值会在**写出那一刻**失败(§0 fail-fast),而不是悄悄产出一份读不了
   的产物、等到别的语言的消费者来读时才发现。

守卫:真实算出的指标字典必须能被 `allow_nan=False` 严格序列化 + 逐值检查无非有限浮点
+ 四个引擎的写出点都必须禁非有限值。已双向验证 —— 换回 `inf` 时该用例必然失败。

### 顺带发现(未修,已登记)

`uptrend_pullback/tail_objective.py::tail_stats` 另有 `inf` 与 3 处 `nan`,
但它在**测试之外没有任何调用点**,故不会进入产物 —— 与 `render_top5` 同属
"无消费者的库函数"。这类"有实现、无消费者"的代码本仓库已多次出现,建议统一清理时
一并处理,而不是逐个顺手改。

---

## 附十:同一个指标三处定义 —— 年化口径(CAGR 差 8%~26%)

沿用附八/附九的方法(逐个核对对外发布的数字),第三条输出侧缺陷,也是三条里**量级最大**的。

### 三处「一年有多少天」

| 位置 | 口径 |
|---|---|
| `chase_up/backtest.py` | `交易日数 / 243` |
| `uptrend_pullback/backtest.py` | `交易日数 / 243`(**同值,但各写一份**) |
| `short_reversal/engine.py` | `日历日跨度 / 365` |
| `dna_stats/*.py` | 默认 `252`(参数,由调用方传) |

日历日 ≠ 交易日。**实测** —— 同一窗口、同一 10% 总收益,两条引擎口径给出的 CAGR:

| 窗口 | 交易日 / 日历日 | 交易日口径 | 日历日口径 | 相对差 |
|---|---|---|---|---|
| 2026-04-01→05-01 | 23 / 30   | 173.7% | 218.9% | **26%** |
| 2026-01-20→03-01 | 29 / 40   | 122.3% | 138.6% | **13%** |
| 2025 全年         | 261 / 364 |  9.28% | 10.03% | **8%**  |

**不是舍入差异**:连整整一年的窗口都差 8%(2025 有 261 个交易日、364 个日历日,两个
分母都不「整」)。而**两边都看起来合理** —— 同一个指标、两处定义、各自自洽。
这与附七在 `render_top5` 工具里发现的分歧是同一族缺陷,只是这次落在**引擎**身上
(那个是展示层,这个是发布层)。

### 修法

- 新增 `core.trade_schema.TRADING_DAYS_PER_YEAR = 243`(A 股交易日/年)与
  `annualized_years(交易日数)`,作为**引擎侧单源**(§2 Canonical 常量只定义一次);
- `chase_up` / `uptrend_pullback` 改为引用它 —— 值不变,**零结果漂移**;
- `short_reversal` 切到**交易日口径**(用面板去重日期数),并把 `n_trading_days` 写进
  metrics。**这是一次有意为之的结果漂移**,量级即上表,记在此处。

**为什么把分母也写进产物**:此前该口径只活在代码里,读者拿到 `cagr` 无法判断分母是
交易日还是日历日 —— 与附八的 `account_model` 同一理由:**一个数字的含义依赖未说明的
模型时,就不能只让模型活在 docstring 里。**

### 仍在 §5 层面登记(未改)

`dna_stats` 默认 `252`。它参与 DSR / Bonferroni 的收缩量,改动会**影响统计结论**
(既往 DSR 比较随之失效),属统计口径变更而非「顺手修」—— 与 §4 滑点、§5 基准同属
需要使用者拍板的一类。

---

## 附十一:`sharpe` 在三个引擎里**不是同一个量**

把附八/附九/附十的核对做完后,`sharpe` 是最后一个未核的发布指标 —— 而它是最严重的
一个,因为另外三条是「同一个量、不同分母」,这一条是**同名不同量**。

| 引擎 | `sharpe` 实际是什么 |
|---|---|
| `chase_up` / `uptrend_pullback` | **日收益序列**的 Sharpe:`mean(日收益)/std(日收益) × √243` |
| `short_reversal` | **逐笔 net** 的 `mean/std × √(min(n_trades, 250))` —— 交易级比率 |
| `cycle_price_action` | `None`(横截面研究无法定义 —— 诚实地不算) |

后者**不是 Sharpe**,是一个"逐笔收益的信噪比"。二者在任何维度上都不可比:一个衡量
日频资金曲线的风险调整收益,另一个衡量成交样本的离散度。

**危害在于仓库自身就在按它排序**:`_run_all_presets*` 等 sweep 脚本用
`sorted_by_sharpe` 排序预设。同一引擎内排序尚可(同一定义),但只消有人把两个引擎的
结果并在一张表里,得到的排名**没有任何意义** —— 而仅看键名 `sharpe` 完全看不出来:
caveat 只埋在 `_approx_sharpe` 的 docstring 里(「粗略,仅供排序」)。

### 修法

四个发布点(两引擎各 2 个:正常返回 + 空成交返回;short_reversal 2 个:单腿 + 集成)
一律带上 `sharpe_kind`:`"daily_returns_annualized"` / `"per_trade_ratio_approx"`。

守卫:两类的字符串必须**真的不同**(否则这个键不起作用)+ 各自取值正确 +
**凡发布 `sharpe` 的文件必须同时发布 `sharpe_kind`**(防止将来新增发布点又漏标)。

### 这一轮(附八~附十一)的共同点

四条发现全部来自同一个动作:**逐个核对对外发布的每一个数字,追问"它的含义依赖
哪个没有写出来的模型"**。四条里没有一条是"代码算错了":

- `total_pnl` 算对了 —— 缺的是分母;
- `profit_factor` 算对了 —— 缺的是产物可读性;
- `cagr` 算对了 —— 三处各按自己口径算;
- `sharpe` 算对了 —— 三处算的**根本不是同一个东西**。

**它们都不会被"测试是否通过"发现,也不会被"数字是否合理"发现** —— 只有"这个数字
的含义是什么、谁在读它"能发现。这与 §0 的静默缺口是同一件事的两个侧面:一个在输入侧
(声明被静默丢弃),一个在输出侧(数字被静默误读)。

---

## 附十二:fresh clone 拿到的是**红的**套件 —— 31 个用例(§6)

前面的每一轮我都是**在本机有行情库**的条件下跑测试的。这一轮补上了那个从未跑过的检查:
**把库拿掉再跑一遍** —— 因为 §6 对这件事有明文要求。

CLAUDE.md §6 verbatim:

> "Tests MUST skip (not error) when the local DB or run artifacts are absent."

### 实测(两种"没有库"的形状)

| 形状 | 结果 |
|---|---|
| 库路径**不存在**(全新克隆最常见) | **15 failed + 5 errors**(954 passed, 54 skipped) |
| 库文件是 **0 字节占位**(本仓库 `data/hiagent.db` 的真实形状) | **8 failed + 3 errors**(958 passed, 59 skipped) |

两种形状合计 **31 个**用例在"没有库"时不是 skip,而是 fail/error。也就是说:
**新克隆者的第一次 `pytest` 看到的是一套红的套件。**

### 为什么这条比它看起来重要

它和附六讲的是**同一个机制**:红成为常态之后,真实回归就藏得进去。附六处理的是"故意
写红"的用例,这一条是"意外写红"的用例 —— 效果一样:套件不再是可用的信号。而且它
发生在**最初的接触点**上(克隆后第一次运行),代价是此后每个人都学会"先忽略一批红"。

### 三类成因(逐条可证)

1. **模块级 fixture 跑在文件的 skip 检查之前** ——
   `test_backtest_data_integrity.py` 的三个 module 级 fixture 直接连库,而该文件的
   skip 检查写在文件**中部**的一个测试里。于是 5 个用例是 ERROR,而不是 skip。
   (§6 的检查写在"能跑到的地方",而不是"库被用到的之前" —— 位置错了。)
2. **干脆没有 skip 检查** —— 10 个用例直接 `load_universe(DB_PATH)`,没有前置判断。
3. **只查 `exists()`,不查大小** —— 这是最隐蔽的一类:0 字节占位文件**存在**,
   于是检查通过,然后 `duckdb.connect` 在读模式下抛 IOException。
   **而 0 字节占位正是 fresh clone 的形状** —— 检查项与要防的场景恰好错过。

### 修法

在 `tests/conftest.py` 加**一个**共享助手(而不是第 20 份重复的判断):

- `market_db_available() -> bool` —— 存在**且**非空,供模块级 `skipif` 用(模块级不能 skip);
- `require_market_db() -> Path` —— 不可用则 `pytest.skip`,返回可用路径。

再把 4 个文件里的 20 处与 5 个文件里的 11 处一律改走它;本次改动造成的 3 个孤立导入
(`Path`/`pytest`/`_DB`)一并移除。

守卫的形状:**我把两种"没有库"的形状都跑成了 0 failed / 0 errors** —— 这不是"看起来对",
而是把 fresh clone 的条件本身当成了验收条件。

---

## 附十三:§5 的执行层不在引擎里,在那 25 个研究脚本里

§8 第 15 条登记的「sweep 的 OOS 窗口」一直开着。这一轮把它查清:**§5 的纪律不是由引擎
执行的,而是由 25 个 `sweep*.py` / `wf_*_focused.py` / `grid*.py` 脚本执行的** ——
DSR、n_trials、WFV 全在那里。所以"引擎合规"与"研究合规"是两件事。

### 1 · WF 家族(14 个文件):分子与分母描述了**两次不同的选择**

`deflated_sharpe_ratio` 的契约原文(其 docstring):

> `n_trials`: Number of independent strategy configurations tested. This is the
> "selection bias" correction — **selecting the best Sharpe from k trials** ...

也就是说 `n_trials` 必须与产生 `observed_sharpe` 的那次选择**对应**。而 14 个 WF 脚本里:

- **分子** `observed = max(sharpes)`,其中 `sharpes` 是**单个 preset 在 4 个窗口**上的
  Sharpe → 这是「最好的那一个**窗口**」;
- **分母** `n_trials = n_comparisons` → 这是「试过多少个**配置**」。

两者不是同一次选择,于是**窗口那一层选择完全没有被折减**,报出的显著性偏高。

**这不是新引入的**:提交 `4acfc2e` 把 `n_trials` 从窗口数改成配置数(方向正确),
但**没有同步修改分子**;而它当时的验收方式是「未跑完整 wf 回测(**仅编译 + 导入 +
取值验证**)」。这正是本报告反复出现的那个教训的又一例:**结构验证不等于验证。**

修:分子改为**跨窗口均值**(WFV 的无偏汇总),分母仍为配置数 —— 两者描述同一次选择;
逐窗口数值本来就逐行打印,信息不丢失,最大值单独标注为「选中值,不作显著性输入」。

**数值验证**(不再只做结构验证):把 `run_backtest_v3` 换成依次返回
`[0.4, 1.9, 0.7, 0.6]`,断言 DSR 收到的是 **0.9(均值)** 而不是 **1.9(最大)**。

### 2 · `chase_up/wf_sweep_all.py`:把**收益率**当 Sharpe 传进 DSR

原为 `observed = max(summary["median_return_pct"]) / 100` —— 窗口中位**总收益**的
百分比被当成「年化 Sharpe」,而 DSR 的 docstring 明确要求后者。

后果**不是数值误差,是结论错误**。实测同一批数字:

| 输入 | DSR | p 值 | 读作 |
|---|---|---|---|
| `12%` 当成 Sharpe=0.12 | 0.034 | 0.966 | 「毫无优势」 |
| 真 Sharpe = 1.20 | 0.228 | 0.772 | 有边际优势 |

即它会把**有边际优势**稳定地印成「无优势」,而且照样作为显著性结果打印出来。
汇总表里本来就有 `mean_sharpe` 列,改用它是显然正确的修法。打印标签一并改正 ——
原先写 `observed_median_ret=+12.00%`,照原样会把 Sharpe 印成百分数。

### 3 · 4 个研究脚本引用**已被删除**的 preset,根本跑不起来

| 脚本 | 引用的 preset | 现状 |
|---|---|---|
| `wf_v34_focused.py` | `v34_mainboard_pctchg_tight` | v34 系列**一个都不剩** |
| `wf_v37_focused.py` | `v37_liq_3e7_5e8` | v37 系列**一个都不剩** |
| `wf_v39_focused.py` | `v39_pctchg_04_09` | 只剩 `v39_pctchg_03_10` |
| `wf_v41_focused.py` | `v41_pctchg_04_10` | v41 系列**一个都不剩** |

它们在启动第一行就 `SystemExit("preset ... 不在 PRESETS")`。

**我没有改它们。** 被删的 preset 没有留下可推断的重命名映射(v34/v37/v41 一个都不剩),
把名字改成某个"看起来像"的 preset 就是**编造实验记录** —— 那比留着失效更糟。

处置:**登记债务**,而不是静默。新增守卫要求实际失效集合**等于** `KNOWN_DEAD_REFERENCES`
登记表:新增失效会失败(被抓住),而只有把旧的修掉、同步缩短登记表才算通过(防止登记表
变成永久借口);另有一条钉住这些脚本必须**响亮**失败,不许被改成"找不到就跳过"
—— 静默跳过会让「脚本没跑」看起来像「脚本跑了且没结论」。

### 这一轮的方法论小结

25 个脚本里,7 个网格类脚本的 `max(sharpes)` 是**正确的**(sharpes 逐配置,分母也是配置数)。
**没有先分清哪一类就"统一改一遍",会把对的改错。** 同样的教训本轮出现两次:
分子/分母的语义要先对齐,再动代码。

### 4 · cycle 的 sweep:同一个缺陷的**另一半**

`cycle_price_action/sweep_thresholds.py`(与 `wf_*` 相反的方向):

```
observed = max(all_sharpes)      # all_sharpes = 阈值 × 窗口 展平后的**每一格**
n_trials = len(thresholds)       # 却只数阈值
```

即 **max 取了 T×W 项、按 T 折减**。WF 家族是"max 取窗口、按配置折减",这里是
"max 取整张网格、按一维折减" —— 同一个契约违反的两个方向。

**一个自相矛盾的信号**:该脚本**自己打印的表**是逐阈值的 `avg_sharpe`(0.900 / 0.500),
而 DSR 用的是展平后的 1.000。**打印出来的数**与**实际拿去算显著性的数**不是同一个 ——
这类"展示与计算不一致"很难靠读代码发现,是靠"把打印的数和传进函数的数对一遍"发现的。

修:每个阈值先按窗口取均值(窗口是同一策略在不同数据上,不是独立 trial),再在 T 个
阈值均值里取最大 → "max 取 T 项 + n_trials = T" ✓,且与它自己的表一致。
**数值验证**:塞入 `{2.0: [1.0, 0.8], 2.5: [0.6, 0.4]}`,断言 DSR 收到 **0.9** 而非 **1.0**。

顺带记一条**该脚本做对了的事**(避免读者以为它整体不合格):它用规范
`walkforward_windows`、跑 OOS 的 `test_start/test_end`(Round 24 修过且留了记录)、
报 Bonferroni —— 同类纪律里,它是仓库的执行范例。

### 5 · 一处**与仓库自身矛盾**的声明

`cycle_price_action/presets.py` 把 `n_comparisons=1` 的理由写成
「cycle 单一 preset,**无 sweep**」。而:

- `cycle_price_action/sweep_thresholds.py` 就是为**本 preset 的 `threshold`** 建的 sweep;
- 它的默认候选是 `--thresholds 1.5,2.0,2.5`,而**出厂的 `threshold=2.0` 正在其中**
  (而且是正中间那个)。

若 2.0 确由那次 sweep 选出,§5 Iterative-Tuning Accounting 要求把它计入 `n_trials`,
`n_comparisons=1` 即**低估** —— 报出来的是 PSR 而不是 DSR,也就是"不做折减"。

**我没有改这个数值。** 真实的累计试验数只能来自**迭代记录**,不是从代码能推出来的量;
写成 `3` 之类的"看起来合理"的数字是**伪精确**,而且大概率仍然低估。处置是:
更正那句与仓库矛盾的注释 + 把该 preset 登记进 `KNOWN_UNRECORDED_TRIAL_COUNTS`,
直到记录补齐。**这一条需要你提供迭代记录** —— 它是本轮唯一一处我明确交还给你的数值。

### 6 · 新增两条 §5 守卫(含一条"防误伤")

- **"max 取几项,n_trials 就数几项"**:只惩罚「展平网格上取 max **且** 按其中一维折减」
  这一种组合 —— `uptrend_pullback/sweep_v33_long*.py` 的 `max(all_sharpes)` 配
  `n_trials=len(all_sharpes)` 是**对的**,不能被误伤。
- **举证责任倒置**:"参数值 ∈ 自家 sweep 的默认候选,却声明 `n_comparisons=1`"必须
  登记或据实填写 —— 让"这个值不是 sweep 选的"从**默认成立**变成**需要说明**。

---

## 附十四:`tools/` 面(此前只查过 2/5 个文件)

`tools/` 共 5 个文件、2506 行。此前只查过 `update_db_direct.py`(时区)与
`render_top5_presets_html.py`(CAGR 口径)。剩下三个查完的结果:

**干净的三条**(先记合规项,免得读者以为这一面全是问题):
- **都调用规范引擎**,没有重实现回测/信号;
- **都从 `__file__` 推导路径** —— 没有硬编码绝对路径(审计在
  `tests/_regen_chase_baselines.py` 抓到过这一类,这里没有);
- **都只写 gitignore 覆盖的 `results/`**(§7)。

### 1 · §0/§2:「无法定义」被换成 0.0,并**带着假数字进入跨策略排名**

`tools/run_all_backtests_html.py`(710 行,**此前零测试**)把

```python
"cagr":   float(metrics.get("cagr")   or 0.0),
"sharpe": float(metrics.get("sharpe") or 0.0),
"max_dd": float(metrics.get("max_dd") or 0.0),
```

用于 `cycle_price_action` —— 而这三个量在 cycle 上**无法定义**(横截面研究,每股一个
独立账户)。换成 `0.0` 有两层后果:

- **渲染层**:页面显示 `0.00`,与"真的等于零"无法区分;
- **排名层**:它带着这个假数字进入「按 Sharpe / CAGR / max_dd 的跨策略 TOP-8 榜」——
  而**排名榜会被当作结论读**。

改回保持 `None`:该工具的 `_fmt_pct` / `_fmt_num` 本就把 `None` 渲染成「—」,而
`render_rank` 本就过滤 `None` —— 于是它**自然地退出排名**,而不是以 0 参赛。

值得一提的是,**这个工具原本就写了一条跨策略可比性警告**(提醒 short_reversal 的
CAGR 量级会包揽榜单)—— 作者在意这件事,只是不知道更深的那一层。

### 2 · §2:该工具**按 Sharpe 给跨策略排名** —— 而附十一已证明它不是同一个量

`chase_up`/`uptrend` 是日收益年化 Sharpe,`short_reversal` 是逐笔比率近似,`cycle` 无定义。
"按 Sharpe 排序"跨策略**没有意义**。现在每行的 `sharpe_kind` 随产物发布,并在排名区块
顶部写明不可比。

### 3 · 守卫**实测**发现的一处真 bug:`nan` 泄漏进 CSS

新写的渲染守卫(用 nan / inf 驱动)立刻报出:

```html
<div class="bar" style="width:nan%"></div>
```

`bar_pct = abs(cagr) / scale * 100` 此前**绕过了** `_fmt_pct` 的 NaN/None 保护 ——
而 `_fmt_pct` 的 docstring 明写它的存在就是为了

> 防止引擎 regression 把 "nan%" / "inf%" 写入 HTML

**那条意图有漏洞,而漏洞只在这条路径上。** 这类"同文件里一处防住了、另一处没防住"很难
靠读代码发现 —— 是**用非法输入驱动渲染**发现的。

### 4 · 更正我自己上一轮的一处**误报**

上一轮我对 `tools/` 跑了死 preset 扫描,报出 `chase_up` / `v1` / `v36_d_converge` /
`v40_tp_07` 等。复核后**全是扫描器的假阳性**:

- `chase_up` 是**引擎名**不是 preset 名;`v1` 是版本片段;
- `v36_d_converge` / `v40_*` / `v44_*` / `v45_*` 属于 **short_reversal**,却被我按
  uptrend_pullback 的集合判定(因为 `render_top5` 同时处理两个引擎,而我按文件推断引擎)。

**`tools/` 没有死 preset 引用。** 这条记在这里,是因为本轮前面刚强调过"假阳性比假阴性
更毒,它会诱导人去修没坏的地方" —— 我自己的扫描器也踩了同一个坑。

### 守卫

这个 710 行、零测试的工具现在有 **8 条**守卫:导入冒烟 / `None` 不崩 /
**未定义不参与排名**(带对照组,防空转)/ `sharpe_kind` 随产物发布 /
无硬编码绝对路径 / 只写 gitignored 目录 / `nan`·`inf` 不泄漏进 HTML。
均双向验证:还原旧代码时,"未定义参赛"与"nan/inf 泄漏"各条都正确失败。

---

## 附十五:`dna_data/` 层(从未查过),以及**守卫自己的覆盖漏洞**

`dna_data/` 3 个文件 208 行,此前完全没查过。它是**产出引擎所消费的 panel** 的那一层 ——
位置决定了:这一层的前视不是"某个引擎的问题",而是**下游每一个回测的问题**。

**先记合规项**:两个 loader 的 SQL 都有因果上界(`WHERE date BETWEEN ? AND ?`)✓,
`dna_data` 内当前**没有**任何 §1 禁用函数 ✓。

### 1 · §3 **静默跨价域回退**:执行价会悄悄变成复权价

`dna_data/dual_price_resolver.py::execution_open` 的回退链是

```python
for fallback in ("raw_open", "adj_open", "open"):
```

即 `raw_open` 缺失时**先落到 `adj_open`** —— 让**执行**价变成**复权**价。这既违反 §3
("ALWAYS use Raw Prices for evaluating limit order triggers, stop-losses, and
portfolio physical cash mark-to-market"),又与**同一文件里两个兄弟函数**写在注释里的
规则**自相矛盾**:

> `# Signal fallback: skip the OTHER family (avoid raw_close when signal is supposed`
> `# to use adj semantics — they're not interchangeable).`

`signal_close` / `execution_close` 都刻意跳过另一族,**只有 `execution_open` 越界 ——
而它正是入场成交价 / 跳空判定那个最要命的位置**。后果就是本仓库此前抓过的幻影成交:
价格被换到另一个价域,**不报错、不留日志**,只体现为一笔"本该拿不到"的成交。

修:回退链改为 `("open",)`(与 `execution_close` 对称),缺 raw 即 fail-fast。
**目前无生产调用点**(仅有其自有测试)—— 所以这是**潜在陷阱**而非正在发生的错误;
但它存在的意义就是被调用,而它对外承诺的正是 §3 的分域。

这条值得单独记一笔:**同一个文件里的三条回退链,两条守规矩、一条不守。** 读文档
(docstring 写着"Same fallback rule as signal_close")会以为三条一致 —— 只有逐条读
**回退列表本身**才能发现。

### 2 · §1 守卫**自己的覆盖漏洞** —— 缺口是静默的

`tests/test_banned_functions_section1.py` 的 `SCAN_DIRS` 只覆盖

```
四个引擎 + core + dna_stats
```

漏掉的是 **`dna_data`**(以及 `tools`)。这是本轮最"元"的一条发现:**检查器自己也有
覆盖缺口,而覆盖缺口不会报错** —— 它只会让"没被扫到的地方"与"合规"看起来一模一样。

严重性在于位置的组合:`dna_data` 是 panel 的生产者,一个 `bfill` / `shift(-1)` 出现在那里,
会把前视注入**下游每一个**回测,而**这笔账不会被记到任何引擎头上**。

处置:把 `dna_data` 与 `tools` 加入扫描面。实测两者当前都干净 —— 所以这是
**潜在缺口,不是正在发生的违规**;补上是因为守卫的价值在防未来。
`sql/` 未纳入:AstScanner 是 Python AST 实现,**SQL 需要另一套检查**(已登记)。

### 守卫

- **跨价域**:三个解析函数统一钉住"缺本域列必须 `KeyError`,不得改用另一价域",并配
  **对照组**(raw 在场时正常返回 —— 防"全都失败"式空转)。
  反向验证时,只有 `execution_open` 那条失败,另两条本就合规 —— 说明这条守卫定位精准。
- **覆盖**:往 `dna_data` 植入 `df.bfill()` 后守卫**正确失败**,还原后通过。

### 一条贯穿本轮系列的模式

从附五(扫描器的假阳性)到附六(用红灯表达待办)到附十二(测试在 fresh clone 上是红的)
再到本条(**扫描器漏扫了两个目录**),被查出问题的常常**不是被测代码,而是检查工具本身**:

| 检查器 | 它的失效方式 |
|---|---|
| preset→引擎一致性扫描器 | `.get("key")` 盲区 → **假阳性** |
| silent-except 扫描器 | 漏掉 `return None` → **假阴性** |
| §1 禁用函数扫描器 | 漏扫 `dna_data`/`tools` → **覆盖缺口**(静默) |
| 测试套件 | 无库时 fail 而非 skip → **红是常态** |
| DSR 消费脚本 | 分子分母不同源 → **统计结论错** |

**共同点:它们都不会自己报错。** 一个检查器只能证明"我扫过的地方没问题" ——
**它证明不了"我没扫的地方没问题"**,而后者恰好是风险所在。故本报告不只记"哪些代码
违规",也记"哪些地方**从没被看过**"。

---

## 附十六:100 次搜索排完 TOP-K,却**不报任何惩罚指标**

审计 §3.2 的 HIGH 点过 `uptrend_pullback/iter_reverse.py:245`。这一轮逐行核对。

**先纠正审计的表述**(原文不准确):它说该脚本"在**同一窗口**选优并直接报告" ——
实际用的是 `monthly_windows` 的 **22 个滚动窗口**(2 个月窗 / 1 个月步)。
**但实质问题成立**:选优与报告用的是**同一批窗口**,没有任何留出。

### 缺陷

该脚本做默认 **100 次** Monte-Carlo(随机采样 preset → 22 窗口评分 → 按综合分排序 →
打印 TOP-K),而**完全没有** DSR / Bonferroni / n_trials。§5 verbatim:

> "**Penalty Metrics:** Evaluation scripts must output Deflated Sharpe Ratio (DSR)
> or apply Bonferroni corrections when reporting backtest results from
> multi-parameter sweeps."

**同仓库的姊妹脚本 `uptrend_pullback/sweep_v33_long.py` 是有的** —— 这个漏了。
后果不是数字错,而是**读者无法区分**:100 次搜索挑出来的 TOP-K,与"单次评估的结果"
在输出上长得一模一样。

### 修法(不改研究设计,只把**已经做过的选择**如实量化)

- `observed` = **被选中那个配置**的窗口中位 Sharpe(rank-1 那一行)—— 这样它与
  `n_trials = 配置数` 描述的是**同一次选择**(与附十三/十四同一条原则);
- `n_trials` = **实际评分的配置数**(`len(rows)`,而不是 `--iter`:**失败的迭代并没有
  被评分**,把它算进去会虚增折减);
- `n_returns` = 单窗交易日数,取 **21/月** —— 这是**仓库既有口径**
  (walk-forward 家族 6 个月 = 126,即 126 ÷ 6),不是新发明的数;
- 显式打印 **in-sample selection** 警告:DSR 量化的是"从 k 个里挑最好"的虚高,
  **不能替代**样本外验证 —— 要下结论须另跑 `wfv_eval.py` 的 train/test 划分。

### ⚠️ 本轮最该记的一条:**我自己的第一版守卫是空转的**

行为守卫的做法:把搜索桩化,断言输出的 `n_trials` 等于**实际评分的配置数**。

第一版我写的是 `--iter 3`,三次迭代**全部成功** —— 于是 `len(rows) == args.iter`,
把 `n_trials` 从 `len(rows)` 改成 `args.iter` **测试仍然全绿**。
也就是说,那条守卫**根本无法区分它要防的两种口径**,属于本报告反复批评的"空转守卫"。

修正:让 `--iter 4` 中**第 3 次迭代失败**(返回 `error`)→ 实际评分 3 个。
两种口径这才真正可分。修正后,两个错误变体(`n_trials=args.iter` 与
`observed=max(...)`)**都正确失败**。

这与附十五的结论是同一条,只是这次把镜头对准了我自己:
**检查器不会自己报错 —— 它只会安静地通过。** 一条守卫必须先能"在错误实现上失败",
才有资格说"在正确实现上通过"。本轮所有新增守卫都做了这一步双向验证;
而这一条恰恰是**在第一版漏做了这一步之后才发现**的。

---

## 附十七:chase_up 的两个单窗选优脚本 —— 以及"这次我先算再报"

`chase_up/sweep.py` 与 `chase_up/sweep_all.py` 都在**单一窗口**
(`--start 2025-09-19 → --end 2026-09-19`)上给一批配置排序并报 DSR。

### 先记它们**做对了**的部分(经核对,**不是**缺陷)

- `observed = max(sharpes)` 配 `n_trials = len(sharpes)` —— **max 取 k 项、按 k 折减** ✓
  同一次选择(附十三/十四/十六同一条原则);
- `n_returns = 252` —— **核对后确认不是缺陷**:对 **12 个月**窗口而言它等于 `21 × 12`,
  与 walk-forward 家族的既有口径(6 个月 = 126)**一致**。

第二条值得单独说明:上一轮我在 `tools/` 上做过一次**假阳性**(把 `chase_up`/`v1` 当成
死 preset)。所以这一轮看到 `252` 时,先算了 `21 × 12 = 252` 才下结论 ——
**"看起来像缺陷"与"是缺陷"之间隔着一次核对**,而误报的代价是把人引去修没坏的地方。

### 缺的那一步:选优是**样本内**的,而输出里只字未提

§5 要求 "Optimization logic must enforce Walk-Forward Validation (WFV) with strict
out-of-sample (OOS) testing windows"。DSR 量化的是「从 k 个配置里挑最好」带来的虚高,
**不能替代**样本外验证 —— 而本仓库**已经有**滚动窗口版本(`chase_up/wf_sweep_all.py`):

> 读者**没有任何理由**把这个单窗榜当成 OOS 结论 —— 但脚本不告诉他这一点。

修:两个脚本在 DSR 之后各打印一段 **in-sample 声明**(写明"本榜是在单一窗口上从 N 个
配置里选出的"),并**指名**滚动窗口版本与"在未参与选择的窗口上复跑(§5 WFV)"。

### 守卫(6 条,双向验证)

- 两个脚本**都必须**声明 in-sample,**都必须**指向 `wf_sweep_all`;
- **回归守卫**:`observed = max(sharpes)` 与 `n_trials=len(sharpes)` 必须**成对** ——
  只改一半就会退化成附十三那种"max 取 N、按 M 折减"的不匹配;
- **行为守卫**(不只看源码):把预设表与回测桩化,断言警示**真的被打印**。
  测试产物写进 pytest 的 `tmp_path` —— 测试不得往仓库树里落文件(§7 精神)。

反向验证:移除 `sweep.py` 的披露后,两条对应用例正确失败。

### §5 研究层的覆盖面小结

至此已逐行核对的研究脚本:**25 个 sweep/wf/grid + `iter_reverse` + 这 3 个 chase_up 脚本**。
修掉的是四类:

| 类别 | 例 |
|---|---|
| 分子与分母不是同一次选择 | 14 个 WF 脚本、cycle 的 sweep、`iter_reverse` |
| 单位错(收益率当 Sharpe) | `chase_up/wf_sweep_all.py` |
| 完全缺惩罚指标 | `iter_reverse.py` |
| 选优是样本内却不声明 | 本节两个、`iter_reverse` |

**仍未闭合**(已在各附录登记):`cycle` 的 `n_comparisons` 需迭代记录、
4 个脚本引用已删除的 preset、以及原文点名的"窗口跨越已声明的 holdout"
—— 最后这条**需要使用者确认 holdout 边界**才能判定。

---

## 附十八:把"债务"往下推一格 —— 查清由来,并写进脚本自己

附十三把 4 个引用失效 preset 的脚本登记为债务,但**没有回答"能不能修好"**。
这一轮先查清这件事,再决定处置。

### 1 · 是"被删除"还是"被改名"?—— 查 git 史,不猜

`git log -S "<preset 名>" -- short_reversal/presets.py` 给出定论:

- 四个 preset 各自由具名的 `feat(short-reversal): vNN_…` 提交引入;
- 它们**共同**消失于提交 **`4b7eab0`**("iter #2 CLAUDE.md fixes")—— 该提交对
  `short_reversal/presets.py` **减 212 行 / 增 66 行**,是**裁剪**。

**是删除,不是改名。** 故不存在可安全回指的替代名 —— 把脚本改成某个"看起来像"的
preset 就是**编造实验记录**(附十三 §3 已立此规矩)。**登记是对的**,但登记本身
停在"知道它坏了",没停到"知道它为什么坏"。

### 2 · 于是把由来写进脚本**自己**的失败信息

    preset 'v34_mainboard_pctchg_tight' 不在 PRESETS —— 它在提交 4b7eab0 中被裁剪(非重命名),
    本脚本因此无法运行,保留作为研究记录。
      登记: tests/...::KNOWN_DEAD_REFERENCES

查清"删还是改"要翻 git 史,**而这个结论不该由下一个人重查一遍**。
"只说找不到"会让人以为还有救;给出裁剪提交,一句话就说明了"没有可回指的目标"。

### 3 · 为什么**保留**而不是删除

`v41_pctchg_04_10` 当初是作为**单点过拟合失败案例**引入的(见 `0a80f74`)——
被裁掉的那个 preset 本身就是一份**负面证据**。本仓库一贯保留负面证据
(参 v21 的 pinned 块,§7 清理时被明确留下)。故处置是**登记 + 说明 + 保留**,
不是删除。

### 4 · 我又写了一条**空转守卫**(第二次自记)

第一版守卫写的是:

```python
assert PRUNED_IN_COMMIT in src        # 查文件
```

而 `4b7eab0` 这个串在文件里**还出现在我自己的注释中** —— 于是把**失败信息**里的
提交号删掉,**测试仍然全绿**。它验的是"文件里有这个串",而我要验的是"**运行它的人
看得到这个串**"。

改为**执行脚本并检查输出**(`subprocess` + 断言非零退出码 + 提交号与登记名出现在消息里)。
反向验证:再从失败信息中删掉提交号,该用例**正确失败**。

### 系列小结:检查器出错的次数(含我自己的)

| # | 检查器 | 失效方式 | 谁发现 |
|---|---|---|---|
| 1 | preset→引擎一致性扫描器 | `.get("key")` 盲区 → 假阳性 | 我(附五) |
| 2 | silent-except 扫描器 | 漏 `return None` → 假阴性 | 我(附五) |
| 3 | §1 禁用函数扫描器 | 漏扫 `dna_data`/`tools` | 我(附十五) |
| 4 | 测试套件(无库时) | fail 而非 skip → 红是常态 | 我(附十二) |
| 5 | DSR 消费脚本(多处) | 分子分母不同源 | 我(附十三/十四/十六) |
| 6 | 跨价域回退 | 执行价静默变复权价 | 我(附十五) |
| 7 | **我为 `iter_reverse` 写的守卫** | `--iter` 与 `len(rows)` 相等 → 不可分 | **我自己后续复核** |
| 8 | **我为失效脚本写的守卫** | 注释满足断言 → 空转 | **我自己后续复核** |
| 9 | 我对 `tools` 的死 preset 扫描 | 引擎名/版本片段误判 | **我自己复核后撤回** |

**9 条里有 8 条是检查工具本身的问题**,其中 3 条(7/8/9)出自我手。
这解释了为什么本报告的每条修复都附**双向验证**:守卫必须先在**错误实现**上失败,
才有资格说它在正确实现上通过 —— 而这一条,我在本轮**两次**都是补做才发现的。

---

## 附十九:§3.3 的 MEDIUM/LOW(124 条)开始逐条复核

§3.3 是**按主题归并**的 124 条,从审计之后一直没被单独复核过 —— 也就是:它们既没有
被"确认仍存在",也没有被"确认已修"。这一轮起把每一族**对着当前代码**过一遍。

### 复核结果一览(证据基于当前代码,不是照抄台账)

| §3.3 主题 | 现状 | 证据 |
|---|---|---|
| cash_walk 把三池写死为 0(MEDIUM×4) | ch/ut **早已修**;sr **本轮修**;**cycle 仍开** | 见下 §1 |
| 费率常量引擎内重复定义(MEDIUM×6) | **已消失** | 四引擎无本地字面量(仅 `core.dual_price` 定义) |
| `position_fraction`/`max_positions`/`max_volume_participation` 静默丢弃(MEDIUM×3) | **已修** | preset 一致性轮(`b8c1539`) |
| 公司行为按原始价记账、无反向现金事件(MEDIUM×3) | **已修** | 四引擎接入 `core.corporate_actions` |
| §5 DSR 键名 / `n_trials` 口径(MEDIUM×4) | **已修** | 附十三/十四/十六 |
| `dsr['p_value']` 键名使 DSR 行永不输出 | **已修** | 上同 |
| 常量重复与口径不一(LOW) | **部分**:黑名单/golden 内嵌业绩已修;**涨停阈值见 §3** | — |
| §6 信号层发子进程/网络 IO(MEDIUM×3 之一) | **定性不成立**;同处的真实缺陷(**静默放行**)已修 | 附二十九:回测路径传递闭包 40 模块零网络边;`st_filter` 的 fail-open 改为 fail-closed |
| 量比上限在 volume=0/NaN 时整体跳过(MEDIUM×3) | **未复核完** | 下一轮 |
| cycle 每股独立 1,000,000 账户(MEDIUM×1) | 设计未改,**已加口径标注** | 附八 |

### 1 · cash_walk 把三池写死为 0 —— 而"等 H5.1"这个理由**早已过期**

`short_reversal/main.py` 的 cash_walk 把 `locked_margin` / `settling_funds` **写死为 0**,
`free_cash` 填成 `cash`,注释理由是"**等 H5.1 落地三池**"。

**而三池早就落地了**:`replay_strategy_v3.py` 的 `__init__` 里就有
`self.free_cash / locked_margin / settling_funds`,并由 `settle()` 逐 bar 维护。
(`chase_up`/`uptrend` 的同一处已在 P0 轮修好,`short_reversal` 被漏下。)

这是一类值得单独命名的形态:**"登记逾期"** —— 缺口当初被如实地记下来了,但**记录所依赖
的前提已经消失**,而没有任何东西会提醒你。于是注释从"诚实的延期"变成"误导的辩护"。

修:逐 bar equity 行补上三池 → 写者如实落盘 → **缺字段即 fail-fast**(不再补 0)。

### 2 · 一个差点写进去的 P0 回归

第一版我把 NAV 写成 `free + locked + settling + 持仓市值`,注释里引用了
`core.dual_price.portfolio_nav` 作为依据 —— **然后去核对了那个函数**:

```
Canonical NAV = Free_Cash + Settling_Funds + Σ持仓市值      ← **不含 locked_margin**
```

`locked_margin` 是持仓的**成本基础**,`holdings_value` 是同一持仓的**市值**;两者相加会
把仓位计两次 —— **正是审计 P0-1 那个缺陷**(持仓期间权益虚增约一个入场成本,平仓后自动
消失,故只在持仓期间出现、极易漏检)。

**我引用了单源,却没读它的内容。** 改为直接**调用** `portfolio_nav(...)`,不再内联公式 ——
内联就是漂移的起点。这条值得记:引用权威 ≠ 服从权威。

### 3 · 涨停阈值:同值不同源(已修)+ 跨引擎 2 对 2 分歧(**未改**,登记)

`chase_up/replay_strategy.py` 自己写了一份 `prev_close_limit=0.098`,注释称"与
`chase_up/portfolio.LIMIT_UP_THRESHOLD` 一致" —— **注释保证不了任何事**。已改为 import。

但核对时发现更实质的:**四个引擎在这条阈值上分成 2 对 2**:

| 引擎 | 阈值 |
|---|---|
| `chase_up` / `uptrend_pullback` | **0.098** |
| `short_reversal` / `cycle_price_action` | **0.095** |

chase_up 那侧自己的注释称它"**历史** override" —— 有来源、无理由。两个值对同一件事给出
**不同判定**:0.095 会拒绝一些其实可成交的接近涨停的 bar(悲观),0.098 会放过它们(乐观);
§0 的 Pessimistic Default 偏向 0.095 侧。

**本轮不改**:统一到任一值都会改变 chase_up / uptrend_pullback 的**成交列表**(进而要重刷
golden 基线)—— 那是结果变更,须先显式说明漂移,属使用者拍板项。守卫里刻意**不**要求两侧
相等:在说明漂移之前,不该有一侧被悄悄改成另一侧。

---

## 附二十:零成交 bar 上订单**不限量**(§4/§0),以及"规则存在 ≠ 规则被应用"

§3.3 的 MEDIUM×3("量比上限在 `volume=0/NaN` 时整体跳过,fail-open,与 §0 悲观默认相反")
复核确认**成立**。四个引擎都写成:

```python
if bar_vol > 0:                      # ← 这一行
    max_fill = volume_cap_fill(bar_vol, pct, lot_size=100)
    if max_fill > 0 and size > max_fill:
        size = max_fill
```

而 `volume_cap_fill` 对 `bar_vol <= 0` **已经**返回 0(= §4 的
`MIN(Target, Bar_Volume × 0.10)`)。`if bar_vol > 0` 让整段**根本不执行** ——
零成交 bar 上的订单于是不受任何约束。§0 verbatim:"Always assume the worst-case
scenario for market **liquidity**" —— 零成交 / 未知成交量正是最坏流动性,
跳过约束等于假设无限承接。

### "规则存在 ≠ 规则被应用"

契约其实**早有测试钉着**:

```python
# tests/test_short_reversal_volume_cap.py:43-44
"""§4 Edge: bar_vol=0 → fill=0 (no volume = no fill)."""
assert volume_cap_fill(bar_vol=0.0, max_pct=0.10, lot_size=100) == 0
```

也就是说:**助手层的规则是对的、有测试、是绿的**;缺的是**四个调用点照它执行**。
这类缺口在读者眼里最容易漏 —— 搜索"§4 量比上限"会看到规则与测试都在,于是以为没事;
只有去看**调用点的守卫形状**才发现它被整段跳过了。

### 严重度:实测(不猜)

本机行情库 `v_daily` **10,364,755** 行中,`volume <= 0` 与 `volume IS NULL`
均为 **0 行**。故这是**潜在**缺陷 —— 当前数据触发不到,**这也正是它一直没被发现的原因**。
仍然修它的理由:分支的**形状**在原理上就是错的,而"触发不到"只是一份数据快照的巧合 ——
换一份数据(或将来接入停牌/无量标记)就会变成真缺陷。

### 修法

零成交 ⇒ helper 返回 0 ⇒ 订单量归零 ⇒ 由各引擎**既有**的"过小即拒"分支如实拒单
(chase_up/uptrend:`continue`;short_reversal:`size < lot_size` 分支;cycle:`shares < 100`)。
`None` / `NaN` 仍是"面板无 volume 列"的**兼容**路径,且 helper **不能吃 NaN**
(`int(nan)` 抛 ValueError)—— 两者在代码里被明确分开,不再混为一谈。

### 第 10 次"检查器本身出错"(这次也是我自己)

新写的守卫第一版用了一条**宽正则**:`if <vol> > 0:` 一律报错。结果它立刻**误伤**了
同文件里的另一处:

```python
if bar_vol > 0:
    participation = min(1.0, size_pre_cap / bar_vol)
else:
    participation = 0.0          # ← 滑点模型的分母保护,不是本缺陷
```

那是**除法保护**(避免除零),属滑点模型的另一件事。已把守卫改为精确定位:
**从 `volume_cap_fill(` 调用点往回看 5 行**,找包住它的 `> 0` 门。
这与附十四(误把 `chase_up`/`v1` 当死 preset)同型:**判据过宽会把没坏的地方一起报**,
而误报的代价是让人去修对的东西。

### 顺带登记(**未改**)

上一段那处 `else: participation = 0.0` 本身也值得记:当 `bar_vol` 为 NaN(面板无
volume 列)时,**ATR 滑点被静默置零** —— 同样是"未知成交量 → 乐观"的方向。
它与本轮修的是**同一族**(未知量应取悲观),但落在**滑点**而非**下单量**上。
未改的原因:production 面板必有 volume 列(`v_daily` 无 NULL),NaN 只在夹具中出现;
要改需先定"无列"与"零成交"在滑点侧的语义,属另一处口径决定 —— 登记,不顺手改。

---

## 附二十一:§3.3 的 LOW 三条 —— 一条真缺陷、一条已修、一条**不是缺陷**

### 1 · `.gitignore` 只忽略**目录**,不忽略**文件名**(真缺陷,已修)

`.gitignore` 当时有 `results/` 与四个 `<engine>/results/` —— 挡住的是**目录**,
挡不住**文件名**。于是这些产物**仍然可以被提交**:

- `python -m chase_up.main --out .`(产物落到仓库根)
- 手工把 `v5_trades.csv` 复制到别处做对比
- 某个新脚本忘了走 `results/`

而 §7 verbatim:

> "`results/`, trades.csv, metrics JSON, and generated reports MUST remain
> gitignored. **Committing them is a contract violation** — a fresh clone must
> contain zero historical performance claims."

也就是说:**这条要求此前只是"写在文档里",并没有被强制执行** —— 目录级模式让"产物不
入库"看起来有保障,而它只覆盖了产物的**常见位置**,没覆盖产物的**名字**。

修:补一组文件名级全局模式(9 类),并逐条核对不误伤已跟踪文件。
**守卫用 `git check-ignore` 断言"在仓库根也被忽略"** —— 断言的是"这条要求被执行",
不是"这条要求被写下来"。

**守卫又抓到我自己漏的一个**:第一版只写了 `*_metrics.json`,而引擎确实会写**裸**
`metrics.json` —— 新守卫当场报出。这正是"守卫要先在错误实现上失败"的用处:
它在我还没提交时就把我的疏漏抓了出来。

### 2 · 恒真断言 `assert cov >= 0.0` —— **早已修**

P3 轮已改为真断言,原语句留在注释里作记录。顺带核对了另外 5 条 `0.0 <= x <= 1.0`:
它们是 **真**区间不变量(`max_dd` / `win_rate` / `deflated_sharpe` 的定义域),
不是恒真断言 —— **不误报**。(恒真与否取决于**取值如何产生**:`cov` 是
`.notna().mean()`,按构造必在 [0,1],故那条恒真;`max_dd` 是回测算出来的,故那条不恒真。)

### 3 · "WFV 单 asof" —— 核对后**不是缺陷**

`chase_up/walkforward.py` 与 `uptrend_pullback/walkforward.py` 的 `run_windows`
一律用 `windows[0][0]` 取宇宙(注释称"后续窗口逐窗口重载 O(n)",即刻意的性能代理)。

看起来像 §1/§3 的 PIT 违规,但**方向**是关键:

- 宇宙按 `date <= asof_date` 过滤,`asof` 越早 ⇒ 股票越**少**;
- 用窗口 0 的宇宙跑窗口 k,等于**排除**了窗口 0 之后上市的票 ——
  那是**更保守**的一侧,而**不是**前视(没有用到未来信息)。

故它是**已文档化的简化**,不是违规。**登记不改**:改它会影响每个 WF 脚本的结果,
而收益方向是保守的 —— 属"要不要更贴近现实"的取舍,不是"修 bug"。

### §3.3 复核进度(累计)

| 主题 | 结论 |
|---|---|
| cash_walk 三池硬编码 | ch/ut 早已修;**sr 已修**;cycle 仍开(组合级缺口,§8#4) |
| 费率常量重复 | **已消失** |
| 参数静默丢弃 | **已修** |
| 公司行为 | **已修** |
| §5 DSR 键名 / n_trials | **已修** |
| 量比 fail-open | **已修**(附二十) |
| `.gitignore` 文件名级 | **已修**(本条) |
| 恒真断言 | **早已修**;另 5 条经核对为真不变量 |
| WFV 单 asof | **不是缺陷**(保守方向,已文档化) |
| 信号层子进程 | **已闭合**(附二十九:定性不成立 + 静默放行已修) |
| 滑点侧未知量 | **已修**(附三十:成交量未知时参与率改取上界 1.0;潜伏缺陷,100 个 preset 全未开启该路径 ⇒ 零漂移) |
| Phase-2 TP-first、限价守卫判在错误 bar(§4 MEDIUM×4) | **未复核** |

还剩两族没逐条看:§4 的 Phase-2 语义分歧,与 §6 的"条件被第二处复制实现"。

---

## 附二十二:§3.3 **复核完毕**(13 个主题全部有结论)

上一节列的两族也看完了 —— 结论是**两族都不需要改**:

### §4 Phase-2 语义分歧(MEDIUM×4)——**已全部闭合**

审计点名三处,逐条核对:

| 子项 | 结论 |
|---|---|
| Phase-2 用 TP-first tie-break | **已修**(`chase_up/replay_strategy.py` P1-8 改成 SL-first;`uptrend_pullback/replay_strategy.py:128-136` 本来就是 SL-first —— 它只是没写"SL-first"字样,所以按关键词搜会漏) |
| SL/TP 以**绝对价**交给 replay | **审计自己已证伪**(绝对价 = 相对百分比 × 同域入场价,两阶段同域) |
| 限价守卫判在**错误 bar** | **已修**(P1-8:守卫在**成交 bar** 上,比较 `open[j]` vs `prev_close[j]` —— 正确的一对) |

一条教训:该族里"看起来还没修"的两项,一项是**关键词搜不到**(uptrend 没写 SL-first 字样),
一项是**审计自己已经撤回**。核对一条已复核过的族时,最容易的错是**把"没搜到"当成"没修"**。

### §6 "条件被第二处复制实现" —— 是**刻意且已声明**的,登记不重构

`short_reversal/scan_signals_fast.py` 用 pandas **重算**策略的 5 个条件(A/B/C/D/E)。
但它的 docstring **主动写明**了这一点,并且**点名**规范位置:

> 策略的 5 条件 (`replay_strategy_v3.Phase3V3Strategy._all_conditions`): …

动机也写在文件头:引擎是 per-stock cerebro 单跑(慢),这里向量化版本"秒级出结果"。
所以这不是"偷偷的重复实现",而是**明示的快路径**。

**真实风险是漂移**:引擎的条件改了、扫描器没改,于是"先扫一遍候选"给出的名单
与引擎实际会评估的名单**不一致** —— 而扫描器正是给使用者**决定看哪些票**用的。

**为什么本轮不重构**:`_all_conditions(self, d)` 依赖策略实例状态(`self.indi`、
`self._last_sl_date`、以及 backtrader 的 `d`),**不可独立调用**。要加漂移守卫,
先得把 5 条件抽成**纯函数**、由引擎与扫描器共用 —— 那是重构,不是顺手改。
已登记于 §8(7d),并写明推荐次序:**先抽纯函数,再补"两处实现必须给同一结论"的对拍守卫**。

### §3.3 复核最终表(13 主题)

| 主题 | 结论 |
|---|---|
| cash_walk 三池硬编码 | ch/ut 早已修;**sr 已修**;cycle 仍开(§8#4) |
| 费率常量重复 | 已消失 |
| 参数静默丢弃 | 已修 |
| 公司行为 | 已修 |
| §5 DSR 键名 / n_trials | 已修 |
| 量比 fail-open | **已修**(附二十) |
| `.gitignore` 文件名级 | **已修**(附二十一) |
| 恒真断言 | 早已修;另 5 条经核对为真不变量 |
| WFV 单 asof | **不是缺陷**(保守方向,已文档化) |
| §4 Phase-2 语义(3 子项) | **全部闭合**(2 已修 + 1 审计已证伪) |
| §6 条件重复实现 | **已修**(附三十一:假等价声明 ⇒ 不等价即 fail-fast;附三十八:参数改读声明,可信 1→35;**附四十:F/G/H/I/K 落地 + 两级对拍,可信 35→68/75**,余 7 个为原理性不可向量化)。附二十二的『已声明,登记不重构』评级已被更正 —— **声明本身就是缺陷** |
| §6 信号层子进程 | 仍开(§8 7c) |
| 滑点侧未知成交量 | 仍开(§8 7b) |

**8 个已闭合 / 1 个不是缺陷 / 3 个登记待办(需重构或口径决策)/ 1 个是 cycle 组合级缺口。**

---

## 附二十三:§3.2 的 HIGH(64 条)开始逐条复核

同样按族过一遍。第一个族里**一条成立、一条被推翻**。

### 1 · 成立:`final_capital` 抹掉期末未平仓浮盈(已修)

`stop()` 曾只写 `holder["cash"] = self.total_cash`,而 `_metrics_from_holder` 用
`final_capital = holder["cash"]`。但同一次回测里:

| 产物 | 口径 |
|---|---|
| `equity_curve.csv` 末行 `equity` | `nav = self._nav()`(**含**未平仓浮盈) |
| `metrics.json` 的 `final_capital` | `total_cash` = 成本基础 + 已实现(**不含**) |

**两个互相打架的"期末权益",出自同一次运行** —— 又是"同一个量两处定义",这次在
**一个引擎内部**。而 `total_yield` / `cagr` 都由 `final_capital` 推出:
**期末只要还持仓,收益率就是错的**(方向取决于浮盈正负)。

修:`stop()` 增写 `final_nav = self._nav()`;`_metrics_from_holder` 改用它且缺即 fail-fast。
两个数从此出自**同一个** `_nav()`。

> ⚠️ **这是一次结果变更**:凡"窗口末仍持仓"的回测,`short_reversal` 的
> `final_capital` / `total_yield` / `cagr` 都会变。**我未量化其幅度**(需要专门跑
> 一个"末持仓"窗口做前后对比)。既有已发布的 short_reversal 数字需重算后再引用。

**空窗口的边角**(跑测试才发现):5 天窗口全被 warmup 门滤掉 → 策略根本没跑 →
`stop()` 不调用 → holder 无 `final_nav`。此时**空仓 ⇒ 净值 == 初始资金**,
故在 holder 初始化时一并写上 `final_nav = INITIAL_CAPITAL` —— 那是**正确**答案,
不是占位谎言;真有运行时由 `stop()` 覆盖。

### 2 · **被推翻**:`settle()` 只冲刷正值 →"亏损永不回 Free_Cash"

审计原文列的这条,逐行核对后**不成立**:`settling_funds` **只有** `+= amount`
一处写入(`credit_settling`),**恒非负**,`if > 0` 只是避开加 0。**亏损不走这条路径。**

这已经是本轮**第二次**在"已复核过的族"里遇到这种情形(上一次是 §4 Phase-2 的
"绝对价交给 replay" —— 那是审计自己已证伪的)。教训固定下来:

> **核对一条已复核过的族时,最容易的错是把"看着像"当成"有 bug",
> 把"没搜到"当成"没修"。** 每一条都要落到**具体的行**上再下结论。

### §3.2 复核进度

| 族(共 13) | 结论 |
|---|---|
| §3 复权价盯市/NAV门/期末强平(HIGH×4) | 我的 P0 轮已统一到 raw-first `mark_price` ✓ |
| §4 ATR 滑点为 0(HIGH×3) | **声明机制**已修(显式声明 + fail-fast);**取值**仍属研究决策(§8#2) |
| §4 涨跌停只做一半(HIGH×5) | **已修**(P1-8/P1-9 四引擎镜像守卫) |
| §4/§3 Phase-2 语义(HIGH×3) | **已闭合**(附二十二) |
| §2 `settle()`/容量/浮盈(HIGH×3) | **已修**:`final_capital` 取净值;"按字母序成交"复核为**合规**(§2 允许"预定义平局裁决",且参数文档已声明它是 v50 兼容的任意 tie-breaker);**容量上限成立并已修**(附二十七 —— `v58_mp_2` 声明 2 个仓位实开 **24** 个) |
| §2 cycle `settle()` 无调用点(HIGH×2) | **已修**(每 bar 调 `settle()`) |
| §6 守卫空转(HIGH×4) | **已修**(§7 清理 + 测试修复) |
| §5 DSR(HIGH×2) | **已修**(附十三/十六) |
| §7 golden/源码内嵌业绩(HIGH×3) | **已修**(`5c731cd`) |
| §1 窗口边界/宇宙 as-of(HIGH×4) | **已修**(附二十五:非交易日 asof 静默产出空宇宙 → 空集 + 端到端 0 笔/CAGR 0.0000);**并已补完宇宙语义**(附三十三:PIT「已退市」判据曾退化成「当日恰好有 bar」⇒ 停牌票被整窗排除;short_reversal 反向无退市判定 ⇒ 退市票永留宇宙。三引擎现已逐只一致,v19 基线按惯例 repin) |
| §1 停牌/退市按 `entry_price` 盯市(HIGH×1) | **已修**(附二十四;黄金批次零漂移 —— 该窗口从未踩中,故只能靠合成夹具) |
| §4/§0 cycle 入场按决策 bar 记账(HIGH×2) | **成立**:3/4 引擎在下一根 bar 开盘成交,cycle 用**同 bar 收盘**(附二十六)。非 §1 lookahead,是 §0 悲观默认的偏离 —— 改口径=结果变更,**待决策** |

**已闭合 10 / 未复核 0 / 待决策 2(上表 12 行;待决策两项为 §4 ATR 滑点取值、本次 cycle 成交口径)。**


---

## 附二十四 —— §3.2「§1 停牌/退市按 `entry_price` 盯市」(HIGH×1):**成立**,已修

### 1 · 代码事实(逐行)

`core/dual_price.py` 的 `mark_price` 旧签名是
`(pi, j, fallback, price_source_for_execution)`,而两个 pandas 引擎
(`chase_up/portfolio.py` ×3、`uptrend_pullback/portfolio.py` ×3)一律传
`fallback = pos["entry_price"]`:

```python
j = _row_at(pi, day)          # 停牌 / 无数据 → None(它自己的 docstring 就这么写)
px = mark_price(pi, j, pos["entry_price"], price_source_for_execution)
```

`j is None` 时 `mark_price` 返回 `float(fallback)`。而 `cal` 是**面板日期的并集**
(chase_up/portfolio.py:324),循环**会**走到这只股票没有 bar 的日子。三条后果:

1. **盯市价 = 入场价** —— 停牌期内该仓位的浮盈浮亏全部消失,复牌当日再一次性
   跳回:一段真实行情在权益曲线上被抹掉又还回来;
2. **NAV 闸门(§2)拿假净值判断击穿** —— 停牌股让闸门看不见亏损,防穿仓形同虚设;
3. **窗口末日强平按 `entry_price` 成交** —— 既造出一笔现实中不可能成交的
   "≈0 盈亏"交易,又把 §1 明令禁止的 fill 写进成交列表。

§1 原文两句都被违反:「positions in suspended names are marked at the
**last `raw_close`**」以及「**MUST NOT generate fills until trading resumes**」。

### 2 · 暴露面(实测,只读库;黄金窗口 2025-09-19→2026-09-19)

| 量 | 值 |
|---|---|
| universe / 交易日 | 3159 只 / 242 日 |
| 有缺口的股票数 | **299** |
| 缺口 (股票, 日) 事件总数 | **1348** |
| 窗口末日仍无 bar 的股票数 | **10** |
| **黄金批次 13 preset / 216 笔成交里,持仓区间跨越停牌日的笔数** | **0** |

**最后一行是本条最重要的事实,也是本条的方法论教训。** 缺陷真实、数据里天天发生,
但**黄金窗口的成交集合从未踩中它**(入场票都是活跃标的、`max_hold` 又只有 10~18 日)。
于是:

- `tests/golden/*.json` 的 sha256 **修复前后都通过** → **零漂移**,但也**零信号**;
- 真实数据既不能暴露它,也不能回归它 —— **只能靠合成夹具**。

> 又一次:**基线的绿不能替代守卫**。sha256 锁的是"当前代码重跑出的成交列表",
> 而不是"符合 §1 的成交列表";它对**盯市价**完全不敏感(只锁 trades.csv,
> 不锁 equity 曲线)。这与附二十「规则存在 ≠ 规则被应用」是同一条:
> **锁住一个产物的哈希,不等于锁住它背后的规则。**

### 3 · 修法

`mark_price` 不再接受"调用方给的成本价"这个输入 —— 签名改为
`mark_price(pi, day, price_source_for_execution)`:按 `day` 在该股票**自己的**
bar 轴上定位(`bisect`,保持模块零外部依赖),缺 bar 就**向前回退到最后一个可用
收盘价**(raw-first,raw 缺失回退该行复权价)。一根 bar 都没有 ⇒ fail-fast
(持仓必然至少有一根 bar,静默回退没有一句话说得通)。

末日强平增加跳过分支:当日无 bar ⇒ **不强平**,持仓留在 `positions` 里,
不入成交列表,而净值仍按 last raw_close 计入。为此:

- 两个引擎的该分支都 `logger.warning`(不静默吞掉);
- §2 的现金恒等式随之**一般化**为
  `equity = 初始 + Σ已实现 + Σ分红 + (持仓市值 − locked_margin)` ——
  全平仓时退化为原来的形式。`holdings − locked_margin` 恰好就是未平仓仓位的
  净贡献(入场时 free→locked 转出的是 `size×entry+fee`,而 locked 不属于 NAV),
  故不需要新增产物字段,`tests/test_nav_cash_ledger_invariants.py` 的守恒式即已覆盖。

### 4 · 双向验证(两个方向都验了"守卫真的会红")

| 方向 | 手段 | 结果 |
|---|---|---|
| 盯市 | 把旧语义 monkeypatch 回去(夹具里入场日收盘 == 入场价,故"回退到首根 bar 收盘"精确复现旧数值) | 三个停牌日 `holdings = 999,000`(= size×10),而修好后是 `1,198,800`(= size×12)→ 断言必然 red ✓ |
| 强平 | 临时删掉跳过分支,跑守卫 | 2 red(`test_position_still_halted_at_window_end_is_not_force_closed` + chase 的结构守卫),8 仍绿 → 恢复后全绿 ✓ |

新增 `tests/test_suspension_mark_and_no_fill.py`(行为层端到端 chase_up + 单元层
`mark_price` + 结构层两引擎),`tests/test_nav_cash_ledger_invariants.py` 的三处
调用迁到新签名并补"缺 bar 向前回退 / 无 bar fail-fast"。

夹具本身也踩过一次坑并修正:**第一版 `_panel` 用 `continue` 跳过停牌日时,
把"作为日历锚点的另一只股票"的 bar 一起跳过了** —— 于是日历里根本没有停牌日,
前提被静默破坏。已改为无条件先追加锚点股票的 bar。**夹具也是代码,也要守自己的前提。**

### 5 · 结果影响

- 黄金批次(13 chase preset + uptrend 全量 sha256 基线):**零漂移**(修复前后均通过),
  原因见 §2 —— 该窗口内没有任何持仓跨越停牌日;
- 因此本次修复**未改变任何已发布结果**,但**移除了一条真实可达的错误路径**;
- 窗口末持有停牌股的窗口(数据里存在,黄金批次里没有)从此不再产生假成交。

### 6 · 同族但**另行登记**的项(不并入本次修复)

`pos["bars"] = t - pos["entry_t"]`(两个引擎同形)按**日历 bar 序号差**计持仓时长,
而非按"实际存在的交易日"计。停牌 30 天会让 `bars` 虚增 30 ⇒ 复牌当日立刻触发
`max_hold`/`time` 出场,`hold_days` 也随之为日历口径。§1 的原话是针对指标滚动窗口
的("count trading days actually present"),但同一原理可推及持仓时长。
**不并入本次修复的理由**:它会改变 `hold_days` 的定义与所有 time-exit 时点,
属**研究决策**(怎么给停牌期计时),与"缺 bar 不得按成本价盯市"这种明确的契约违反
不同类。已登记,待评估。

---

## 附二十五 —— §3.2「非交易日 as-of 静默产出空宇宙」(§1 窗口边界/宇宙 as-of 行的最后一项):**成立**,已修

### 1 · 缺陷

`chase_up/universe.py` 的 PIT 查询把 as-of 字面值同时用在**两侧**:

```sql
WHERE date <= ?   GROUP BY thscode   HAVING MAX(date) >= ?    -- [asof, asof]
```

asof 一旦落在**非交易日**,对**每一只票**都有「最后一个交易日 < asof」⇒
`HAVING` 全不成立 ⇒ **空集**。而 `load_universe` 静默返回 `[]`,回测照跑。

### 2 · 实测(live DB,`mainboard_only`)

| asof | chase_up | uptrend_pullback(早已是正确形式) |
|---|---|---|
| 2026-01-09 周五 | 3167 | 3167 |
| 2026-01-10 周六 | **0** | 3167 |
| 2026-01-11 周日 | **0** | 3167 |
| 2026-10-01 国庆 | **0** | 3187 |
| 2026-01-09 / 01-10 / 10-01(short_reversal) | 3176 / 3176 / 3196 —— **不受影响** ✓ |

端到端(同一 preset `chase_v10_...`,**只把窗口起点从周五挪到周六**):

| 窗口起点 | 成交 | 期末权益 | CAGR |
|---|---|---|---|
| 2026-01-09(周五) | 11 笔 | 1,425,981.91 | 0.6277 |
| 2026-01-10(周六) | **0 笔** | 1,000,000.00 | **0.0000** |

危害不在"跑出 0 笔",而在**它长得像一个有效结果**:回测正常结束、产物齐全、
`cagr = 0.0000` 是一个合法数字,于是会被 `run_all_presets` / `sweep` 之类的
下游聚合当成一个真实样本计入均值与 DSR 的 trial 集合。§0 的 Fail-Fast 要的正是
把这种输入错误变成异常,而不是变成一个安静的数字。

### 3 · 修法

1. **查询**:两侧都锚到「asof 当日或之前的最后一个交易日」——
   `(SELECT MAX(date) FROM v_daily WHERE date <= ?)`,与 `uptrend_pullback` 对齐
   (该引擎早已是此形式,`last_td` 在交易日上恒等于 asof,故交易日行为不变)。
2. **空集 fail-fast**:过滤后为空即抛 `ChaseUpError`(镜像 uptrend 的同款守卫),
   不再静默返回 `[]`。

### 4 · 本条的方法论教训:**修一处 ≠ 修一族**

`uptrend_pullback/universe.py` 早已是正确形式,而且**带着一段专门解释这条缺陷的注释**
(「否则 `HAVING MAX(date) >= asof` 在 asof 是周末/节假日时对每只票都不成立 …
→ 空集 → 回测静默产出 0 笔交易」);`chase_up/universe.py` **一字不差地保留着旧形式**,
连注释都停在旧认知上。

这与附二十四的 `mark_price`、以及审计中反复出现的形态是同一条:
**同形代码散落在多个引擎里时,任何一个引擎的修复都不会自动传播** ——
而且"注释里写着已修"是最容易让人跳过核对的一种信号。所以:
**凡是"某个引擎已经修过"的族,必须逐个引擎点名核对,而不是看到一处正确就收工。**

### 5 · 双向验证

把查询改回字面值形式 → 新增 `tests/test_universe_asof_non_trading_day.py` **7 red**
(行为层周末/节假日两条、跨引擎不变量三条、结构层 chase 一条),其余 3 条仍绿;
恢复后 10 全绿。该文件同时钉住"同一 asof 下两个引擎必须给出同样大小的宇宙" ——
这条不变量正是本缺陷的形态:**同一个查询两处两种写法,一边有一边没有**。

### 6 · 另行登记(不并入本次修复)

`short_reversal/load_universe_asof` 的查询形如 `date <= ?`(无 `HAVING`),
**故非交易日 as-of 不受影响**(上表已实测)。但它同样**没有空集守卫**:
asof 早于数据覆盖起点时会静默返回 `[]`、回测静默 0 笔。这与 chase_up 那条的
**成因不同**(覆盖不足 vs 非交易日),不影响本次结论,故另行登记而非顺手改 ——
避免把两种不同的失效原因混成一次改动。

---

## 附二十六 —— §3.2「cycle 入场按决策 bar 记账」(§4/§0 HIGH×2):**成立**;属**未声明的跨引擎约定分歧**,待决策

### 1 · 事实(四个引擎的成交时点对照)

| 引擎 | 信号取自 | 成交价 | 代码位置 |
|---|---|---|---|
| `chase_up` | `cal[t-1]` | `raw_open[j]` @ bar t | `portfolio.py:517`(信号)→ 入场用当日开盘 |
| `uptrend_pullback` | `cal[t-1]` | 同形,bar t 开盘 | `portfolio.py:475` |
| `short_reversal` | T 日 close | 「**T+1 日 open 成交**(cheat-on-open 模式)」 | `replay_strategy_v3.py:5, 712` |
| `cycle_price_action` | **bar T** | **`bar_exec.close`(同一根 bar 的收盘)** | `backtrader_engine.py:275-283` |

即:**3/4 个引擎在"下一根 bar 的开盘"成交,cycle 在"决策 bar 自己的收盘"成交。**
cycle 的 `try_enter(..., bar_exec.close, ...)` 与同一函数里的涨停守卫
`is_limit_up(prev_close=close[T-1], open_price=bar_exec.close)` 一起看,语义是自洽的
(在收盘封板时买不到),但它的成交价与决策所用的是**同一根 bar 的同一个价格** ——
决策与成交之间**没有任何不利波动的窗口**。

### 2 · 性质判定:不是 §1 的 lookahead,而是 §0 悲观默认的偏离

- **不构成 §1 未来函数**:决策与成交用的是同一根 bar 已实现的价格,没有引用 `t+1` 的信息,
  `data[timestamp <= as_of_time]` 的切片规则未被违反;
- **构成 §0 Pessimistic Default 的偏离**:§0 原文要求「Always assume the **worst-case
  scenario** for market liquidity, **execution price**, and statistical significance」。
  同 bar 收盘成交是执行价的**最乐观端点**(等于"在收盘那一刻同时决定并成交"),
  而 §1 的 `AsOf` 规则本身也在暗示决策发生在 bar 结束后。三个姊妹引擎一致选下一根
  开盘,cycle 单独选同 bar 收盘 —— 二者在跨引擎比较时会给出系统性偏向 cycle 的数字。

### 3 · 为什么不擅自改

改成交口径(同 bar 收盘 → 下一根开盘)**会改变 cycle 的全部已发布结果**,属结果变更,
与"缺 bar 按成本价盯市""非交易日 asof 出空宇宙"这类**明确的契约违反**不同类。
按本轮一贯的处置(**契约违反就修;结果变更先登记**),本条登记为待决策。

待决策的具体问题:**cycle 是否改为与其余三引擎一致的"下一根 bar 开盘"成交?**
(若改,需要重跑 cycle 的全部基线并与旧结果对照;若保留,应在产物里显式声明
`execution_convention = "same_bar_close"`,以免跨引擎比较时被误读。)

> 注:**我未在本次改动中给 cycle 的产物加 `execution_convention` 字段。** 理由:
> 口径尚未决定,先落一个字段等于把**现状**固化成"声明过的正确值"。等 §3 的决策落地后
> 再一并加,那时它声明的才是**应当**的口径。(这与本审计反复强调的"声明必须可兑现"
> 是同一条 —— 现在加,只能兑现一个我不认为是终态的约定。)

### 4 · 双向验证(可复核的判据)

本条的证据是**四个引擎的信号 bar 与成交价来源的对照表**(§1),可用
`grep -n "sigs_by_day.get(cal\[t - 1\]" chase_up/portfolio.py uptrend_pullback/portfolio.py`
与 `grep -n "try_enter" cycle_price_action/backtrader_engine.py` 一次性重现;
`tests/test_limit_up_guard_cross_engine.py` 已锁四引擎的涨停守卫同源,
但**尚未**有一条守卫锁"成交时点约定"—— 因为约定未定,锁什么都是错的。

---

## 附二十七 —— §3.2「§2 容量上限」(HIGH):**成立**,已修 —— 声明 2 个仓位,实际开到 24 个

### 1 · 缺陷

§2 原文:「Capacity is bounded by the preset's `max_positions`; signals beyond
capacity at time T MUST BE **IMMEDIATELY DISCARDED** (no queueing into T+1).」

`short_reversal/replay_strategy_v3.py::_fill_pending_entries` 只有**经济约束**:
每笔按 `free_cash / max_positions` 下注,现金耗尽即自然停下。但该公式**每笔都重算**,
于是份额几何衰减(F/N, F/N², F/N³, …)—— 现金几乎永远不耗尽,容量约束形同虚设。

### 2 · 实测(只读库;区间扫描:entry +1 / exit −1 求最大并发持仓)

| preset | 声明 `max_positions` | 实测峰值并发(全年 2025-09-19→2026-09-19) |
|---|---|---|
| `v58_mp_2` | 2 | **24** |
| `v58_mp_3` | 3 | **33** |

**声明的容量与实际风险敞口差一个数量级。** 这两个 preset 的实际形态是"几十个小到
忽略不计的仓位",而它们的名字与声明的含义是"2 个 / 3 个等分仓位"。

### 3 · 为什么这不是一次口径选择

本仓库**已经书面写下**该契约(`tests/test_claudemd_full_audit.py:12-18`):

> 「…多仓时每个 slot 的预算是 free_cash/max_positions,**合计仍是 100% 部署**,
> 没有 §2 禁止的『开仓前预留现金缓冲』。」

实现既没做到"合计 100%"(几何衰减),也没做到"容量受约束"。故本修复是把实现拉回
仓库自己声明的契约,而不是替谁选口径。

**族内不对称(第三次)**:`chase_up/portfolio.py:563` 与
`uptrend_pullback/portfolio.py:512` 都有显式的
`if len(positions) >= max_positions: break`;只有 `short_reversal` 缺。
前两次是附二十四(停牌盯市)与附二十五(非交易日 asof)——
**同一个模式已经出现三次**:一条规则在 3~4 个引擎里各写一份,于是修复永远只覆盖
"我这次看到的那一份"。这已不是巧合,而是一种系统性的维护风险。

### 4 · 修法

1. **显式容量闸门**:`len(self._holds) >= max_positions` ⇒ 丢弃本 bar 剩余信号
   (`pending.pop(...)`)并 `break`,与两个姊妹引擎同形;日志按本文件既有的
   `_cash_gate_logged` 惯例只报首次(实测 3 个月窗口触发 30+ 次,逐次刷会淹没输出);
2. **sizing 分母改为"剩余未占用的 slot 数"**:
   `free_cash × position_fraction / slots_left`,使 N 个 slot **等分**且**合计 100% 部署**。
   `max_positions == 1` 时 `slots_left ≡ 1`,与该分支此前的行为**逐字相同**。

### 5 · 双向验证

把闸门与 sizing 分母两处一起撤回 ⇒ `tests/test_short_reversal_capacity_gate.py`
**5 red / 2 green**(red: 两个 preset 的行为层 + 三条结构层;green: 未受影响的
chase/uptrend 结构守卫);恢复后 7 全绿。行为层在**缺陷态**下确实会红(3 个月窗口
两 preset 均超容量),故这条守卫是**两向有牙**的。

### 6 · 结果影响(**这是一次大结果变更**,必须登记)

窗口 2026-06-01→2026-08-31:

| preset | 声明 | 峰值并发 前→后 | 成交 前→后 | CAGR 前→后 |
|---|---|---|---|---|
| `v58_mp_2` | 2 | **22 → 2** | 160 → 29 | +0.7576 → **+1.0188** |
| `v58_mp_3` | 3 | **31 → 3** | 185 → 42 | +0.5975 → **+0.7488** |

74 个 `max_positions == 1` 的 preset **零漂移**(公式在该分支恒等)。
但**这两个已发布的 preset 数字必须重算后再引用**。

### 7 · 守卫的运行代价(需要知悉)

行为层用例每次要真跑两个 preset × 3 个月窗口(实测约 **5.5 分钟**)——
占全套件(19 分钟)近三成。它的价值在于:这是唯一能发现"容量未被约束"的手段
(结构守卫只能发现"闸门被删",发现不了"闸门写错了"例如误用常数上限)。
若日后觉得太慢,可缩窗口,但**必须先在缺陷态验证缩短后的窗口仍会红**,否则守卫
会退化成永远绿。

---

## 附二十八 —— §4 的两条"守卫自身"遗留项(S2 / S3):**均成立,均已修**

§4 里唯二标着**未修复**的条目,本轮逐行核实后两条都成立并已修。它们不在引擎里,
而在**验证层**:这一类缺陷的代价比引擎缺陷更高 —— 它让其余所有"绿"失去可验证性。

### S3 · 扫描器静默跳过不存在的文件 ⇒ 覆盖率是假的

实测确认(本轮,当前代码):

- `PRODUCTION_FILES["short_reversal"]` 列了 `short_reversal/portfolio.py` ——
  该文件**不存在**(本策略的引擎是 `replay_strategy_v3.py`);`ls` 直接 not found;
- 而扫描器写的是 `if not path.exists(): continue`(静默跳过)⇒
  **"清单里有它"与"真的扫了它"不可区分**,不可变性守卫对 short_reversal 的覆盖
  比它宣称的少一格,而且任何一次文件改名/笔误都会**悄无声息地**再削掉一格;
- 同一函数里还有第二处静默降级:`except (SyntaxError, OSError, UnicodeDecodeError): continue`
  —— 一个解析不了的文件会被当作"无违规"。

这正是 §0 Fail-Fast 的直接违反,也是本次审计反复出现的"缺口靠沉默存在"。

**修**:清单只列真实存在的文件;缺失即抛、解析失败即抛(不再降级);
新增 `test_production_file_list_has_no_dead_entries` 把"清单即覆盖声明"这件事钉住。

### S2 · 不可变性守卫可被一行别名绕过,且**源码注释明说这是为了绕过它**

实测确认(当前代码,`short_reversal/replay_strategy_v3.py`):

```python
# Local alias preserves runtime semantics while satisfying AST detector in
# tests/test_immutable_state_4engine.py.
holds = self._holds
pos = holds.pop(code)
```

1. 扫描器只认 `self.<attr>.<method>(...)`,所以上面这一行**完全不报**;
2. 注释**直接承认**规避意图 —— 这让"该测试通过"不再具备任何含义;
3. 而且这种写法会**自我传播**:我本轮新加的容量闸门里,我照着本地惯例也写了
   `pending = self.pending_entries`(共 7 处),而不是写成直调。一个被承认的
   绕行写法,会被后来者当成"本仓库的写法"继续复制。

**修(两半,缺一不可)**:

- **守卫侧**:扫描器新增 `_aliases_to_self_attrs()`,把 `alias = self.<attr>`
  解析回来 —— 于是 `<alias>.<method>()` 与 `self.<attr>.<method>()` 受**同一条**
  豁免规则约束。豁免按**属性**判定,不再按**书写形式**判定。
- **代码侧**:不再绕。`_holds` 的移除改为**重建**
  (`self._holds = {c: p for c, p in self._holds.items() if c != code}`)—— 语法本身
  即合规,也不再有需要解释的注释;7 处 `pending_entries` 别名全部改回直调
  (`pending_entries` 早已由 `TRANSIENT_CONTROL_STATE` 显式豁免,别名**本来就没有必要**,
  它只是旧限制的遗迹),"为满足检测器"的注释全部删除。

### 顺带修正:一处**注释与代码相矛盾**

`_fill_pending_entries` 的 NAV 闸门分支,原注释写「拒绝所有 pending entries
(**保留在 pending 让下一根 bar 重新评估**)」,而紧接着的代码是 `pending.clear()`。
按 §2(超容/被拒的信号**立即丢弃**,不得排队到 T+1),**清空**才是正确行为 ——
故是注释错、代码对。已按实际语义改写(这类"注释说 A、代码做 B"是下一次误修改的种子)。

### 双向验证

| 方向 | 手段 | 结果 |
|---|---|---|
| 守卫**失明** | 把旧扫描器(静默跳过 + 不解析别名)还原 | 3 red(`detects_aliased_mutation` / `fails_fast_on_missing_file` / `fails_fast_on_unparseable_file`)、其余 8 绿 ✓ |
| 代码**确实违规** | 先加固扫描器、再跑(改代码之前) | 当场点名 `('replay_strategy_v3.py', 1090, 'holds→self._holds', 'pop')` —— 即旧写法在**会解析别名的**扫描器下必然红 ✓ |

### 仍未覆盖的边界(据实声明,不假装完整)

扫描器只查**破坏性方法调用**(`pop`/`clear`/`update`/`discard`/`remove`);
`self.<attr>[k] = v` 这类**下标赋值**不在射程内(`self._holds[code] = {...}` 即属此类)。
这是**范围声明**,不是遗漏 —— 各用例 docstring 均据实如此表述,且
`_scan_self_mutation` 的 docstring 里也写明了这条边界。若要覆盖下标赋值,
需要另一套判据(否则会把每处合法的字典更新都判成违规),留待后续。

---

## 附二十九 —— §3.3「§6 信号层发子进程/网络 IO」:**定性不成立**;但同处有一个真实的 §0 缺陷(已修)

### 1 · 台账的定性被推翻:回测路径根本不触达它

台账把本项记为「§6 信号层发子进程/网络 IO(MEDIUM×3 之一)」,依据是
`short_reversal/st_filter.py:44` 用 `subprocess`。逐条核对后**不成立**:

- `st_filter` 只被 `scan_signals.py:145` 与 `scan_signals_fast.py:161` 引用 ——
  两个**实时信号扫描工具**,不是 §6 定义的 Strategy;
- 用**传递闭包**核对(四个回测入口 `short_reversal.engine` / `chase_up.backtest` /
  `uptrend_pullback.backtest` / `cycle_price_action.backtest` 出发,解析仓库内 import):
  可达 **40** 个仓库模块,**没有一条边**通向 `subprocess` / `requests` / `urllib` /
  `socket` / `st_filter`。§6 的「Strategy … has no network/DB access」在回测路径上成立。

这与本轮已经出现过的形态相同:**台账的措辞比事实重**。前例是 §4 Phase-2 那族(附二十二
逐条看完后"两族都不需要改"),以及 §1 的"settle() 只冲刷正值"。核对已复核过的族时,
**最容易被措辞带走** —— 每条都要落到具体的边/行上。

### 2 · 但那个文件里确有一个 §0 缺陷:**风险过滤器静默放行**

```python
name_map = _fetch_name_map(codes)          # 失败即 continue,返回拿到的那部分
st_codes = {c: ... for c in codes if _looks_like_st(name_map.get(c, ""))}
                                          # 取不到 ⇒ "" ⇒ 判定为"非 ST" ⇒ 放行
```

CLI 不在 / 超时 / 返回非 JSON / `ok=false` / `thscode` 不匹配时,`name_map` 为空或残缺,
过滤等于没跑 —— 而**输出与"跑过且没有命中"完全同形**。一个**风险控制**输入以
"没查出问题"的形式失效,方向与 §0 的 Pessimistic Default(「Do not silently bypass」)
正好相反。这与本仓库已修的同形缺陷同类:`chase_up/universe.py` 的黑名单
「文件不存在静默返回空集 ⇒『要排除 29 只』与『排除了 0 只』不可区分」。

### 3 · 修法

任何一只取不到名称即抛 `STFilterUnavailable`。要在无过滤下出结果,必须**显式**传
`--include-st`(两个实时入口都已有该开关)—— 把"放弃风险检查"变成一次明确操作。
注入点在 `_fetch_name_map` 这一层,故**回测路径完全不受影响**(见 §1 的传递闭包结论)。

同时把一条**PIT 偏离**写进模块 docstring(据实声明,不假装安全):名称取自**当前**时点,
故对历史的 `--signal-date` 而言,本过滤用的是"今天"的 ST 状态而**不是**该信号日的状态
—— 它不是 point-in-time 过滤。回测的 PIT 过滤在 `short_reversal/universe.py`,
不走本模块,故回测 universe 不受此影响。

### 4 · 双向验证

| 方向 | 手段 | 结果 |
|---|---|---|
| 旧行为 | 还原"静默 continue + 返回部分结果" | `test_st_filter_fails_closed.py` **4 red / 4 green**(red 恰为四条"失败必响") |
| 新行为 | 恢复 | 8 全绿 |

**另做了真实端到端核对**(改 fail-fast 最怕把运维工具打死):以真实 CLI 对 5 只真实代码
(沪深各半)调用,全部解析成功,`*ST萃华` 被正确剔除 ⇒ 正常路径未被破坏。

**并为 fail-fast 配了逃生门守卫**:`test_both_entry_points_offer_an_explicit_opt_out`
断言两个入口都有 `--include-st` —— 没有逃生门的 fail-fast 会被运维用"改代码绕过"的方式
绕开,那时守卫就真的失效了。

---

## 附三十 —— §8 #7b「滑点侧未知量」:**成立**,已修(潜伏缺陷,实测零漂移)

### 1 · 缺陷

三个引擎算滑点参与率时写着同一条分支:

```python
if bar_vol > 0:  participation = min(1.0, size_pre_cap / bar_vol)
else:            participation = 0.0        # ← NaN(面板无 volume 列)也走这里
```

而 `core.dual_price.effective_slippage` 的**唯一口径**是

    slip_eff = max(static_slippage, atr_pct × participation × scale)

取 `participation = 0.0` ⇒ `slip_eff = static_slippage`(本仓库多为 0)⇒
**恰好在流动性未知处把滑点归零**。方向与 §0(「Always assume the worst-case
scenario for market liquidity, **execution price**」/「Do not silently bypass」)
相反:拿不到成交量的时候,引擎反而假设自己毫无市场冲击。

可达路径只有一条:**面板无 `volume` 列**(LEFT JOIN miss ⇒ NaN,量比闸门对 NaN 跳过)。
零成交(`bar_vol <= 0`)在量比闸门已被拒单,到不了这一行 —— 修附二十时确认过。

| 引擎 | 站点 |
|---|---|
| `chase_up/portfolio.py` | 第 656 行(旧) |
| `uptrend_pullback/portfolio.py` | 第 591 行(旧) |
| `short_reversal/replay_strategy_v3.py` | 第 824 行(旧) |

### 2 · 修法

`participation = 1.0` —— 模型定义域的上界(假设自己吃掉整根 bar 的成交量),
即该模型能表达的最坏冲击。

### 3 · **这是一条潜伏缺陷**(据实说明,不夸大)

`atr_slip_scale` 是 opt-in,而实测 **100 个 preset 全部为 0**(chase_up 0/22、
uptrend_pullback 0/3、short_reversal 0/75)⇒ 整条 ATR 滑点路径在当前配置下
**不可达**,本次修复**零漂移**。

仍然要修的理由:§8#2 登记的「ATR 滑点取值」是一个**待决事项**。一旦有人按 §4 的
要求把 `atr_slip_scale` 打开(§4 原文:「Execution slippage MUST be modeled
dynamically as a function of the asset's current ATR and the order's participation
rate」),他会在**流动性未知**的地方拿到零滑点 —— 这是给那个决定预埋的坑。
**先填坑,再谈取值**,那个决定才是安全的。

> 顺带记录一条本轮的元观察:`atr_slip_scale` 全为 0 这件事本身说明 —— §4 的
> 动态滑点条款目前**在所有已发布 preset 上都未被启用**。这不是代码缺陷(机制已
> 单源且缺声明即 fail-fast),而是 §8#2 那个待决事项的另一面:机制就绪,**取值待定**。

### 4 · 双向验证

三处一并还原为 `participation = 0.0` ⇒
`tests/test_unknown_volume_slippage_is_conservative.py` **4 red / 1 green**
(red:行为层 + 三条结构层;green:成交量充裕的正路径,本就不该受影响);恢复后 5 全绿。

行为层断言直接读成交价:`slip_eff = 0.02 × 1.0 × 0.5 = 1%` ⇒ 成交价必须等于
`open × 1.01`,且**不得**等于 `open`(后者正是 participation=0 的结果)。
夹具刻意用 `equal` sizing + 2 个 slot:all-in 时 1% 滑点会把订单顶出 `free_cash`
而被现金闸门拒单 —— 那是另一条**正确**行为,却会掩盖本用例。

---

## 附三十一 —— §8 #7d「条件被第二处复制实现」:**成立**,已修(并更正附二十二的评级)

### 1 · 缺陷

`short_reversal/scan_signals_fast.py` 是引擎入场条件的**第二处实现**。它把
E/A/B/C/D 的**参数写死在代码里**(`_filter_signals` 里直接写 `3e7/3e8`、`3/10`、
`0.6`,`d_mode` 只实现 `'strict'`),**不读 preset 的同名声明**;不实现引擎会评估的
F/G/H/I/J/K 与市场波动宽度开关;也不评估多腿集成(`ensemble_substrategies`)。

而模块 docstring 宣称:

> 结果与策略 **100% 等价**(LAHEAD-001 信号层 vs 执行层已经解耦)。

### 2 · 实测(75 个 preset)

| 偏离原因 | preset 数 |
|---|---|
| 启用本器未实现的入场开关 | 37 |
| 基础参数被写死(声明值不同) | 71 |
| ├ `d_mode` | 70 |
| ├ `below_ratio_60` | 70 |
| └ `close_ma60_buffer` | 70 |
| ├ `up_streak_low` / `up_streak_high` | 各 2 |
| ├ `liq_low` / `liq_high` | 各 2 |
| └ `a_condition` | 1 |
| **结论不可信合计** | **71 / 75** |

可信的只剩 `v35_agg_pctchg_04_09` 一个。(附二十二当时列的 4 个"可信"里,有 3 个是
`v63_ensemble` / `v64_ensemble_3leg` / `v79_ens44` —— 本器**根本不评估** ensemble。)

对**实时交易**工具而言,多报的信号就是要下单的票 —— 方向错误比不出结果更糟。

**而且这不是"实现漏了"**:`sl_cooldown_days`(J)取决于**运行历史**的 SL 出场时点、
市场宽度取决于当日全市场 —— 二者都是**路径依赖**的,单行向量化扫描**原理上**
无法复现。故这条路径对它们**永远不可能**等价,只能拒绝。

### 3 · 修法

`_scan_preset` 在 `get_preset` 之后立即 `_assert_fast_path_equivalent(cfg, name)`:
不等价 ⇒ 抛 `FastScannerDivergence`,消息里**逐条列出**原因并指向
`python -m short_reversal.scan_signals`(构造真实 `Phase3V3Strategy`,与回测走同一条
条件路径,只是慢)。docstring 的等价声明改为精确范围。逃逸面被钉成三个显式清单:
`UNSUPPORTED_ENTRY_SWITCHES` / `BAKED_IN_PARAMS` / ensemble。

守卫**同时**钉住"可信集合恰好是已知快照"(`KNOWN_FAITHFUL`):既防它变成永远拒绝
(那种绿是真空的绿 —— 附二十"规则存在 ≠ 规则被应用"的镜像),也防有人扩大适用范围
而未在此处留痕。

### 4 · 更正附二十二的评级(重要)

附二十二把本族记为「刻意且**已声明**,登记不重构」,并给出了不重构的理由
(`_all_conditions` 依赖策略实例状态,不可独立调用)。**家族找对了,评级不对**:

> 声明本身**就是缺陷**。它宣称的等价**今天就不成立**(71/75),不需要等到"将来漂移"。

而且修它**不需要那个重构** —— 只需要让工具停止宣称自己不具备的性质。重构(把 5 条件
抽成纯函数、两处共用)仍然是让快路径对另外 74 个 preset 可用的**前提**,继续登记于 §8#7d,
但那是"扩大适用范围"的功能工作,与"别再给错名单"的正确性修复不是一件事。

> 这是本审计第四次出现同一形态:**核对一条已复核过的族时,把"已声明"当成"没问题"**。
> 前三次分别是"settle() 只冲刷正值"、"Phase-2 自由裁量"、"非交易日 asof"。
> 一条声明要能站得住,必须能被**逐条核到代码**上 —— 否则它只是一个更贵的沉默。

### 5 · 双向验证

删掉 `_scan_preset` 里的闸门调用 ⇒ `tests/test_fast_scanner_equivalence_gate.py`
**5 red / 4 green**(red:五种偏离情形;green:快照与非空断言);恢复后 9 全绿。

### 6 · 一条自我教训(第三次踩同一个坑)

本轮连续三次被"守卫的字面量断言命中**我自己写的历史说明**"绊倒:S2 的
`"AST detector"`、容量守卫的 `pending.pop(`、这次的 `"100% 等价"`。
引用旧文本做变更说明本身是好习惯(它让后来者知道缺陷曾经存在),但它与
子串型守卫**天然冲突**。结论:**子串守卫只能针对"当前声明",不能针对"历史叙述"**;
二者要共存,就得让历史说明改述(或让守卫升级为结构性判定)。

---

## 附三十二 —— §5 的两处**输入口径**:DSR 年化常量不同源、观测数被硬编码(均**成立**,已修)

### 1 · (a) 年化常量:引擎 243,`dna_stats` 252

`deflated_sharpe_ratio` 的第一件事是把 `observed_sharpe` **除回逐期**:

```python
sr = observed_sharpe / math.sqrt(trading_days_per_year)
```

所以消费者用的常数**必须**等于生产者算它时用的常数。而:

| 层 | 常数 | 位置 |
|---|---|---|
| 引擎(`chase_up` / `uptrend_pullback` 的 `sharpe`) | `mean/std × sqrt(243)` | `core.trade_schema.TRADING_DAYS_PER_YEAR` |
| `dna_stats`(消费者) | **252** | `deflated.py:84/111/230`、`walkforward_report.py:37` |

⇒ 逐期 Sharpe 被系统性缩放 `sqrt(243/252) ≈ 0.982`(1.8%),DSR 随之偏离。
同一层里的 `annualized_sharpe()`(**生产者**)也是 252 —— 即"同一量两处定义",
而真正的边界(引擎 → DSR)**恰好跨在这两份定义之间**。

实测影响(DSR 相对变化):

| observed_sharpe | k | T | DSR@252 | DSR@243 | 相对变化 |
|---|---|---|---|---|---|
| 0.84 | 19 | 1071 | 0.4410 | 0.4536 | **+2.84%** |
| 0.60 | 30 | 500 | 0.1095 | 0.1124 | +2.67% |
| 1.50 | 10 | 250 | 0.4654 | 0.4762 | +2.32% |
| 2.50 | 50 | 1200 | 0.9992 | 0.9994 | +0.02% |

**中段最受影响** —— 而中段正是"要不要继续研究这个策略"的判据所在。方向是**更少**
折减(引擎确实按 √243 年化,消费者此前除得不够),不是"更保守",即不是我要的偏好,
而是把口径对回去。

### 2 · (b) `n_returns` 被硬编码为 252(实测 **10 处**,不是我最初以为的 7 处)

`n_returns` 是"Sharpe 用了多少个收益观测"(T),用于标准误修正。写成常数 `252` 的位置:

| 文件 | 处理 |
|---|---|
| `uptrend_pullback/sweep_v33_long{,_v2..v6}.py`(6) | 改用 `panel["date"].nunique()`(面板在作用域内) |
| `chase_up/sweep.py` | 同上 |
| `short_reversal/grid_runner.py` | 改用发布的 `n_trading_days`(并把它写进落盘 CSV) |
| `chase_up/sweep_all.py` | 改用发布的 `n_daily_returns` |
| `chase_up/wf_sweep_all.py` | 同上,取多窗口的**均值**(observed 是跨窗 mean_sharpe) |

实测这些窗口只有 **242~243** 个交易日 ⇒ T 被高估 **+3.7%~+4.1%**,标准误被低估约 2%
⇒ DSR **系统性偏乐观**。窗口恰好约一年只是让它**碰巧**没差太远;而 sweep 脚本的
全部用途就是换窗口重跑 —— 那时它会错得更多。

**缺字段即 fail-fast**,不再用常数兜底 —— 兜底值正是这个缺陷的形态。

### 3 · 顺带:观测数随产物发布

`chase_up` / `uptrend_pullback` 的 `compute_metrics` 增发 `n_daily_returns`
(= `len(eq) - 1`,即 T 的定义),两个 return 分支都发。它与 `short_reversal` 的
`n_trading_days` 是**两个量**:一个是"窗口有多少个交易日"(用于年化),一个是
"有多少个收益观测"(用于标准误),差一个观测 —— 注释里写明,避免日后被当成同一个量。

### 4 · 守卫与双向验证

`tests/test_dsr_inputs_single_source.py`(7 条):四个入口的默认 == 规范常量;
两种常数给出**不同**结论(否则单源断言无判别力);**用 AST** 判定所有
`deflated_sharpe_ratio(...)` 调用点的 `n_returns` / `trading_days_per_year`
不得是字面量;并断言扫描面非空(防空真绿)。

两个方向都验:还原 252 默认 + 硬编码 ⇒ **5 red / 2 green**,恢复后 7 全绿。

> **方法论**:这个 AST 守卫当场多抓出 **3 处**(`chase_up/sweep*.py`)——
> 我先前是用 `grep -rn n_returns= -- | head -12` 数的,结果被 `head` 截断。
> 又一次:**完整扫描不要截断**;并再次印证"子串/正则统计"不如 AST 判定可靠。

### 5 · 自我纠错(记录在案)

首版补丁脚本对同一个锚点连续做了两次 `replace` ⇒ 字段被重复插进"空权益"分支,
而**真正会被读到的**主分支反而没有。由仓库既有的
`test_chase_up_sweep_discloses_in_sample` 抓出(它用真实 `compute_metrics` 造夹具)。
改为按行结构性插入,并在**两个分支**各验证一次取值。

---

## 附三十三 —— §3 PIT 的「已退市」判据退化成「当日恰好有 bar」(**成立**,已修)

### 1 · 缺陷(两个相反方向)

**(a) chase_up / uptrend_pullback:把"当日停牌"错杀成"已退市"。**
附二十五 把 as-of 字面值换成了子查询,但 `HAVING MAX(date) >= last_td` 的 `MAX(date)`
**建在 `date <= last_td` 过滤后的分组上** —— 恒 ≤ last_td,于是该条件退化成
「在最后一个交易日**恰好有** bar」。后果:asof 当日/近日停牌的票被当成已退市踢出,
而且踢的是**整个窗口**。

代码自己的注释写的是「(b) asof_date 之前**已退市**的票 `(MAX(date) < asof_date)`」
—— **实现与声明不符**(本条正是"声明要能逐条核到代码上"的又一个例)。

实测(2026-01-09,`mainboard_only`):chase/uptrend **3167** vs short_reversal **3176**,
少的 9 只**全是停牌票** —— 例如 `002049.SZ` 最后一根 bar 是 2025-12-29,而整表最后一根
是 2026-09-30(停牌后复牌),`000608.SZ`、`600058.SH`、`605255.SH` 同形。

**(b) short_reversal:反向错误 —— 根本没有退市判定。**
它的查询只是 `WHERE date <= ?`,于是**一只 2018 年就退市的票在 2026 年的窗口里
依然在宇宙中**。§3 的 PIT Mandate 明确要求「Delisted assets must remain in the
simulation **until their physical delisting date**」—— 即退市日**之后**必须剔除。
数据集实测覆盖 **2016-09-02 .. 2026-09-30**,故这不是空谈。

两个方向合起来说明:同一个 §3 语义在三个引擎里各写一份,于是**一边把停牌当退市、
另一边退市都不算**。

### 2 · 修法

三者统一为同一判据:**活跃 ⇔ 该票「整表」最后一根 bar ≥ asof 当日或之前的最后一个
交易日**(`last_any >= last_td`,用 CTE:一个取 `last_td`,一个取每票的 `last_any`)。

- 「当日停牌」的票 `last_any` 在 asof 之后 ⇒ **留下**(仍在市,窗口内会复牌)✓
- 「已退市」的票 `last_any` 在 asof 之前 ⇒ **剔除** ✓
- 非交易日 asof:两侧都锚在 `last_td` ⇒ 与上一交易日等价 ✓

同时给 `short_reversal/universe.py` 补上**空宇宙 fail-fast**(与两姊妹对齐):
asof 早于数据覆盖起点时,此前静默返回 `[]` ⇒ 回测静默跑出 0 笔交易。

### 3 · 结果影响(逐条量化,依 §6 惯例)

| 项 | 结果 |
|---|---|
| 三引擎在同一 asof 上 | **逐只相同**(10 个 asof 实测,含非交易日、覆盖边界、节假日) |
| chase_up 黄金基线(8 条) | **零漂移** |
| uptrend 基线 v20 / v21 | **零漂移** |
| uptrend 基线 **v19** | **漂移**:98 → 106 行,已按仓库既有 `repinned` 惯例重新 pin |

v19 的归因(逐笔):旧代码在本窗口产出 98 行、sha256 == 上一版 pinned 值(**已核**),
故漂移完全由本改动引起;修复后有 **13 只**标的首次进入可交易集合 ——
`000586.SZ / 002718.SZ / 002921.SZ / 002937.SZ / 003036.SZ / 600777.SH / 603016.SH /
603150.SH / 603303.SH / 603387.SH / 603557.SH / 603685.SH / 605056.SH`,
它们在 asof(2024-09-01,**周日**;最后一个交易日 2024-08-30)上没有 bar 而在 2026 年
恢复交易,旧查询因此把它们整窗排除;其信号落在 2026-03~2026-06(如 `002718.SZ`
2026-06-08→06-16 TP **+411,568**;`603303.SH` 2026-05-22→06-01 TP **+316,069**)。

> 重新 pin 时踩到一个坑并已修正:**不能**用"写 CSV → 读回 → 再哈希"的往返值
> (dtype/浮点格式化会变),必须**直接对 `run_backtest` 返回的 DataFrame**
> `to_csv(index=False)` 取哈希 —— 这正是本仓库 `_regen_chase_baselines.py` 里
> 已经写明的教训("两边各自『对』却永远对不上,重刷也修不好")。
> 另外按规定做了**两次重算一致**的可复现性核验后才 pin。

### 4 · 双向验证

| 方向 | 手段 | 结果 |
|---|---|---|
| chase/uptrend 回退 | 恢复"字面值 HAVING"查询 | **5 red**(合成库语义 + 4 条三引擎不变量),13 green |
| short_reversal 回退 | 去掉退市判定 | 合成库用例报出 `short_reversal: §3 VIOLATION —— asof 之前已退市的票仍在宇宙里`(集合里确实含 `600003.SH`) |

### 5 · 守卫(以及又一条"守卫悄悄失效")

- **合成库行为断言**(核心):真库里**没有退市票**(实测:整表最后一根 bar 落在
  2020~2024 的标的一只也没有 —— 数据集里的票都还活着),故"退市那一支"只能合成。
  合成表放三种情形(正常 / 当日停牌 / 已退市)× 三引擎,把语义钉死在行为层。
- **三引擎不变量**:6 个 asof 上三者的 universe 必须逐只相同(本缺陷的形态就是
  "同一语义两处实现,一边有一边没有")。
- **反向结构守卫**:禁止字面值 as-of 的 `HAVING` 写法。
  **同时修掉了一次覆盖损失**:该守卫原先按"正确形态"做**拼写匹配**,本次换 SQL 后
  它**静默 skip 了 2 条**(文件里 `pytest.skip("无同形 PIT 查询")`),套件依然全绿 ——
  即"守卫在代码演化后悄悄失效"。现改为**负向断言(禁止已知错误写法)+ 行为断言承载
  语义**,不再依赖拼写。

> 这是本审计第三次记录同一个教训(附五 的假阳性、附二十二的"已声明当成没问题"、
> 以及本次的匿名 skip):**按写法匹配的守卫,会在代码演化时变成沉默**。
> 能穿越重构的只有行为断言。

---

## 附三十四 —— §5 Attribution Mandate:**全库无实现** → 已补齐(基准 + 超额)

### 1 · 缺口

CLAUDE.md §5:

> **Attribution Mandate:** Headline returns MUST be reported alongside
> benchmark-relative excess return (index or style basket). Pure style-beta
> replication (e.g. size/momentum factor exposure) MUST NOT be presented as alpha.

审计时**全库无实现**:`core/trade_schema.py`、`chase_up/backtest.py`、
`cycle_price_action/metrics.py`、`tools/render_top5_presets_html.py` 都只报裸收益;
`tests/` 里 `benchmark|excess` 零命中;此前只在报告里打过一个"未归因"标签
(附七第 5 条)。§8#16 记的正是这一项:"目前**完全空缺**的一项"。

### 2 · 基准的选择(已声明、可替换,不是悄悄取一个)

实机核对:`v_daily` 里**只有个股**(后缀分布 SZ 2901 / SH 2320 / BJ 344),
**没有任何指数代码**(000300 / 399300 / 000905 / 000852 / 000001.SH 全部零命中)。
故 §5 的 `index` 这一支**当前不可用**;§5 允许 `index **or style basket**`,遂取:

    benchmark = 该窗口 **PIT 宇宙的等权买入持有**(不调仓)总收益

理由:这些策略的候选池就是"全部主板 A 股",等权买入持有正是它们暴露的
**规模/等权 beta** —— 拿它做基准,恰好回答 §5 真正关心的那个问题:
"这份收益里,有多少只是『拿了那个池子』?"

实现置于 `core/benchmark.py`,产物里同时发布 `benchmark_kind =
"equal_weight_pit_universe_buy_and_hold"`。将来有指数数据时,新增一个 `index` 实现、
由调用方声明即可 —— **读者永远知道这个数字是什么**(与 `sharpe_kind`(附十)、
`n_daily_returns`(附三十二)同一条原则)。

### 3 · 价格域(§3):基准必须用**复权**价

策略侧是**总收益**(分红作为现金流入账,见各引擎的公司行为处理),故基准也必须是总收益
⇒ 用复权价(`close` 列)。用原始价会把分红漏掉,等于**给策略送一个虚假的超额**。
§3 的"raw 用于执行价"说的是**成交价**,不是收益序列 —— 这里要的是收益序列。

### 4 · 口径细节(据实声明,不留沉默的默认)

- 每只标的取窗口内**第一根与最后一根**可用 bar 之比 ⇒ 窗口中途才有行情的标的
  从**它的第一根**起算(不能假装窗口初就持有);
- bar 数 < 2 的标的**排除**,且排除数量由 `benchmark_members` **如实带出** ——
  静默把"窗口内没有行情的标的"算成 0 收益,也是一种沉默的错(本项自身的守卫
  就是拿这一点做双向验证的:把它改成 0 收益,守卫立刻变红);
- 等权买入持有取**等权平均**(不是几何链式),与"等权指数"的常见口径一致,
  且无路径依赖 ⇒ 符合 §0 的确定性要求。

### 5 · 这一项**改变了什么**(为什么 §5 要强制它)

补上之后,同一窗口里可以看到头条收益与超额**符号相反**的情形:某个 `chase_up`
preset 的头条收益为正,而同期等权宇宙基准显著更高 ⇒ **超额为负**。
在只报裸收益的世界里,这个 preset 看起来"小赚、可以继续研究";
在报了超额的世界里,它其实是**负 alpha**(纯 style beta 都算不上)。

(具体数字**故意不写进本文件** —— 按 §7,可由当前代码 + 一条命令复现;
内嵌在文档里就会变成"失效的结论"。命令见 `core/benchmark.py` 的模块 docstring。)

`short_reversal` 是空头策略,基准同样是那个等权池 —— 它的超额为正
(池子走平时做空能赚钱),这正是"基准是否公平"该被看见的地方。

### 6 · 覆盖范围与守卫

| 引擎 | 状态 |
|---|---|
| `chase_up` / `uptrend_pullback` | 已发布 `benchmark_kind` / `benchmark_return` / `benchmark_members` / `excess_return` |
| `short_reversal`(含 ensemble) | 同上;集成路径的基准取自子策略,并**要求子策略基准一致**,不一致即 fail-fast(子策略宇宙不同时,怎么合并基准是人为决定,不该静默取平均) |
| `cycle_price_action` | **未改**(另一 workstream 正在改该包的文件,避免冲突);它已有 `account_model` 口径块,基准留待那一路收口 |

守卫 `tests/test_benchmark_attribution.py`(9 条):

- **确定性核心口径**:三只票(A +10% / B +20% / C 仅一根 bar)⇒ 基准必须**恰好**
  0.15 且成员数 = 2 —— 直接钉住数值,**写死/算错的实现必然失败**;
- 中途才有行情的标的从它的第一根 bar 起算;
- 引擎层恒等式:`excess_return == 总收益 − benchmark_return`(chase 与
  short_reversal 各自的键名不同,分别断言);
- **结构层**:凡发布 `excess_return` 的文件必须同时发布 `benchmark_kind`。

双向验证:把"仅一根 bar 的标的"改成按 0 收益计入 ⇒ 确定性用例立刻变红
(期望 0.15 得到 0.10),恢复后 9 全绿。

### 7 · 性质说明

**这是补空缺,不是修缺陷** —— 没有既有数字被改动,只是在产物里**新增**了四个字段。
故本轮无结果漂移(既有字段一个没动)。

---

## 附三十五 —— 收口:待决策清单、已登记的后续工作、以及两个并行 workstream 的交叉

### 1 · 待决策(每条附我的建议;数字与证据都在对应附录里)

| # | 事项 | 我的建议 | 依据 |
|---|---|---|---|
| 1 | **ATR 滑点标定值**(§4 要求动态滑点,而 100/100 个 preset 的 `atr_slip_scale` 全是 0 ⇒ 已发布结果全部**零滑点**) | **不替谁编一个值**。先决定"要不要按 §4 打开";要打开就得有标定依据(成交回报/冲击成本样本)。机制已就绪(单源 + 缺声明 fail-fast),且"成交量未知时的坑"已填(附三十) | §8#2、附三十 |
| 2 | **`dna_stats` 与引擎的年化口径** | **已按单源修正为 243**(附三十二);若日后要改,只能改一处 | 附三十二 |
| 3 | **cycle 成交口径**(3/4 引擎在下一根 bar 开盘成交,cycle 用**同 bar 收盘**) | 方向由 §0 悲观默认 + 三引擎先例决定(改为下一根开盘);但这是**全量结果变更**,且该包正被另一 workstream 改动 ⇒ **等那一路收口后由其一次改** | 附二十六 |
| 4 | **`pos["bars"]` 按日历 bar 序号计持仓时长** | **不改**:持仓时长本来就随日历流逝(停牌也在持有),这属语义选择而非违约;但**必须声明**(已在附录写明) | 附二十四 §6 |
| 5 | **基准数据** | 已用"PIT 宇宙等权买入持有"落地(§5 允许 style basket);有指数数据时再增一支 `index` 实现 | 附三十四 |
| 6 | **`dna_stats` / lockfile / holdout 边界 / cycle `n_comparisons`** | 需你给事实(依赖锁定策略、holdout 起止、迭代次数) | 附十三/十六 |
| 7 | **涨跌停阈值 0.098(仅 chase)vs 0.095(core 默认)** | 目前是**显式传参**的声明式差异,不是重复定义 ⇒ 可以先不动;若要统一,属策略参数决策 | 附二十六相关 |
| 8 | **short_reversal 的空宇宙守卫** | **已完成**(附三十三),连同 PIT 退市判定一起 | 附三十三 |

### 2 · 已登记的后续工作(不是缺陷,是缺口/功能)

1. **快路径重构**:`scan_signals_fast.py` 现对 74/75 个 preset **拒绝作答**(附三十一)。
   要让它对更多 preset 可用,需按附二十二 的设计把 5 条件抽成**纯函数**、由引擎与阶梯扫描共用,
   再补"两处实现给同一结论"的对拍守卫。**这是功能工作**,不是正确性修复 ——
   正确性(不再给错名单)已由 fail-fast 守住。
2. **§7 产物 writer**:`equity_curve.csv` / `cash_walk.csv` / per-preset `backtest.json`
   的 writer 仍未实现(相应断言按 §6 skip 登记)。
3. **4 个脚本引用已删除的 preset**(`KNOWN_DEAD_REFERENCES` 已登记)。
4. **cycle 的组合级缺口**:每股独立账户(设计未改,已加口径标注)。

### 3 · 两个并行 workstream 的交叉(需要你知道)

本仓库同时有**两条工作线**在改同一批文件:

- 我这条:`fix/discipline-remediation`(代码)+ `audit/strategy-discipline`(审计台账);
- 另一条:`mine/strategy-potential`(在 `~/code/hiagent` 的检出里),其提交包含
  `fix(chase_up) 非交易日 asof`、`fix(cycle) 停牌崩溃 → 成交顺延`、
  `fix(phase2) 拒绝发布负权益`、`perf(cycle) 18x`。

**已经出现的重复**:对方的 `0162de5`(chase_up 非交易日 asof)与我这条的 `8b628b1`
修的是**同一个缺陷**;对方的 `74b0368`(cycle 停牌)与我 `附二十四` 的 §1 停牌语义
在同一片区域。合并时需人工对账,避免"两边各修一半、合并后又退回一半"。

另外:`docs/audits/strategy-discipline-audit.md` 的**附三十二/附三十三**两个提交
原本落在对方的分支上(该检出当时被切到了 `mine/strategy-potential`),我已用临时
worktree 把这两个提交**补进** `audit/strategy-discipline` 并推送(远端 `169ff3e` →
`e778f4f`)。对方分支上仍留有这两份重复的文档提交 —— **我没有改写他们的历史**。

### 4 · 本轮的验证口径(便于复核)

- 每一项修复都做了**双向验证**(守卫必须在"错误实现"上变红),各附录里记了具体手段与结果;
- 全量套件在本轮各批次后分别跑过:1096 → 1103 → 1122 → 1138 → 1146 通过,
  跳过 30、失败 0(每轮都是真库 + 真实回测);
- 修好但**当时不可达**的两项(未知成交量滑点、DSR 年化常量)都如实标注为"潜伏/零漂移",
  不夸大成"已修缺陷";
- 被**证伪**的台账条目同样记录在案(§6 信号层子进程、§2 按字母序成交、
  §1 settle 只冲刷正值等),避免后人按错的描述去改代码。

---

## 附三十六 —— 自查:我自己刚写的基准代码里,也有一个"静默的零"

补 §5 归因(附三十四)之后自查那一笔提交,发现同一个缺陷类**出现在我自己刚写的代码里**:

```python
if not per_name:
    return 0.0, 0        # ← 基准算不出时返回 0.0
```

后果:`excess_return = 总收益 - 0.0 = 总收益` ⇒ 产物读起来像「基准什么都没涨」,
与「基准确实是 0%」**不可区分** —— 这正是本审计反复在修的那一类(静默的零 / 缺口靠
沉默存在)。它出现在"补空缺"的新代码里,说明这类错不是历史遗留,而是**默认行为**:
写一个数值函数时,返回 0 比返回"算不出"更顺手。

修:无成员 ⇒ `(None, 0)`;三个引擎的 `_benchmark_block` 透传 ⇒
`benchmark_return` / `excess_return` **双 None**,与仓库既有的"算不出就 None"口径
一致(`profit_factor` 就是这个先例)。ensemble 路径另加一条:子策略基准**部分为 None**
即 fail-fast(不许静默取平均);全为 None 则整体 None。

守卫:`tests/test_benchmark_attribution.py` 增两条 —— 核心层(空面板 / 仅一根 bar ⇒
`(None, 0)`)与引擎层(三引擎 × `_benchmark_block(空面板)` ⇒ 双 None)。
双向验证:还原 `0.0` ⇒ **4 red**;恢复后整文件 12 全绿。

> 记在这里的原因不是"这一行有多重要",而是它与本审计的一条核心结论互为印证:
> **"算不出"必须是一种显式状态**。凡是让"算不出"与"算出来是 0"共用同一个值的地方,
> 下游就一定会把它读成后者 —— 而这在本仓库已经发生过多次
> (`profit_factor` 的 `Infinity`、DSR 的 `n_returns=252`、`mark_price` 的入场价兜底、
> `_fetch_name_map` 的空 dict、容量闸门缺失时的"经济约束")。

---

## 附三十七 —— "§7 产物 writer 尚未实现"**不成立**:writer 早就有,缺的是**接线**

### 1 · 台账的说法被推翻

台账有两处写着「`equity_curve.csv` / `cash_walk.csv` / per-preset `backtest.json` 的
**writer 尚未实现**」(§8 第 4 条、以及"仍未闭合的缺口"一节)。复核结果:**四个
`main.py` 里都有 `_write_equity_curve`** —— writer 不但存在,而且带 canonical 列名与
§2 的三池落盘逻辑。

真实缺口完全在别处,而且是**两个不同**的东西:

**(a) `short_reversal`:writer 存在、调用点存在,但链路断在中间 —— 永远不可达。**
`main.py:188` 读 `eq_rows = m.get("equity_curve")`,而 `run_backtest_v3` 返回的 metrics
**没有这个键**(实测:22 个键里没有它)。策略每个 bar 都在往
`result_holder["equity_curve"]` 里写(全年窗口实测 200 行、键名齐全),但这些行
**从来没有被带进 metrics** ⇒ `eq_rows` 恒为 None ⇒ 产物永远不出现,而且**静默**。

**(b) `cycle_price_action`:`_write_equity_curve` 没有任何调用点。**
`grep` 计数 1(只有定义)。def 与 call 的区别,在这份台账里此前被记成了"未实现"。

> 这两处合起来说明一件事:**"未实现"与"实现了但不可达"是两种病,修法完全不同**
> (前者要写代码,后者要接线 + 找断点)。台账把它们记成同一个,于是既低估了
> short_reversal(其实只差一个键),又高估了 cycle(其实连调用都没有)。

### 2 · 修法

- `_metrics_from_holder` 把逐 bar 曲线**带进 metrics**(`"equity_curve": list(holder.get(...))`);
- 集成路径**显式置 `None`** —— 多子组合的曲线尚未聚合。用 `None` 而不是"不放这个键":
  缺键会与"字段根本没实现"不可区分(附三十三 的教训);`None` 可被读取方明确抱怨。
- `main.py`:取不到曲线时 **`logger.warning`**(此前静默跳过)。"没写产物"必须出声 ——
  否则"没写"与"写了但为空"同形。
- `cycle_price_action`:**未代改**(该包正被另一 workstream 改动),改为在守卫里
  **钉住事实**:测试断言 writer 仍无调用点 —— 谁接上了它,测试就会失败并被迫更新台账。

### 3 · 守卫:把"真空的 skip"换成"自己产出再校验"

那四条产物守卫此前形如「产物在 → 校验;不在 → skip 并登记缺口」。听起来稳妥,实则:
`results/` 按 §7**必须**不入库 ⇒ fresh clone 下**永远 skip** ⇒ 它们从未校验过任何东西
(而且 `_GAP` 文本里"缺少 writer"的说法是错的)。

现改为**自己产出产物**:

| 守卫 | 做什么 | 成本 |
|---|---|---|
| `test_writer_produces_both_artifacts`(3 引擎) | 合成输入 → 调 writer → 表头 == canonical | 毫秒 |
| `test_cash_walk_pools_are_written_through_not_zeroed`(3 引擎) | 三池**逐列不同且非全 0**、且 `free_cash != locked_margin`(锁住 §2 P0-2 那个"硬编码 0"的形态) | 毫秒 |
| `test_short_reversal_metrics_carry_the_equity_curve` | 单元层钉住本轮那个**具体**缺陷(键必须被带出) | 毫秒 |
| `test_end_to_end_real_run_writes_artifacts`(仅 short_reversal) | 真跑一次 → 一路到文件落盘 | 约 5 分钟 |
| `test_cycle_writer_is_still_unwired_and_that_is_recorded` | 钉住 cycle 的事实 | 毫秒 |

**取舍记录**:最初做法是三个引擎各真跑一次 = **11 分钟**;而 writer 只需要"形状正确的
输入",不需要真回测 ⇒ 改为合成输入后 3 分钟内解决,只保留**一条**真跑端到端
(short_reversal,即本轮修的链路)。实测 5.4 分钟(原为全 skip、0 秒)。

双向验证:回退 metrics 的 `equity_curve` 接入 ⇒ 单元断言以 `KeyError` 变红;恢复后
9 passed / 4 skipped。

### 4 · 台账更正(第五次"说法比事实重")

已把 §8 与"仍未闭合"两处的「writer 尚未实现」更正为「writer 存在,**接线**问题」,
并写明 cycle 的具体状态(定义了但无调用点)。

本审计到目前已经推翻/更正过五条"已复核过"的台账说法:§4 Phase-2(自己已撤回)、
§1 `settle()` 只冲刷正值、§6 信号层子进程(不存在)、§2 按字母序成交(实为合规)、
以及本条"writer 未实现"。它们的共同形态是:
**台账描述的是"当时观察到的表象",而代码在演化 —— 于是"未实现"可能早已变成
"无效/不可达/已重命名"。凡引用台账,必须重新落到代码上核一遍。**

---

## 附三十八 —— 实时扫描工具**手抄参数子集 ⇒ 运行期崩溃**;策略构造改为单源

### 1 · 起因:给快速扫描器写对拍,第一次调用"真值路径"就崩了

`附三十一` 把快速扫描器的"与策略 100% 等价"改成"不等价即拒答"之后,我在 `附三十八`
里把它的参数改为**读 preset 声明**,并打算用**对拍**给出等价性证据 —— 对拍对象是
`scan_signals._scan_preset`(它逐股构造**真实** `Phase3V3Strategy` 跑 cerebro,即回测引擎本身)。

第一次调用就抛:

```
§2: nav_gate_ratio 必须由 Control Plane 从 preset 声明解析后注入
    (engine.run_backtest_v3 → core.preset_contract.resolve_nav_gate_ratio)。
```

也就是说:**实时扫描工具当时根本跑不起来**。

### 2 · 根因:`scan_signals` 手抄了策略构造参数的**子集**

它写的是 `cerebro.addstrategy(Phase3V3Strategy, tp_pct=…, sl_pct=…, …, result_holder=holder)`
—— **12 项手抄关键字**,而引擎侧传 **55 项**。漏掉的东西分两类:

| 漏掉的 | 后果 |
|---|---|
| `nav_gate_ratio`(§2 要求由声明解析后注入,fail-fast) | **运行期直接崩溃** |
| F/G/H/I/J/K 开关、`max_positions`、`position_sizing`、`signal_price_domain`、`max_volume_participation`、`intraday_tiebreak`、`window_start/end` … | 即便把崩溃那一项补上,扫描出的信号集也会**比回测宽**(开关全走默认值)——与快速扫描器同一类错,只是方向相反 |

**而这正是我在附三十一/三十八 里推荐给使用者的"可信路径"。** 台账 §4 的 S1 记过一次
同类事故(`b597d0c` 修的是 `min_cash_ratio` 未传),但那次是**补一个参数**;
这次换个参数又会崩 —— 说明病根不是"漏了某项",而是**"参数清单有两份,靠人手同步"**。

**为什么没人发现**:`scan_signals._scan_preset` 不被任何测试调用 ⇒ 崩溃对套件不可见。

### 3 · 修法:构造逻辑单源

抽出 `short_reversal/engine.py::strategy_kwargs(cfg, name, *, holder, start, end)`
——55 项参数**逐字搬过去**,回测入口与扫描工具**都**调它:

```python
cerebro.addstrategy(Phase3V3Strategy, **strategy_kwargs(cfg, _name, …))
```

**搬运过程中被抓出的两处作用域泄漏**(值得记一笔):helper 里引用了调用方的局部变量
`_name` 与 `price_source_for_execution` —— 我不是靠眼看发现的,而是仓库里**已有的**
两个行为测试(`test_short_reversal_v8_plumbing.py` 里 spy `Phase3V3Strategy.__init__`
的那两条)立刻变红报 `NameError`。**行为测试在这里替我兜住了手工重构的错。**

### 4 · 快速扫描器:参数改为读声明,覆盖 1 → 35 / 75

`_filter_signals` 此前把 liq(3e7/3e8)、up_streak(3/10)、below_ratio(0.6) **写死**,
且只实现 `d_mode='strict'`、不看 `close_ma60_buffer`。现一律读声明,并补齐三种
`d_mode`(`strict` / `d_only` / `converge_strict`,与引擎逐字对应)。

| | 之前 | 之后 |
|---|---|---|
| 可信 preset | **1 / 75** | **35 / 75** |
| 仍拒答 | 74 | 40(F/G/H/I/J/K、市场宽度、ensemble) |

**为什么不顺手把 F–K 也实现了**:引擎把它们算成 **backtrader 指标类**
(`ReturnN(period=63)`、`AmountRatio(...)`、RSI 等),要在 pandas 侧支持就得**重新推导**
这些定义 —— 那是**新增一处重复实现**,恰好与本附录在修的东西相反。正确做法仍是
`附二十二` 的建议:**先把它们抽成纯函数**再由两处共用(继续登记为功能工作)。

### 5 · 对拍(等价性的证据,而不是"说了算")

新增 `tests/test_fast_scanner_matches_engine.py`:同一 preset、同一信号日(2026-09-18),
**快速扫描器 vs 真引擎路径**逐只比较信号集,6 个 preset 覆盖本轮新读的每一项参数
(`strict`/`converge_strict`、ratio、buffer、liq 放宽、cascade、up_streak 收窄)。
子集 = 快扫描命中 ∪ 定序取样 300 只 —— 后者保证"快扫描漏、真值选中"这个方向也在射程内
(只比命中会自证)。另有一条**非空断言**:六个 preset 至少有一个有命中,防止日期/数据变化后
整个文件退化成空转。

**它对拍出了我自己的错**:第一版把**未按 universe 过滤**的面板喂给快扫描器,于是报出三只
非主板票(`301187.SZ` 创业板 / `688816.SH` 科创板 / `920036.BJ` 北交所)。核对后发现
`scan_signals_fast.main()` 本来就按 preset 的 universe 过滤面板,而且**注释里写的正是这个坑**
—— 错在测试。**教训:对拍失败时,先核对"真值路径"的前置条件,再指控实现。**

顺带:这条对拍也是**实时扫描路径的回归守卫** —— 第 2 节那个崩溃,它第一次调用就会红。

### 6 · 台账更正

- §4 的 S1(scan 路径崩溃)原记为"已在 `b597d0c` 修复"。**该表述过窄**:那是补了一个参数,
  2026-10-16 同一个工具因**另一个**参数再次崩溃。现已从**根上**修掉(构造单源),
  同类问题不再是"记得同步"而是"结构上不可能不同步"。
- §8#7d("先抽纯函数、再补对拍")**部分兑现**:对拍已就位;**纯函数抽取仍未做**
  (F–K 的实现前提),继续登记。
- §8#7c 提到的"信号层"相关登记随之更新:扫描工具的构造已收口到单源。

---

## 附三十九 —— 补上 short_reversal 的成交列表基线:这是此前**缺的那张安全网**

### 1 · 缺口

§6 明文:「Golden-baseline hashes lock trade-list behavior **for every engine**;
any logic change that alters the trade list MUST regenerate the baseline and
justify the drift in the PR.」

实测 `tests/golden/`:chase **13** 条、uptrend **3** 条、cycle **1** 条,
**short_reversal 0 条** —— 而它是四个引擎里迭代最频繁的一个(v35 → v83,75 个 preset)。
后果:任何触碰它信号/出场/sizing/容量的改动,判据只剩"套件还是绿的",
**而套件里没有一条锁住成交列表**。

§8 早已登记此项,并写明了正确的做法:**"先修守卫,否则加了基线也无人执行"** ——
即基线必须像 `test_uptrend_pullback_sha256_baseline.py` 那样**在测试内重算**再比对,
不能去读 gitignored 的 `results/`(那种写法在 fresh clone 下会静默 PASS,
本仓库在 uptrend 上吃过一次这个亏)。

### 2 · 本轮补齐

| preset | 覆盖 | 成交 |
|---|---|---|
| `v50_slope` | 单腿生产路径的规范形态 | 28 笔 |
| `v58_mp_2` | **多仓容量路径**(附二十七 改过其 sizing 与容量闸门) | 58 笔 |

窗口 `2026-03-01..2026-08-31`。生成脚本 `tests/_capture_short_reversal_baseline.py`:
每个 preset **连续重算两次、要求哈希一致**才落 pin(不可复现的东西不该被 pin);
哈希**直接取 DataFrame**,不做 CSV 往返 —— 后者两边各自"对"却永远对不上
(该教训写在 `_regen_chase_baselines.py` 里;附三十三 repin 时我也踩过一次)。

**代价如实记**:面板的暖机缓冲主导运行成本(实测 6 个月 ≈3.9 分钟/preset、
一年 ≈5.3 分钟,故缩短窗口收益有限),两条共约 **8 分钟**加到套件里。
这是"成交列表可锁"的价格,写进 golden 的 `pinned` 块。

### 3 · 双向验证(以及一次**无效**的验证)

把 `core/dual_price.py` 里**真正的** `COMMISSION_RATE` 赋值从 `0.00025` 改到 `0.000257`
(2.8%)⇒ 守卫立刻变红,并打印 expected/actual 与 §6 的漂移要求;恢复后干净。

> **第一次双向验证是无效的**:我用正则 `COMMISSION_RATE\s*=\s*([0-9.eE-]+)` 去改,
> 它匹配到的是**注释里的**那一行(`#   - short_reversal engine.py:24  COMMISSION_RATE = 0.0006 (2.4x off)`),
> 于是"跑完没变红"其实是**改错了地方**,不是基线失效。现改为锚定整行赋值,
> 且**先看 `git diff` 确认只动了那一行,再跑**。
> 这是本审计第 N 次遇到同一件事:**按正则/子串下手之前,先确认命中的是哪一处**
> (附三十:AST 守卫多抓出 3 处;附三十六:子串守卫命中我自己的注释)。

### 4 · 顺带闭合的登记

`tests/test_reproducibility_audit.py::test_short_reversal_has_trades_csv_sha256_baseline`
是一条 "GAP CAPTURED" 登记用例(用红灯表达待办)。它的判据正是"`tests/test_short*` 里
存在 sha256 基线" ⇒ 本提交之后它**自然通过**,无需改动它 —— 登记与实现对齐。

### 5 · 这张网解开了一个此前的僵局

附三十八 里我拒绝"顺手把 F–K 也用 pandas 重写"的理由是:引擎用 backtrader 指标类算它们,
在 pandas 侧支持 = **重新推导**这些定义 = 新增一处重复实现;正确做法是先把它们抽成
**纯函数**再两处共用。而我当时不愿动引擎指标层的原因正是:**short_reversal 没有成交列表基线,
改坏了没人知道**。

现在这张网有了(`v50_slope` 28 笔 + `v58_mp_2` 58 笔,逐字节可锁)。故那条重构的风险
从"无保护"降到"有基线可对照",可以立项 —— 但仍**不在本轮做**:它需要把 backtrader 指标
逐个与 pandas 实现**逐值对拍**后才敢替换,是独立一件事。

---

## 附四十 —— 快速扫描器:F/G/H/I/K 落地,可信度 **1 → 68 / 75**(附两级对拍)

### 1 · 做了什么

`scan_signals_fast` 此前对 74/75 个 preset **拒绝作答**(附三十一 修掉"假等价声明"、
附三十八 让它读 preset 声明的参数)。本轮把**剩下能实现的条件**补上:

- **指标**:F/G/H/I/K 需要的 `ma20_slope_5d` / `return_1m|3m|6m` / `amount_ratio` / `rsi`
  一律调用 `short_reversal/indicators_bt.py` 里**新增的 pandas 对偶**。放进那个文件,
  是为了让每个指标的 backtrader 原件与 pandas 版**在同处可查**,而不是像以前那样
  在扫描器里各抄一份。
- **条件**:`_filter_signals` 里逐条照 `_all_conditions` 写(NaN 语义也一致 ——
  引擎遇 NaN 一律 `return False`,pandas 的 NaN 比较亦为 False)。
- **仍拒答 7 个**:J 冷静期 3 条 + 市场宽度 1 条 + ensemble 3 条。前两者是**路径依赖**
  的(J 取决于运行历史里的 SL 出场时点;breadth 取决于当日全市场宽度),
  单行向量化**原理上**复现不了 ⇒ 拒绝是对的,不是缺口。

| | 之前 | 现在 |
|---|---|---|
| 可信 preset | 1 / 75(附三十八 参数化后 35) | **68 / 75** |
| 拒答 | 74 | **7**(全部为原理性不可复现) |

### 2 · 证据(这才是本附录的重点)

"读对了参数"和"抄对了公式"是两件事。故做了**两级**对拍:

**(a) 逐值对拍**(`tests/test_indicator_equivalence_pandas_vs_backtrader.py`):
同一批 25 只代码、同一天,**引擎的 backtrader 指标值** vs **pandas 对偶**,
逐指标比较 —— 14 个指标全部在 `rtol=1e-6` 内一致(其中 RSI 精确到 1e-14)。
范围不止新增的五个:`ma5/10/20/60`、`pct_chg`、`am60`、`up_streak`、
`below_ma60_ratio_60`、`ma20_slope_5d`、`return_1m/3m/6m`、`amount_ratio`、`rsi`
—— **基础五条件的指标此前同样只是"假设等价",现在也一并被钉住**。

**(b) 信号集端到端对拍**(`tests/test_fast_scanner_matches_engine.py`):
扩到 **11 个 preset**(F/G/H/I/K 各一条 + 参数类各一条),同一信号日,
快扫描器 vs **真引擎路径**(逐股构造真实 `Phase3V3Strategy` 跑 cerebro)逐只比较 ⇒ 全一致。

### 3 · 一次"形态指明成因"的调试(值得单独记)

第一次逐值对拍报出:**只有 RSI 不一致**,相对差约 1e-6。

这个**形态**本身就是线索:候选指标里只有 RSI 是**对整条序列递归**的(Wilder 平滑),
其余都是滚动窗口 —— 于是"只有它差"极可能意味着**输入不同**,而不是**公式不同**。
验证:把 backtrader 的 RSI 单独跑在**同一条序列**上,与 pandas 版比较 ⇒ 差 **0 ~ 1.4e-14**。

根因确认:我的测试让引擎侧走引擎自己的 loader、pandas 侧走另一个 loader,
两者给的**历史长度不同** ⇒ Wilder 的种子不同 ⇒ 残差约 1e-6(随递归衰减但不为零)。
改用同一个 loader 后,RSI 与其余指标一样精确。

> 两件事记在这里:
> 1. **测量胜于假设**。我先有一个"种子应该是前 period 个增量的均值"的假设,照它改了一版,
>    残差**丝毫未动** —— 因为真实成因在别处。把指标隔离出来单独跑,两分钟就定位了。
> 2. **我随后把为了掩盖残差而加的"逐指标容差"删掉了**。它当时看着"合理"(浮点路径差),
>    实则是在为一个**测试自身的错**开后门;留着它,将来真的把 Wilder 抄成简单均值
>    (百分之几的差)也会被这层容差吞掉一部分。现在全键统一 `rtol=1e-6`。
>    ——这与附六「用红灯表达待办」是同一类问题:**守卫里最危险的不是没写,而是写成了
>    一个能被绕过的形状**。

### 4 · 与 §6「单一实现」的关系(如实说明取舍)

§6 偏好"一条规则只有一处实现"。本项**没有**做到那一点:引擎仍是 backtrader 类、
扫描器仍走 pandas。之所以不重构引擎指标层:那是**结果敏感**的手术(指标值喂给每一条
条件与每一次回测),而它的收益只是"少一份实现"。

故选择的是**能力等价 + 证据**:两份实现放在**同一个文件**里相邻可查,
并配 **两级对拍**。§8#7d 当初的建议是"先抽纯函数、再补对拍" —— 本轮把顺序倒过来了:
**先把对拍建起来,于是"等价"从假设变成可验证的事实**,而重构与否就有了判据
(要重构,也必须先有这层对拍来证明重构没改行为)。

### 5 · 顺带钉住的一处能力

`test_fast_scanner_equivalence_gate.py` 里原本有一条"`v50_slope` 启用 F ⇒ 必须被拒"。
F 实现之后,这条**拒绝**正是应当消失的东西 —— 已改为钉住新能力
(五条条件对应的 preset 现在都必须**可信**),而不是把覆盖删掉。
可信集合快照 `KNOWN_FAITHFUL` 同步 35 → 68,并在注释里写明余下 7 个为何不可复现。

---

## 附四十一 —— 套件成本与"慢守卫"开关(**默认不减少覆盖**)

### 1 · 背景:本会话把全套件从 43 分钟推到 49 分钟

其中约 **29 分钟**集中在 19 条"以分钟计"的守卫上,全部是本会话新增的:

| 守卫 | 条数 | 约计 |
|---|---|---|
| short_reversal 成交列表基线(附三十九) | 2 | 8 分钟 |
| 快扫描器 vs 真引擎**信号集对拍**(附四十) | 12 | 6 分钟 |
| 容量行为(附二十七) | 2 | 5.5 分钟 |
| 基准归因(附三十四) | 2 | 4 分钟 |
| 产物端到端(附三十七) | 1 | 5 分钟 |

这些守卫**都替换了真空覆盖**(原先不是 skip 就是恒真),所以值得留。但成本必须
**可见、可控** —— 否则"验证很慢"会以最坏的方式解决:有人把守卫删掉。

### 2 · 做法

新增 `pytest.ini`,注册 marker `slow` 并开启 `--strict-markers`。
后者是**必须**的:未注册的 marker 会被 pytest **静默忽略**,于是"我打了标记,所以这组
被排除了"会变成看不见的事 —— 静默忽略 = 测试被悄悄排除,正是本审计反复在修的那一类
(附五 假阳性、附六 用红灯表达待办、附二十二 "已声明=没问题"、附三十三 静默 skip)。

三条命令(实测数字):

| 用途 | 命令 | 收集 | 耗时 |
|---|---|---|---|
| **完整验证(默认,CI 应当用这个)** | `pytest` | **1213 条全收** | 49m00s |
| 本地快速迭代 | `pytest -m "not slow"` | 1194 条(19 条被显式排除) | **19m46s(省 29 分钟)** |
| 找出"下一条该标的" | `pytest --durations=20` | — | — |

### 3 · 关键设计选择:**默认仍然执行全部**

本仓库已经被"守卫悄悄失效"伤过多次,而"**默认跳过重型守卫**"正是同一族缺陷:
它不会报错、不会变红,只会在**一片绿**里把覆盖拿掉,而且事后无从察觉。
故 marker 只作**显式**开关。实测:不加 `-m` 过滤时收集 1213 条 = 加标记之前**完全一致**。

> 一句话原则:**让"跳过"必须由人打出来**(`-m "not slow"`),而不是由默认值决定。

### 4 · 未做完的部分(如实说明)

我只标了**本会话新增**的重型守卫。更早的历史测试(governor、golden 等)尚未逐条标 ——
那需要一次 `--durations` 跑分才能**诚实地**标(按感觉标会让"哪些慢"变成传闻)。故
`-m "not slow"` 省下的 29 分钟**少于**理论上限,这一点写进了 `pytest.ini` 的注释里,
免得后人以为已经标全了。

顺带:快速模式那一跑(19m46s)本身也让 1164 条非重型守卫**全部通过 / 0 失败** ——
即这条开关不是"跳过就算",被留下的那部分确实还是绿的。

---

## 附四十二 —— 补完 slow 标记:`--durations` 实测把快速模式压到 **3 分钟**

附四十一 只标了本会话新增的重型守卫,并写明"更早的历史测试需要一次 `--durations` 跑分
才能**诚实地**标"。本轮把那次跑分做了(52m09s,1183 passed,0 failed),按 **≥60s** 的判据
补标两处 —— 而这两处**都不是靠感觉猜得到的**:

| 未标但很慢的 | 实测 | 为什么先前的"逐条标"会漏掉它 |
|---|---|---|
| `test_short_reversal_no_lookahead.py` 的 `test_pre_window_entry_count_is_zero` | **438s,全在 setup** | `trace_report` 是 **module 级 fixture**;该文件里**三条**测试共享它。只标报时的那一条**毫无作用** —— 另两条照样把它拉起来 ⇒ 必须按 **fixture 的使用者**标,而不是按"谁报了时间"标 |
| `test_engine_v3.py` 的 `test_end_to_end_one_preset` / `test_high_cagr_preset_profitable` | 320s / 312s | 历史文件,不在本会话改动范围内;不跑一次 `--durations` 就只能凭猜 |

结果(实测):

| | 标记前 | 现在 |
|---|---|---|
| **默认(不加过滤)** | 收集 1213 条 | 收集 **1213 条**(**完全一致** —— 标记不减少默认覆盖) |
| `-m "not slow"` | 19m46s / 19 条被排除 | **3m03s / 24 条被排除** / 1159 passed / 0 failed |
| 全套件 | 49m00s | 52m09s(`--durations=30` 本身有开销) |

> **两条教训**:
> 1. **共享 fixture 会隐藏成本归属。** 438 秒记在一条测试名下,实际是三条共用的
>    module 级 fixture;按"谁慢标谁"处理,等于没标。标之前要看 fixture 作用域。
> 2. **体感估时不可靠。** 我先前把"基准归因两条"估成"约 4 分钟",实测 chase 那条只要
>    **4.8s**、短反转那条 308s —— 差两个数量级。凡涉及"哪条慢",一律以
>    `--durations` 为准;这也正是把"估时"写进守卫注释时的风险:一个错的数字比没有数字更坏。

---

## 附四十三 —— 系统扫"空转守卫":粗模式全清,但费率守卫确实是空转的(并修了扫描器自身的误报)

### 1 · 起因:把"检查器本身才是问题"这一类**系统地**扫一遍

此前几次都是**个案**发现(附二十五 的静默 skip、附三十三 拼写匹配的守卫、附四十 的
"为测试自己的错开后门")。这次写扫描器系统过一遍全库测试:

| 粗模式 | 命中 |
|---|---|
| `assert True` / `assert 1 == 1` | **0** |
| `if False` / `if False else` | **0** |
| 无理由的 `pytest.skip()` | **0** |
| `except Exception: pass` | **0** |

> **一条自我纠正**:我的第一版检测器把 **84 个**测试判成"无断言 / 无失败路径",
> 逐个查看后发现**全是假阳性** —— 本仓库的房规是 `if <bad>: raise AssertionError(...)`,
> 因为 `python -O` 会剥掉 `assert`(这正是审计自己在 §0/§6 主张的)。检测器只认
> `ast.Assert`,于是把**主流写法**判成空转。改成同时认 `raise AssertionError` /
> `pytest.raises` / `_assert*` 助手后降到 **19 条**,再逐条看:其余都是"不抛异常即通过"
> 的冒烟用例(函数名就写着 `..._does_not_raise`)。
>
> **假阳性扫描器比没有扫描器更毒** —— 这条教训这次应验在我自己的工具上。

### 2 · 真缺陷一:四个费率用例里有三个从不失败

`tests/test_cost_constants_single_source_4engine.py`:

```python
    if chase:
        # Informational — chase_up has known duplicated cost constants
        # per Tick 53. This is documented, not a regression.
        pass                      # ← 扫完不看,永不失败
```

而同一个函数的 docstring 写着「This test **catches** NEW hardcodes introduced after
refactor」—— **声明与实现相反**。`uptrend_pullback` 同形;`short_reversal` /
`cycle_price_action` 稍好(有 `raise`),但只比对**特定错值**(0.0006 / 0.001)⇒
"值抄对了但重复定义"这个**漂移起点**照样漏过。

**这与台账的关系(第 6 次"账实不符")**:审计的 §3.2/§3.3 与 §8#13 都**点名**了这个文件的
`:265`(无断言 `pass`),而 §8#13 是"修三个空转守卫"的**修复计划**。也就是说:发现记了、
计划列了,**这个文件却没被真正修**。附六 当时说「恒真断言早已修」指的是**另一个**
文件(`test_backtest_data_integrity.py:58`),措辞容易让人以为这一族都清了。

### 3 · 真缺陷二:扫描器自己在误报

`_scan_hardcoded_costs` 只按"数值命中费率表(0.00025 / 0.0005 / 0.0006 …)"判定,
而它算出来的 `cost_context` 变量**从未被使用** —— 紧接着就是无条件 `append`,
注释还写着 *"Always flag ... (even without context)"*。后果(实测):
`short_reversal/replay_strategy_v3.py:185` 的 **`sl_pct=0.0005`**(止损百分比,
一个策略参数)被报成"印花税重复定义"。

在这条上假阳性尤其毒:它给了"这四个用例本来就抓不准"一个体面的理由,
从而把真正的费率重复藏进噪声里。

### 4 · 修法

- 扫描器改**按名字**判定:赋值目标 / 关键字实参的名字含
  `commission|stamp|duty|fee|cost|tax|borrow`,且值**非零**
  (零值有合法用途:`cerebro.broker.setcommission(commission=0.0)` —— 成本由策略内部扣)。
- 四个用例统一为**任何非零成本字面量即违规**,共用 `_assert_no_cost_literals`:
  不再有 `if: pass`,也不再只盯特定错值 —— **值对错都不该出现在引擎里**
  (同值不同源就是下一次漂移的起点,§2 单源)。

重写后实测:四引擎**都是 0 处**,与审计"费率重复定义**已消失**"的结论一致 ⇒
这些守卫现在是**为真且为绿**的,而不是"绿是因为什么都没查"。

### 5 · 双向验证(含**负对照**)

| 方向 | 手段 | 结果 |
|---|---|---|
| 正对照 | 往 `chase_up/portfolio.py` 注入 `commission_rate = 0.00025` | **变红**,并打印 `chase_up/portfolio.py:208 commission_rate=0.00025` ✓ |
| **负对照** | 注入 `sl_pct = 0.0005`(旧扫描器误报的那个值) | **保持绿** ✓ —— 假阳性确实修掉了,而不是把守卫放宽成"什么都抓不到" |

恢复后 5 passed,`git diff` 干净。

---

## 附四十四 —— 把"skip"当作一个**覆盖维度**来盘点:三处天花板守卫 + 一条未实现的要求

### 0 · 方法

继附四十三(系统扫"空转守卫")之后,换一个维度:把 skip **本身**当作覆盖来审计。
做法便宜到只需三分钟 —— `pytest -m "not slow" -rs`(快模式列全部 skip 理由),
然后逐条问:**"不 skip 的条件在这个仓库里可能满足吗?"**

"在 fresh clone / 干净检出里必然 skip,且不 skip 的条件不可能满足"的守卫,
提供的不是覆盖,而是**覆盖的错觉**。本轮据此找到三处,外加一个真缺陷。

### 1 · 真缺陷:`build_trade_dates` 声明了"必须报 unverified",而实现里没有这个词

`short_reversal/render_html_report.py` 的模块 docstring 第 4 条:

> 4. 若所有候选都不通过校验, **必须报 "unverified"** (而不是任意挑一个错的)

全文件 grep `unverified` ⇒ **零命中**。实际行为:退化取最早候选,并**凭空推**
`exit_date = entry + BDay(hd)` —— 那个 bar 可能根本不存在。于是 HTML 报告里会出现一个
"看起来正常、数字是编的"日期。**这正是该文件当初要防的那个 bug 的变体。**

修:回退路径**状态随行发布**(`_date_status` ∈ `verified` / `unverified` /
`no_kline_match`),初值取 `unknown` —— fail-safe 方向:漏标记只会让状态更**保守**,
不会更乐观;汇总处打印未通过校验的条数。

> 又是"声明与实现不符"(本审计第 7 次)。这次的形态最刺眼:**声明就写在同一文件的
> docstring 里,而正文从未实现它** —— 说明"写在旁边"完全不能替代"落到代码"。

### 2 · 三条守卫依赖**已删除 preset** 的产物,并给出不可能执行的指引

`tests/test_render_html_date_mapping.py` 原由真实产物驱动,而
`v33_mainboard_tp2_sl05_dneg` / `v33_mainboard_tp6_sl005_mh5_realistic`
**已裁剪出 PRESETS** ⇒ 产物再无法重生成 ⇒ 三条用例**永远 skip**,理由还写着
"需用 `--save-trades` 重跑 <已不存在的 preset>" —— **一条不可能执行的指引**
(比"没有指引"更坏:它让人以为再跑一次就能恢复覆盖)。另外它把 DB 与 results 路径
**硬编码到别人的检出**(`/Users/holeon/code/hiagent/short_reversal/results`),
与审计在 `_regen_chase_baselines.py` 修过的"硬编码绝对路径会读/写别的检出"同类。

修:改为**合成夹具** —— 不依赖产物、不需要 DB,**任何检出里都能跑**(0.02 秒),
四条不变量全部仍被钉住,其中包含**历史 bug 本体**:歧义入场价时必须选
**能通过 `exit_price` 校验**的那根,而不是日期最早的那根。

### 3 · 11 条"等 csv 生成"的守卫:不变量并入已有的重算测试(零额外成本)

`test_short_reversal_trade_math_consistency.py` 守的是 **SHORT 方向语义**
(SL ⇒ `xp > ep×(1+sl_pct−tol)`;TP ⇒ `xp < ep×(1−tp_pct+tol)`;违反即**幻影出场** ——
审计 §4 的实锤族),但它靠 gitignored 的 `results/*_trades.csv` 驱动 ⇒ fresh clone 里
**11 条全 skip**。

而 `test_short_reversal_sha256_baseline.py` **本来就要重算成交列表** ⇒ 把该不变量跑在
**重算出来的**数据上:**零额外成本、不依赖产物**。

实测:两个 preset 的**全部真实成交均无方向违规**(verified-clean)
—— 即"幻影出场"在当前数据上不存在,而这个结论现在**每次跑基线都会被重新验证**,
不再是"没人查过"。另配一条**植入幻影必须被报出**的单元对照(0.02 秒),
证明检查器有牙而不是恒绿。

### 4 · cycle 的成交列表基线:默认从"永远不跑"改为**默认跑**

`test_cycle_price_action_sha256_baseline.py` 用**环境变量**默认跳过
(`DNA_RUN_SLOW_GOLDENS=1` 才跑),理由写着"放进默认套件会让整体不可用" ——
该理由在**没有 marker 机制**时成立,而附四十一 刚把 `slow` marker 建好。
故改用 marker:**默认执行**(实测 7 分钟、**通过**),本地快速迭代用 `-m "not slow"`
显式排除。

**为什么这条重要**:它是四个引擎里**唯一**锁住 cycle 成交列表的守卫。
默认跳过它,等于 cycle 的成交列表**从来没有被验证过** —— 而这正是本审计一直在批的
"覆盖在绿色里消失"。marker 机制的价值在这里第一次真正兑现:让"重型"与"默认不跑"
**解耦** —— 重型可以默认跑,需要快的人显式说不。

### 5 · 双向验证

| 项 | 手段 | 结果 |
|---|---|---|
| 日期映射 | 还原为"静默 verified" | **2 red**(`unverified` / `no_kline_match`),恢复后 5 全绿 |
| 方向语义 | 合规样本 vs **植入幻影** | `[]` vs 报出 2 条(单元级,0.02 秒) |
| cycle 基线 | 先以显式环境变量确认可通过(7m09s)再改为默认跑 | 通过,且默认收集数 +1 |

---

## 附四十五 —— 扫描"声明了但代码里没有的机制":命中 1 处(其余 23 处为合法),扫描器精度不足故不做守卫

### 1 · 方法(承接附四十四 那个 `unverified` 缺陷的**形态**)

附四十四 的真缺陷有一个共同外形:**docstring 里点名了一个机制/标签,而代码里没有它**。
于是写扫描器把这种外形找出来:收集 docstring 里被引号或反引号点名的 token
(`"unverified"` / `` `raw_close` `` 这类写法),再看它是否出现在**代码区**
(即去掉 docstring 之后的源码)里。覆盖 107 个生产模块。

### 2 · 结果:24 处命中,逐条看过后**只有 1 处是真缺陷**

| 类别 | 例子 | 判定 |
|---|---|---|
| 跨模块引用 | `dna_data/dual_price_loader.py` 提到 `extract_execution_bar` / `is_limit_up` | 合法 |
| 历史沿革说明 | `core/preset_contract.py` 提到改名前的 `min_cash_ratio` | 合法 |
| 跨引擎一致性备注 | `short_reversal/engine.py` 提到 `profit_factor` 的 None 口径 | 合法 |
| 通用词 | `cycle_price_action/presets.py` 的 `time` | 噪声 |
| **真缺陷** | `short_reversal/feed_bt.py` 声称加了 `raw_*` lines | **见下** |

### 3 · 那 1 处:`feed_bt` 的模块 docstring 描述了一个**不存在、也不需要**的机制

模块 docstring 写着「V3a: 添加 raw_open/raw_high/raw_low/raw_close lines,strategy 在
`price_source_for_execution="raw_close"` 时切换 SL/TP/intraday trigger 价格到 raw_*
lines;raw_* 缺失 → fallback 到 adj …」。实测:

- `lines` 元组里**没有任何 raw_***;
- 全模块 grep `d.raw_close` / `d.lines.raw_*` **零命中**。

而这个机制**本来就不需要**:`v_daily` 本身就是原始价 ⇒ raw 域执行直接用默认的
`close` line;复权域另开 `adj_open/adj_high/adj_low/adj_close` 四条。
`price_source_for_execution="raw_close"` 的含义正是"用默认(原始)列"。

**为什么值得修**(而不只是"文字不准"):这段描述会让人或 agent 以为
`d.lines.raw_close` 存在(→ 写出 AttributeError),或者据此对价格域下错结论 ——
而"短反转的 `close` 到底是 raw 还是 adj"正是审计 §3 **反复要钉住的前提**
(它决定了 A 条件、公司行为、D 条件那些结论是否成立)。

**类** docstring(`AShareData`)本来就准确 —— 它明确写着「当前 strategy 仍读 raw
(v_daily IS raw)」。故只更正模块级那一段,并使其与类级说法一致。纯文档改动。

### 4 · 扫描器本身的评价:**精度不足,不做成守卫**

24 处里 23 处合法 ⇒ 假阳性率约 96%。按本审计自己的判据(**假阳性比假阴性更毒** ——
它会让真缺陷藏在噪声后、并最终导致守卫被关掉),这种精度的扫描器若固化成守卫,
只会制造长期噪声。故它只当**一次性排查工具**用,结论记在这里,不入库。

> 这也是本会话第 N 次遇到同一个元问题:**"扫描器"永远要先验证它自己**。
> 今天早些时候,我自己的检测器分别把 84 个合规测试判成空转(附四十三)、
> 把 `sl_pct=0.0005` 判成印花税重复(附四十三)、把 `pytest.skip()` 的检测写成零命中
> (附四十四)。**先量自己的假阳性率,再决定它配不配当守卫。**

### 5 · 本轮在"覆盖"这条线上的收获汇总(附四十三 → 附四十五)

| 维度 | 手法 | 结果 |
|---|---|---|
| 空转守卫 | AST 扫 `assert True` / `if False` / 无理由 skip / 吞异常 | 粗模式**全清**;真缺陷在费率守卫(4 个用例 3 个从不失败) |
| skip 当覆盖 | `-m "not slow" -rs` 列理由,逐条问"不 skip 的条件可能满足吗" | 3 处天花板守卫 + 1 条未实现的要求(附四十四) |
| 声明 vs 代码 | docstring 点名的 token 是否出现在代码里 | 24 命中 / **1 真缺陷**(附四十五,本条) |

合计把**4 条永远 skip 的守卫换成真覆盖**(cycle 基线 + 3 条 render_html),
外加把 11 条依赖 gitignored csv 的不变量并入已有的重算测试 ——
全套件因此 **skip 30 → 26、passed 1183 → 1190**,两个方向同时动,方向正确。
