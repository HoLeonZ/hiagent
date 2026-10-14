# 跨策略 §3 Dual-Price 审计 (2026-10-14)

对 4 个回测策略的信号/执行价格域做统一审计, 检查是否存在 CLAUDE.md §3
「Dual-Price System」违规 —— 尤其是「同一策略内混用原始价与复权价」这类
会导致信号条件静默失效 (no-op) 的潜伏 bug。

## 结论表

| 策略 | 信号价域 | 执行价域 | 状态 |
|------|----------|----------|------|
| short_reversal | A/B/C = 原始价, MA/MACD = 复权价 (**混用**) | raw | ❌ 潜伏 bug |
| chase_up | v_daily_qfq (前复权) | raw_kline_daily (原始) | ✅ §3 正确 |
| uptrend_pullback | v_daily_qfq (前复权) | raw_kline_daily (原始) | ✅ §3 正确 |
| cycle_price_action | v_daily (原始, 单价格域) | v_daily (原始) | ⚠️ §3 缺口但内部一致 |

## short_reversal bug 详情

- **症状**: A 条件 `close < MA60` 中, `close` 取自 `d.close` (v_daily 原始价),
  但 `MA60` 由 `adj_close` (v_daily_hfq 前复权) 计算。原始价系统性低于前复权价
  (二者平均偏差约 55%), 导致 `close < MA60` 几乎恒为真 → A 条件的核心过滤
  实际是 no-op; B (连阳) / C (涨跌幅) 亦把除权日跳空误判。
- **修复**: 引入 `signal_price_domain` 开关 ('raw' 默认兼容 / 'adj' §3 合规),
  把 A/B/C 的价格源统一到 adj_close。见分支 `feat/short-reversal-adj-close-signal-fix`。
- **影响**: 修复后绝对表现下降约 16% (短窗口) —— 说明原表现部分依赖该 bug;
  但「移除 F 条件」这一结论在 §3 正确语义下依然成立。

## 为何其他策略无此 bug

- chase_up / uptrend_pullback: 信号全程用 qfq (adj), 执行用 raw_kline_daily,
  是**一致**的 dual-price 实现 —— 不存在「同一条件内两个域」的错配。
- cycle_price_action: 单价格域 (v_daily = raw) 贯穿信号与执行 —— 存在
  「信号应用复权价」的 §3 缺口, 但域内部一致, 不会产生 no-op 类静默失效。

## 通用检查项 (用于新策略)

1. 每个信号 indicator (含 MA/MACD/涨跌幅/连阳/累计回报等) 是否与它被比较的
   价格同域? (混用 → 条件静默失效)
2. 执行触发 (SL/TP/limit-up-down/mark-to-market) 是否用 raw? (§3 要求)
3. 若策略只用一个价格域, 明确它是 raw 还是 adj, 并在文件头声明 (§3 缺口)。

---

*本审计记录的是价格域的一致性状态, 不含任何回测绩效数字 (CLAUDE.md §7)。*
