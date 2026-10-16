# uptrend_pullback preset 搜索:评估协议、工具与机制不变量

> **本文按 CLAUDE.md §7 撰写:只写「怎么复现」和「要检验什么不变量」,不含任何历史指标。**
> CAGR / Sharpe / 胜率 / 收益 / 行数等一律不入此文;带数字的运行记录留在 gitignored 的
> `uptrend_pullback/results/PRESET_SEARCH.md`。
>
> 与本仓库既有约定一致:`README.md` 记明「历史审计报告已从 `docs/` 移除」——**发现进 commit log,
> docs 只留复现方法**。

---

## 1. 为什么要这份文档

对 `uptrend_pullback` 做 preset 择优时,曾长期用**被污染的目标函数**在选择:
equity 曲线把建仓名义额计入两次(Sharpe/回撤失真)、DSR 把年化 Sharpe 与逐期阈值混用、
以及用**均值 Sharpe 去评价一个由右尾驱动盈亏的策略**。这些尺子后来都被修正(见 §3 的工具),
但**换尺子会改变候选排序**——所以除工具本身之外,还需要把「怎么复现一次评估」和
「哪些改动方向已被证伪」固化下来,避免后人重新走一遍同样的弯路。

## 2. 评估协议(CLAUDE.md §5 合规)

| 项 | 做法 |
|---|---|
| 窗口 | 2 个月窗口 × 1 个月步长(`core.walkforward.monthly_windows`) |
| 迭代期 | `2024-09 .. 2026-03`(用于择优) |
| holdout | `2026-03 .. 2026-09`,**迭代期不碰**,只在下结论时跑 |
| 独立期 | `2020-01 .. 2024-09` —— 一段**从未参与任何迭代**的历史(DB 覆盖 2016-09 起;PIT universe 早年可用)。样本远大于 holdout,是本项目事实上的主判别器 |
| 目标函数 | **R-multiple 期望 `E[R]`**(见 §3),辅以分布量:win%、avgWinR、avgLossR、P(R≥5)、尾十分位贡献、PF |
| 选择偏差 | 每次试验累加 `n_trials`,显式写进 preset 的 `n_comparisons`,供 DSR/Bonferroni 折算 |
| 归因 | 任何收益结论必须同时给**相对基准(同 universe 等权指数)的超额**,并对 beta 做检查 —— 纯 beta 复制不得当作 alpha |

**纪律**:不做网格搜索取最高 Sharpe;一次只评估一个假设;holdout/独立期的使用次数本身
要如实披露(用得越多,证据强度越低)。

## 3. 工具与复现命令

```bash
# (a) 单候选滚动窗口评估 + DSR(n_trials 必须显式传入)
python3 -m uptrend_pullback.wfv_eval --preset v33_long_reverse_v21 --n-trials 121 \
    --start-month 2024-09 --end-month 2026-03 --label my_candidate

# (b) 由 base preset 派生候选(点路径增量, 不写全量 dict)
python3 -m uptrend_pullback.wfv_eval --base v33_long_reverse_v21 \
    --overrides '{"tp_pct": 0.30, "signal.min_mom120": 0.15}' \
    --label cand_x --n-trials 122

# (c) 尾部目标函数(在代码中直接调用)
python3 -c "
from uptrend_pullback.tail_objective import tail_stats
# trades 为 run_backtest(...)['trades']; sl_pct 取候选的固定止损宽度
# print(tail_stats(trades, sl_pct=0.021))
"
```

**关键**:`R_trade = sl_pct × entry_price × size`(入场时即固定的计划风险),
`R_mult = net_pnl / R_trade`。**不要**用 `atr_pct` 做分母 —— 固定百分比止损路径下
`atr_pct` 可能为空,会把整批 R 算成 NaN(本项目踩过这个坑)。

## 4. 机制不变量(每条都可证伪;改动后请重跑 §3(a)/(c) 验证)

以下方向**均已实测为更差**,若有人重新提出,请先复现再讨论:

| 不变量 | 改动即变差 | 复现方式 |
|---|---|---|
| **排序用 `score = mom120` 降序** | 反转排序、按 ATR% 排序、按回调深度排序 | 覆盖 `score` 后跑 §3(a) |
| **信号日 T 之后 T+1 开盘立即入场** | 加"确认 K 线"延迟入场(T+2 开盘) | 包装 selector 把信号日后移一根 K 线 |
| **固定百分比 TP/SL** | 改用 ATR 归一化(`atr_tp_mult`/`atr_sl_mult`) | 在 preset 里设 `atr_*_mult` 后跑 §3(a) |
| **TP 不宜过宽** | 抬高 `tp_pct` | 覆盖 `tp_pct` 后跑 §3(a) |
| **`max_positions = 1`** | 提高并行持仓数 | 覆盖 `max_positions`(`position_sizing` 需相应改 `equal`) |
| **市场级 regime gate 有效** | 去掉 `regime` 块、或加 `require_rising` | 对照跑 §3(a) |

> **2026-10-16 更正**: 上表 `max_positions = 1` 一行**已被推翻**, 但推翻它的不是
> 该行的复现方式, 而是**判据**。那一行的依据是 `tail_objective` 的逐笔 E[R] ——
> 逐笔期望对分散化**完全不敏感**: 加仓让每笔更小、期望不变, 而组合波动与回撤下降。
> 换成组合口径 (Sharpe / Calmar / MaxDD) 后, N=2/3/4 在三个窗口上全部优于 N=1:
> 最大回撤近乎减半, W2 与 IND 的 CAGR 更高。同族的 short_reversal 此前踩过同一个
> 盲点 (它的"多仓无效"判决是在容量闸门有缺陷时做出的)。
>
> **但结论仍是否定的一半**: N=4 并没有让这个族在非趋势期变得可用 —— IND 与 IS1
> 上 N=1..4 全部为负 (这与 §6 已写下的"该族在非趋势市里期望为负"一致)。
> 所以正确的表述是: 「**max_positions>1 在组合口径下更好; 但它救不活这个族**」。
> 本节不记数字 (§7); 完整三窗口结果在 commit log 与工作日志里。

**统一机理解释**(三条独立证据同向):该策略赚的是「**未确认的立即延续**」——
在上升趋势中刚回调的票里取动量最强的那只,次日开盘立即买入,用宽 TP + 紧 SL 收割右尾。
**任何延迟入场或改排序的做法都恰好把这部分拿掉。**

## 5. 已证伪的方法(定性;每条给出复现路径)

| # | 方法 | 复现方式 |
|---|---|---|
| M1 | 按 ATR% 降序排序 | 覆盖 `score` 为 `atr_pct` |
| M2 | 按回调深度排序(最深优先) | 覆盖 `score` 为 `-sig_pullback` |
| M3 | ATR 归一化 TP/SL(倍数由候选池 ATR 中位数反推,不扫参) | preset 设 `atr_sl_mult` / `atr_tp_mult` |
| M4 | regime 加 `require_rising` | preset 的 `regime` 块加 `require_rising: true` |
| M5 | 入场确认(T+1 收涨才入场) | 包装 selector:要求下一根 K 线收涨并把信号日后移一根 |

## 6. 该族的结构性事实(结论性,无数字)

- 退出分布极度偏止损、持仓期极短,盈亏由**少数右尾事件**驱动 —— 因此
  **均值类指标(Sharpe、窗口均值)不是合适的判据**,应使用 §3 的尾部口径。
- 该 preset 家族在**非趋势市**里期望为负;在趋势市里的正收益与**市场 beta** 高度相关。
  因此其头条收益**必须按 §2 的归因要求对照基准**,不得直接当作选股 alpha。
- 据此,若要取得可证实的 alpha,应更换**信号源**(引入基本面/事件维度),
  而不是继续在价格派生的 A~E 条件上做参数或排序层面的改动。

## 7. 相关代码与测试

- `uptrend_pullback/wfv_eval.py` —— 单候选 WFV 评估器
- `uptrend_pullback/tail_objective.py` —— R-multiple 目标函数
- `tests/test_uptrend_pullback_tail_objective.py` —— 公式与统计口径的钉桩测试
- `tests/test_uptrend_pullback_sha256_baseline.py` + `tests/golden/` —— §6 基线(每只 preset 一个)
- `uptrend_pullback/regime.py` —— 市场级 regime gate(因果,只用 ≤T 数据)
