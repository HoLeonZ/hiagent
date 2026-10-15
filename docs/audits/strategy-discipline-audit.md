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

但审计的批判层（critic）另指出 **6 个没有任何 cell 覆盖的面**。这些**不是违规认定**，只是「未审查到」的空白，需后续单独立项确认：

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

**公司行为(P2-10)**:`chase_up` / `uptrend_pullback` / `short_reversal` 已接入同一 `core` 实现(做空为**付出**,符号由引擎决定;四条引擎统一"除权日当天建仓不享有"的权益归属规则);**`cycle_price_action` 仍未接入**。

**仍未处理(按 §8 顺序)**:滑点的 preset 显式声明 + 缺声明 fail-fast(P1-B2,需给 100 个 preset 各加一条声明);公司行为推广至其余三引擎;§5 的 DSR `n_trials` 口径与基准归因;§7 源码内嵌业绩数字清理;`chase_up` 金标准基线仍红(陈旧产物),故 chase_up 侧的漂移今天仍不可见。

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
