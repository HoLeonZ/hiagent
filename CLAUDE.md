# hiagent — 开发注意事项

## 回测框架使用规范

任何策略的最终回测结果，**必须**经过专业回测框架（backtrader / zipline /
vectorbt 等）的 broker 现金流记账，不能用纯 pandas 自循环充当 Phase 2。
简化路径会绕过 commission 最低收费、印花税单向、成交滑点等市场微观规则，
导致 CAGR 不可复现。

框架约定的"硬事实"（写策略前必须理解）：

- **市价单在下一根 bar 开盘才成交**。决策时看到的触发价 ≠ 实际成交价。
  必须通过订单完成事件捕获实际 fill price，PnL 与 trade 记录都按实际成交价算。
- **broker 报回的净 PnL 是真值**。fees 应该从 gross - net 反推，不要用
  `notional × commission_rate` 这种近似公式（漏掉最低收费等约束）。
- **position 在 `buy()` 调用后还需等下一根 bar size 才 > 0**。持仓判定与
  撮合判定分两层：撮合由框架负责，策略只关心 entry/exit 信号与 bar 内优先级。
- **下单 ≠ 成交**。订单可能被撤、拒、保证金不足，策略必须监听订单状态事件
  而非假设必成交。
- **写新功能前先验证框架 API**。官方文档未必覆盖所有边界，无把握时加最小
  单元测试（feed + 策略 + broker + 一笔成交 → 验证 cash 变化）。

## Look-Ahead Bias 防御协议（项目硬约束）

量化回测中最隐蔽的 bug 类。任何"用未来的数据提前决策"都会让回测 CAGR
虚高且不可复现。本协议禁止在无显式豁免注释的情况下违反以下任何一条。

回归测试覆盖见 `tests/test_uptrend_pullback_no_lookahead.py`（P0×4 + P1×2 +
P2×2 + P3×5，共 13 个测试，全绿才可合并）。

### P0 — 自适应参数必须用「决策时已知」的值

任何基于行情计算的动态阈值（ATR、波动率、量能分位等）都必须用决策时刻
已收市的 K 线数据，不能用还没发生的 K 线。常见错误：用 entry 当根 K 线
的 high/low 计算止损（开盘时不可知）。

### P1 — exit_price 必须是「实际成交价」，不是「触发价」

触发价 = 策略决定退出的那根 K 线上的 TP/SL 触发价；成交价 = 下一根 bar
开盘的实际 fill price。两者不可混用，否则 PnL 口径不一致 1 根 bar。

### P2 — trade 记录必须携带决策时的状态快照

策略用的动态阈值（ATR%、signal 时点的指标值等）必须写入 trade 记录，否则
下游验证阶段拿不到这些信息，会静默退化为固定参数。

### P3 — 禁止同日买卖 / 入场当日不判退出

T 日收盘产生信号、T+1 开盘成交（任何 T+1 制度的市场都适用）。入场当日
策略必须不判退出，从下一根 bar 起才检查 TP/SL/time。两阶段架构下撮合层
与策略层都需要守卫，缺一会留下隐蔽穿越。

不变量：exit_date > entry_date（≥1 日历日）、hold_days ≥ 1、exit_price
不能等于 entry 当天 OHLC 任一值。

### P4 — DB schema 以实际查询为准，不靠注释 / 旧假设

第一次写 SQL 前必须 `DESCRIBE` 或 `SELECT * LIMIT 1` 验证列名。任何
`xxx AS yyy` 别名都先确认 xxx 真存在。

### P5 — 退出优先级（同一根 K 线内，盘后口径）

```
1. open ≤ sl_p      → SL @ open         （开盘跳空破止损）
2. open ≥ tp_p      → TP @ open         （开盘跳空破止盈）
3. low  ≤ sl_p      → SL @ sl_p         （盘中触止损）
4. high ≥ tp_p      → TP @ tp_p         （盘中触止盈）
5. bars ≥ max_hold  → time @ close      （到期 — 必须 close，不能用 tp/sl 触发价）
```

### P6 — 信号 vs 入场是两道不同闸门

业务条件（趋势、回调、流动性、择时）属于信号层；资金条件（仓位、现金、
涨跌停、最小手数）属于执行层。两者解耦，禁止把资金约束塞进信号层。

### P7 — indicator 必须按 (entity, date) 严格分组

任何 rolling / shift / cumsum / cumcount 等跨行操作必须按标的分组，
否则会出现跨股票 / 跨账户的隐式泄漏。

### P8 — universe 不能包含「未来退市股」

universe 必须按回测截止日的"在市"集合取，模拟遇空 panel 跳过而非报错，
否则引入 survivorship bias。

## 自检清单（提交前必跑）

```
[ ] 改 entry_date 当根 K 线的 OHLCV → 回测结果不变？
[ ] 改 T+1 及以后任意 K 线 → 信号日的信号结果不变？
[ ] 删除入场当日"不判退出"守卫 → 单测失败？
[ ] 把 exit_price 从实际成交价改成触发价 → 单测失败？
[ ] 把 max_hold 到期 exit 从 close 改成 high → 单测失败？
[ ] 真实 trades.csv：(exit_date - entry_date).days ≥ 1 全通过？
[ ] 跨股票 rolling → 跨股票污染测试失败？
[ ] pytest tests/test_uptrend_pullback_no_lookahead.py 全绿？
```