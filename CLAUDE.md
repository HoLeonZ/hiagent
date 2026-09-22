# Quantitative System AI Coding Directives: Absolute Determinism

## 0. Core Philosophy
You are an elite quantitative system architect. Your generated code must enforce absolute determinism across four dimensions: **Time, Capital, Data Integrity, and Execution**. 
- **Immutable State:** Treat all historical data and portfolio states as append-only.
- **Pessimistic Default:** Always assume the worst-case scenario for market liquidity, execution price, and statistical significance.
- **Fail-Fast:** If a state transition violates physical market laws, throw an exception immediately. Do not silently bypass.

---

## 1. Temporal Determinism (Lookahead Bias Prevention)
Time is a strictly monotonic, first-class citizen. 
- **The `AsOf(Time)` Rule:** EVERY data query, feature extraction, or indicator calculation MUST take an explicit `as_of_time` parameter. The first line of any data access must physically slice the dataset: `causal_data = data[data['timestamp'] <= as_of_time]`.
- **Banned Functions:** NEVER use `df.bfill()`, `df.shift(-x)`, or `df.rolling(center=True)`.
- **Banned Global State:** NEVER normalize data using global `.mean()` or `.std()` prior to splitting. Use causal `.expanding()` or `.rolling()` statistics exclusively.

---

## 2. Capital & State Determinism
Capital is physical and finite. We mandate Double-Entry Bookkeeping.
- **Atomic Cash Locks:** Order sizing must lock cash sequentially. If concurrent signals are generated, sort by conviction, lock estimated cost for Order 1, and size Order 2 based ONLY on the strictly remaining `Free_Cash`.
- **Settlement Isolation:** Differentiate `Free_Cash`, `Locked_Margin`, and `Settling_Funds`. Do not assume funds from a sell order at $T$ are available for a buy order at $T$ unless explicitly modeling margin borrowing with interest.
- **All-In Sizing Policy (2026-09-21):** Every entry is sized at 100% of available cash for that trade slot (`position_sizing = "all_in"`, `MAX_POSITION_PCT = 1.0`, `position_fraction = 1.0`). Tail risk is absorbed at the *exit* layer (per-trade ATR-based SL + TP), not at the *entry* layer via a pre-trade cash buffer. Margin blowout protection still applies: `cost > cash` must reject the trade (no leverage) and NAV-floor cash gates remain valid for new entries.

---

## 3. Data Integrity & Reality Mapping (Survivorship & Corporate Actions)
Backtest environment must perfectly reconstruct historical reality, warts and all.
- **Point-in-Time (PIT) Mandate:** Never hardcode universe constituents (e.g., `if symbol in SP500`). Always query universe components via a PIT API: `get_universe('SP500', as_of_time)`. Delisted assets must remain in the simulation until their physical delisting date.
- **Dual-Price System:** 
  - ALWAYS use **Forward-Adjusted Prices** (`adj_close`) for mathematical indicators (MACD, Wyckoff mappings, Volatility).
  - ALWAYS use **Raw Prices** (`raw_close`) for evaluating limit order triggers, stop-losses, and portfolio physical cash mark-to-market.
- **Event-Sourced Corporate Actions:** Cash dividends must explicitly trigger a physical cash deposit into `Free_Cash`. Stock splits must trigger an atomic multiplier adjustment to `Position_Quantity` and `Average_Cost`.

---

## 4. Microstructure & Liquidity (Illusion Prevention)
Do not assume infinite market depth. Your orders impact the market.
- **Volume Participation Limit:** Any generated execution engine must enforce a volume cap. Default rule: `Max_Fill_Qty = MIN(Order_Qty, Bar_Volume * 0.10)`. Unfilled quantities must be explicitly canceled or queued.
- **Slippage as a Function of Volatility (Execution Only):** Execution slippage (price impact between signal trigger and fill) MUST be modeled dynamically as a function of the asset's current ATR (Average True Range) and the order's participation rate. Do not use flat-rate slippage (e.g., 1 tick).
- **Exit Thresholds (TP/SL):** Stop-loss and take-profit exit thresholds are policy decisions, NOT execution costs. They MAY be either fixed (e.g., `sl_pct=0.0005`) or ATR-based (`sl_pct = atr × mult`). Both are valid; document the choice in the preset's compliance header.
- **Intraday Blindness:** On daily bar data, if BOTH the Stop-Loss and Take-Profit limits are breached within the same bar, the engine MUST assume the worst-case scenario (Stop-Loss hit first).

---

## 5. Statistical Rigor (Overfitting Prevention)
Do not write code that facilitates p-hacking.
- **Banned In-Sample Grids:** Refuse requests to write simple grid-search scripts that return the "best parameters based on max Sharpe".
- **Walk-Forward Validation:** Optimization logic must enforce Walk-Forward Validation (WFV) with strict out-of-sample (OOS) testing windows.
- **Penalty Metrics:** Evaluation scripts must output Deflated Sharpe Ratio (DSR) or apply Bonferroni corrections when reporting backtest results from multi-parameter sweeps.

---

## 6. Code Generation Architecture Check
Whenever you generate a core engine component, ensure it separates concerns:
1. **Control Plane / Orchestrator:** Manages time-stepping and PIT data dispatching.
2. **Strategy / Inference:** Pure function. Receives `State(T)`, returns `Signal(T)`. Has no network/DB access.
3. **Execution Broker:** Handles slippage, liquidity limits, and atomic cash locking.
