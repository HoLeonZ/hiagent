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

**状态**:`b597d0c` 的 `c06ead1` 已将默认值改为 `0.05`(`replay_strategy_v3.py:196`),**该崩溃在当前 `origin/main` 上已消除**。

### S2 · 不可变性守卫可被"别名"绕过,源码注释明说这是为了绕过检测器 —— **未修复**

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

### S3 · 守卫静默跳过不存在的文件,覆盖是假的 —— **未修复**

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
3. **§5 Attribution Mandate 从未被任何 cell 检查，且全库无实现**：`core/trade_schema.py`、`chase_up/backtest.py`、`cycle_price_action/metrics.py`、`tools/render_top5_presets_html.py:905` 都只报裸收益，无基准超额；`tests/` 中 `benchmark|excess` 零命中。
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
13. 修三个空转守卫（`tests/test_reproducibility_audit.py:331`/`:352`、`tests/test_cycle_price_action_sha256_baseline.py:94`、`tests/test_cost_constants_single_source_4engine.py:265`、`tests/test_chase_up_no_lookahead.py:642-656`、`tests/test_backtest_data_integrity.py:58`），并把 61 failed + 3 error 登记 owner 或修绿。
14. 补 `tests/golden/short_reversal_*_baseline.json`（先修守卫，否则加了基线也无人执行）。
15. §5：`dsr['p_value']` 键名错误、`n_trials` 累计口径、sweep 的 OOS 窗口（`uptrend_pullback/sweep_v33_long*.py`、`short_reversal/wf_v34_focused.py`、`chase_up/wf_sweep_all.py`）。
    → **已处理(见附十三)**:键名、`n_trials` 口径、DSR 分子/分母一致性、收益率当 Sharpe 均已修;
    **仍未闭合**:4 个脚本引用已删除的 preset(已登记 `KNOWN_DEAD_REFERENCES`)、以及原文点名的
    「窗口跨越已声明的 holdout」(需使用者确认 holdout 边界)。
16. 补 §5 Attribution Mandate 的实现（基准超额），这是目前完全空缺的一项。

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
4. **§7 产物 writer**:`equity_curve.csv` / `cash_walk.csv` / per-preset `backtest.json` 的 writer 尚未实现(相应断言按 §6 skip 登记)。注:`cycle` 的 `cagr/sharpe/max_dd` 返回 `None` 是**诚实**的"横截面无法定义",不是缺口。
5. **§6 展示层重复**:`tools/render_top5_presets_html.py` 重述逐 bar 指标与 A/B/C 文案(回测本身调用真引擎);消解需引擎暴露逐 bar 指标序列,属重构。
6. **"有实现、无消费者"的库函数**:`tail_objective.tail_stats`(测试外无调用点)与 `render_top5` 同类;建议统一清理而非逐个顺手改。
7. **§3 公司行为**:配股/缩股未建模(全库 1 例),`apply_corporate_action` 已显式告警。
8. ~~§7 源码内嵌业绩数字清理~~ → **已完成(`5c731cd`)**;~~`chase_up` 金标准基线仍红~~ → **已修复(`e063c43`)**;~~cycle 无成交列表基线~~ → **已补(`4cbc66c`)**;~~审计自认的六个未覆盖面~~ → **已查证(附七)**。

**当前测试状态**(截至 `a714e64`)——**三种条件都跑过**(§6 的验收条件就是 fresh clone 的条件):

| 条件 | 结果 |
|---|---|
| 有本机行情库 | 1011 passed / 30 skipped / **0 failed** |
| 无库(路径不存在) | 967 passed / 74 skipped / **0 failed / 0 errors** |
| 无库(0 字节占位) | 967 passed / 74 skipped / **0 failed / 0 errors** |

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

- **§7 产物边界(8 条)**:`equity_curve.csv` / `cash_walk.csv` / per-preset `backtest.json` 的 **writer** 尚未实现。`results/` 按 §7 不入库,故这些断言只在产物存在时校验 schema、缺失时 skip 登记。§2 的实质要求(NAV 恒等式 + 现金守恒)已由 `test_nav_cash_ledger_invariants.py` 在内存中确定性覆盖。
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

