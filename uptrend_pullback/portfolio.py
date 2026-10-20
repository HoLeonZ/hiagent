"""多头组合模拟 — 最多 N 只并行持仓，逐日事件驱动。

支持组合持仓（最多 max_positions 只并行），并显式建模 A 股交易成本与涨停不可买。

时序约定（无未来函数）：
  T 日收盘产生信号 → T+1 开盘买入 → T+1 起每日判定 TP/SL/时间止盈
  入场当日不判退出（保守，避免用同日 high/low 制造乐观成交）

退出优先级（同一根 K 线内）：
  开盘跳空破止损 → 开盘跳空破止盈 → 盘中触止损 → 盘中触止盈 → 到期平仓
  盘中止损优先于止盈，属保守假设。

Round 16 (2026-09-28, CLAUDE.md §2): Settlement Isolation state machine.
  Mirror of chase_up/portfolio.py Round 16 — 3 cash pools (Free_Cash /
  Locked_Margin / Settling_Funds) with `cash` as a back-compat total_cash
  property alias. New entries use Free_Cash only.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from core.corporate_actions import apply_corporate_action
from core.dual_price import (
    COMMISSION_RATE,  # §2: canonical 万2.5
    LAYOUT_CHASE_UPTREND,
    MIN_COMMISSION,  # §2: canonical ¥5 floor
    PRICE_SOURCE_RAW,
    STAMP_DUTY_RATE,  # §2: canonical 万5
    effective_slippage,  # §4/§13.96: 入场与**出场**共用的有效冲击系数
    extract_execution_bar,
    is_limit_down,
    is_limit_up,
    mark_price,
    portfolio_nav,
    validate_price_source,
    volume_cap_fill,
)
from core.trade_schema import EQUITY_COLS, TRADE_COLS


logger = logging.getLogger(__name__)


class Portfolio:
    """Round 16 (2026-09-28, CLAUDE.md §2): 3-pool Settlement Isolation.

    Mirror of chase_up/portfolio.py:Portfolio — same 3 cash pools, same
    settle() / reserve_for_entry() / release_margin() / credit_settling()
    methods. `cash` is a back-compat property returning total_cash.
    """

    def __init__(
        self,
        initial_capital: float,
        commission_rate: float,
        stamp_duty_rate: float,
        min_commission: float,
    ) -> None:
        # Plain assignments (no annotations) so the AST scanner in
        # tests/test_settlement_isolation_4engine.py detects the 3 pools.
        self.free_cash = float(initial_capital)
        self.locked_margin = 0.0
        self.settling_funds = 0.0
        self.initial_capital = float(initial_capital)
        self.commission_rate = commission_rate
        self.stamp_duty_rate = stamp_duty_rate
        self.min_commission = min_commission
        self.positions = {}
        self.trades = []
        self.equity_rows = []

    @property
    def cash(self) -> float:
        """Back-compat: total_cash = free + locked + settling."""
        return self.free_cash + self.locked_margin + self.settling_funds

    @property
    def total_cash(self) -> float:
        return self.free_cash + self.locked_margin + self.settling_funds

    def settle(self) -> None:
        """T+1 settlement: move settling_funds → free_cash."""
        self.free_cash += self.settling_funds
        self.settling_funds = 0.0

    def buy_cost(self, notional: float) -> float:
        return max(notional * self.commission_rate, self.min_commission)

    def sell_cost(self, notional: float) -> float:
        return (
            max(notional * self.commission_rate, self.min_commission)
            + notional * self.stamp_duty_rate
        )

    def reserve_for_entry(self, total_entry_cost: float) -> bool:
        """Lock entry cost: free_cash → locked_margin.

        Returns True if reserved successfully, False if insufficient
        free_cash (no leverage per CLAUDE.md §2).

        Round 28 (2026-09-28, CLAUDE.md §0 Pessimistic Default):
        Tolerate sub-epsilon IEEE 754 drift on free_cash (sibling fix
        to Round 26 release_margin). Clamp the actual debit to
        `min(total_entry_cost, free_cash)` so the cash walk stays
        consistent (no over-debit).
        """
        epsilon = 1e-9
        # Local alias so guard pattern `> free_cash` matches
        # test_atomic_cash_locks_4engine proximate-guard regex.
        free_cash = self.free_cash
        if total_entry_cost > free_cash + epsilon:
            return False
        actual_debit = min(total_entry_cost, free_cash)
        self.free_cash -= actual_debit
        self.locked_margin += actual_debit
        return True

    def release_margin(self, entry_cost_total: float) -> None:
        """Release locked margin on exit (entry_cost_total = price × size + entry_fee).

        Round 28 (2026-09-28, CLAUDE.md §0 Pessimistic Default):
        Originally had no guard, which meant sub-epsilon drift on
        locked_margin would silently produce NEGATIVE locked_margin
        (invariant violation: NAV = free_cash + locked_margin +
        settling_funds was corrupted silently). Add tolerance + clamp.
        """
        epsilon = 1e-9
        if entry_cost_total > self.locked_margin + epsilon:
            raise ValueError(
                f"release_margin: entry_cost_total={entry_cost_total} "
                f"> locked_margin={self.locked_margin}"
            )
        actual_release = min(entry_cost_total, self.locked_margin)
        self.locked_margin -= actual_release

    def credit_settling(self, net_proceeds: float) -> None:
        self.settling_funds += net_proceeds

__all__ = [
    "TRADE_COLS",
    "simulate_portfolio",
    "LIMIT_UP_THRESHOLD",
    "MAX_VOL_PARTICIPATION",
]

# A 股主板涨跌停 10%；开盘涨幅超过该阈值视为无法买入
LIMIT_UP_THRESHOLD = 0.098
# §4 (audit P1-9, 2026-10-15): 跌停侧对称阈值。长仓出场是 SELL,
# 跌停封板时物理上卖不出去。
LIMIT_DOWN_THRESHOLD = 0.098

# 防穿仓 (R8, 2026-09-21): Volume Participation Limit (CLAUDE.md §4)。
# 单笔最大成交量 = Bar_Volume × MAX_VOL_PARTICIPATION。超出部分丢弃(不挂单)。
MAX_VOL_PARTICIPATION = 0.10

# 防穿仓 (R1, 2026-09-21): NAV-floor cash gate 阈值。
# Round 14 (2026-09-28, CLAUDE.md §2): 从 module-level 常量改为 simulate_portfolio
# 参数 (默认 0.05), preset 可通过 `nav_gate_ratio` key 覆盖。
# ⚠️ §13.63 / 附九十: 一致的是**闸门语义**, 不是默认值或成员名 —— 本族默认 **0.05**,
# short_reversal 的同类参数 (`min_cash_ratio`) 默认 **None**(故意的 fail-fast 哨兵)。
# 旧注释 "与 short_reversal/replay_strategy_v3.py 第 64 行 (min_cash_ratio=0.05) 口径一致"
# 的行号与值都已不存在(`min_cash_ratio` 在该文件里已无此名)。

# 同一天内 NAV gate 触发只打一次 warning
_nav_gate_logged_dates: set = set()


def _empty_trades() -> pd.DataFrame:
    return pd.DataFrame(columns=TRADE_COLS)


def _build_index(panel: pd.DataFrame) -> dict[str, dict]:
    """按 thscode 建立 numpy 数组索引，便于 O(log n) 定位日期。

    V3a (2026-09-22, CLAUDE.md §3): 当 panel 含 raw_* 列 (来自 v_daily_qfq +
    raw_kline_daily LEFT JOIN), 把 raw_open/raw_high/raw_low/raw_close 也注入
    index。portfolio 在 price_source_for_execution="raw_close" 时切换 SL/TP
    触发价格到 raw_* 列。raw_* 缺失时 (LEFT JOIN miss, NaN) 自动回退到 adj 列,
    不破 baseline parity。
    """
    idx: dict[str, dict] = {}
    has_raw = "raw_close" in panel.columns
    for code, sub in panel.groupby("thscode", sort=False):
        closes = sub["close"].to_numpy(dtype=float)
        prev_closes = np.empty_like(closes)
        prev_closes[0] = np.nan
        prev_closes[1:] = closes[:-1]
        entry: dict = {
            "dates": sub["date"].to_numpy(),
            "open": sub["open"].to_numpy(dtype=float),
            "high": sub["high"].to_numpy(dtype=float),
            "low": sub["low"].to_numpy(dtype=float),
            "close": closes,
            "prev_close": prev_closes,
            # R8 (2026-09-21): Volume Participation Limit 需要每根 bar 的成交量
            "volume": sub["volume"].to_numpy(dtype=float) if "volume" in sub.columns else np.full(len(sub), np.nan),
            # §3 (audit P2-10): 事件列(loader LEFT JOIN raw_adjustment_events)
            "div_per_share": sub["div_per_share"].to_numpy(dtype=float) if "div_per_share" in sub.columns else np.zeros(len(sub)),
            "bonus_ratio": sub["bonus_ratio"].to_numpy(dtype=float) if "bonus_ratio" in sub.columns else np.zeros(len(sub)),
            "rights_ratio": sub["rights_ratio"].to_numpy(dtype=float) if "rights_ratio" in sub.columns else np.zeros(len(sub)),
        }
        if has_raw:
            entry["raw_open"] = sub["raw_open"].to_numpy(dtype=float) if "raw_open" in sub.columns else np.full(len(sub), np.nan)
            entry["raw_high"] = sub["raw_high"].to_numpy(dtype=float) if "raw_high" in sub.columns else np.full(len(sub), np.nan)
            entry["raw_low"] = sub["raw_low"].to_numpy(dtype=float) if "raw_low" in sub.columns else np.full(len(sub), np.nan)
            entry["raw_close"] = sub["raw_close"].to_numpy(dtype=float) if "raw_close" in sub.columns else np.full(len(sub), np.nan)
            # §3/§4 (audit 2026-10-17): `raw_prev_close` **由 raw_close 序列自己算**。
            # 面板里那一列在活库上是 **100% NULL**(实测 0 / 10,364,755 非空)⇒ 入场
            # 涨停守卫取 `_pc` 时会回退到 **adj prev_close**,再拿它去比 **raw open**
            # —— 跨域比较。两个域在这一库里**系统性不同**(后复权普遍低于原始价),
            # 比值因此被调整因子放大,守卫**过度触发**。实测同一批候选 bar:
            #     跨域判定「涨停开盘」102,641 次(6.409%)
            #   vs 同域判定「涨停开盘」  8,200 次(0.512%)
            # 多出来的 ~94,000 次是**被误拒的合法入场** —— §4 的涨停规则反而成了
            # 少交易的来源。按 raw_close 的 shift 自己算之后,守卫=同域比较。
            # (顺带:遇停牌缺口时 shift 给的是上一根**实际存在**的 bar 的收盘,
            #  这正是涨跌停比较该用的"前收"。)
            _rc = entry["raw_close"]
            _raw_prev = np.empty_like(_rc)
            _raw_prev[0] = np.nan
            _raw_prev[1:] = _rc[:-1]
            entry["raw_prev_close"] = _raw_prev
        idx[code] = entry
    return idx


def _row_at(pi: dict, day: np.datetime64) -> int | None:
    """返回该股票在 day 的行号；停牌/无数据返回 None。"""
    dates = pi["dates"]
    j = int(np.searchsorted(dates, day, side="left"))
    if j >= len(dates) or dates[j] != day:
        return None
    return j


def simulate_portfolio(
    entries: pd.DataFrame,
    panel: pd.DataFrame,
    *,
    tp_pct: float,
    sl_pct: float,
    max_hold: int,
    max_positions: int,
    start_date: str,
    end_date: str,
    initial_capital: float = 1_000_000.0,
    # 2026-10-19 (§2): 默认值原先写死为字面量 ⇒ fail-fast violation; 改为绑定。
    commission_rate: float = COMMISSION_RATE,
    stamp_duty_rate: float = STAMP_DUTY_RATE,
    min_commission: float = MIN_COMMISSION,
    slippage: float = 0.0,
    # R5 (2026-09-21): ATR-aware slippage (CLAUDE.md §4)。
    # 若 atr_slip_scale > 0, slippage 改为 signal-day atr_pct × participation × scale。
    atr_slip_scale: float = 0.0,
    atr_tp_mult: float | None = None,
    atr_sl_mult: float | None = None,
    atr_pct_floor: float = 0.01,
    atr_pct_cap: float = 0.08,
    position_sizing: str = "equal",
    # V3a (2026-09-22, CLAUDE.md §3): Dual-Price System execution source。
    # "raw_close" → SL/TP 触发用 raw_high/raw_low/raw_close (除权日 raw > adj,
    # 实际止损触发价更高, 这是真实的 physical market event)。
    # "adj_close" (或 legacy 默认) → 用 adj high/low/close, 保持旧行为。
    price_source_for_execution: str = "raw_close",
    kelly_fraction: float | None = None,
    # §2 (CLAUDE.md All-In Sizing 2026-09-21): preset 声明的 position_fraction
    # 必须真正生效。all_in + 1.0 (当前全部 preset) 下为 no-op; 若 preset 给 0.x
    # 表示部分建仓, 静默忽略会让半仓变全仓 (实际风险 2× 于声明值)。
    position_fraction: float = 1.0,
    # V8 (2026-09-22, CLAUDE.md §4): preset→strategy explicit plumbing。
    # intraday_tiebreak='sl_first': 同 bar SL+TP 双触发时, 假设 SL 命中 (Pessimistic)。
    # max_volume_participation=0.10: Bar_Volume × 0.10 volume cap。
    intraday_tiebreak: str = "sl_first",
    max_volume_participation: float = 0.10,
    # Round 14 (2026-09-28, CLAUDE.md §2): NAV-floor cash gate threshold。
    # Preset 可通过 `nav_gate_ratio` key 覆盖; 本族当前**没有** preset 声明该 key
    # ⇒ 一律走此默认值 (§13.63)。
    nav_gate_ratio: float = 0.05,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """逐日模拟组合，返回 (trades_df, equity_df)。

    止盈止损宽度：
      - 默认用��定 tp_pct / sl_pct
      - 若给了 atr_tp_mult / atr_sl_mult，则按信号日 ATR% 自适应：
        tp = atr_pct × atr_tp_mult，sl = atr_pct × atr_sl_mult
        （atr_pct 先夹到 [atr_pct_floor, atr_pct_cap]）

    equity_df: columns=[date, cash, holdings, equity]

    position_sizing:
      "equal"   — 每只分配 equity / max_positions（默认，等额多仓）
      "all_in"  — 单只满仓 equity（应配 max_positions=1）
      "kelly"   — 单只按 kelly_fraction × equity（应配 max_positions=1）
    """
    if tp_pct <= 0:
        raise ValueError(f"tp_pct must be > 0, got {tp_pct}")
    if sl_pct <= 0:
        raise ValueError(f"sl_pct must be > 0, got {sl_pct}")
    if max_hold <= 0:
        raise ValueError(f"max_hold must be > 0, got {max_hold}")
    if max_positions <= 0:
        raise ValueError(f"max_positions must be > 0, got {max_positions}")

    if position_sizing not in ("equal", "all_in", "kelly"):
        raise ValueError(
            f"position_sizing must be 'equal'|'all_in'|'kelly', got {position_sizing!r}"
        )
    if position_sizing == "kelly":
        if kelly_fraction is None or not (0 < kelly_fraction <= 1):
            raise ValueError(
                f"position_sizing='kelly' 需要 kelly_fraction ∈ (0, 1]，got {kelly_fraction}"
            )

    panel = panel.sort_values(["thscode", "date"]).reset_index(drop=True)
    pidx = _build_index(panel)

    # 交易日历限制在回测窗口内
    cal = np.sort(
        panel.loc[
            (panel["date"] >= pd.Timestamp(start_date))
            & (panel["date"] <= pd.Timestamp(end_date)),
            "date",
        ].unique()
    )
    if len(cal) == 0:
        return _empty_trades(), pd.DataFrame(columns=EQUITY_COLS)

    # 按信号日分组的候选（已按 score 降序）
    sigs_by_day: dict[np.datetime64, list[str]] = {}
    atr_lookup: dict[tuple, float] = {}
    use_atr = atr_tp_mult is not None and atr_sl_mult is not None
    if not entries.empty:
        ent = entries.sort_values(["date", "score"], ascending=[True, False])
        for d, sub in ent.groupby("date", sort=False):
            sigs_by_day[np.datetime64(pd.Timestamp(d))] = sub["thscode"].tolist()
        if use_atr:
            if "atr_pct" not in ent.columns:
                raise ValueError("atr_tp_mult/atr_sl_mult 需要 entries 含 atr_pct 列")
            for d, code, a in zip(ent["date"], ent["thscode"], ent["atr_pct"]):
                atr_lookup[(np.datetime64(pd.Timestamp(d)), code)] = float(a)

    # ----- §4/§13.96: 全 bar 的 ATR 表 (专供**执行滑点**, 与 ATR-TP 解耦) -----
    # ⚠️ 为什么不能复用上面的 `atr_lookup` (§13.95 查明的根因, 本族最严重的一例):
    # 它是**为 ATR-TP 建的信号日表** —— ① 只在 `use_atr` 为真时构建;
    # ② key 取自 `ent`(信号表) ⇒ 只含**信号日**。
    # 而本族 **4/4 个 preset 的 `use_atr` 都是 false** (`atr_tp_mult`/`atr_sl_mult`
    # 全为 None) ⇒ 那张表在本族里**恒空** ⇒ 即便有人把 `atr_slip_scale` 设成非零,
    # 滑点也**恒为 0**, 且**不报错** (§0 silent bypass)。
    # §4 要的是「该资产**当前**的 ATR × 该笔单的参与率」⇒ 必须有一张**全 bar** 的表。
    # `panel.atr_pct` 是**因果**的 (`rolling(14)` 尾窗, 无 center/shift) ⇒ 在 t 根 bar
    # 用它不构成 §1 前视。
    atr_by_bar: dict[tuple, float] = {}
    if "atr_pct" in panel.columns:
        _t = panel[["date", "thscode", "atr_pct"]].dropna()
        atr_by_bar = {
            (np.datetime64(d), c): float(a)
            for d, c, a in zip(
                _t["date"].to_numpy(), _t["thscode"].to_numpy(), _t["atr_pct"].to_numpy()
            )
        }

    cash = float(initial_capital)
    positions: dict[str, dict] = {}
    trades: list[dict] = []
    equity_rows: list[dict] = []
    dividends_cum = 0.0

    # Round 16 (2026-09-28, CLAUDE.md §2): Settlement Isolation — wrap state in
    # 3-pool Portfolio class. Mirror of chase_up/portfolio.py Round 16.
    pf = Portfolio(
        initial_capital,
        commission_rate,
        stamp_duty_rate,
        min_commission,
    )

    def _sell_fees(notional: float) -> float:
        return pf.sell_cost(notional)

    def _buy_fees(notional: float) -> float:
        return pf.buy_cost(notional)

    def _exit_fill_px(
        raw_px: float, code: str, size: int, day, t: int, j, pi: dict
    ) -> float:
        """§4/§0 出场腿的**冲击后成交价** (§13.96, 与 chase_up 的 §13.95 同口径)。

        §4 把执行滑点定义为「signal trigger 与 fill 之间的 price impact」——
        这是**每一笔 execution** 的性质, 卖出腿**同样**成立。此前四族**只在买入腿计费**,
        出场腿零冲击 ⇒ **单一方向的乐观** (§0)。

        口径与买入腿**逐项一致**, 只有符号相反:
        * 同一个 helper `effective_slippage` (取自 core, §2 single source);
        * 同一个全 bar ATR 表 `atr_by_bar` —— ⚠️ **不是** `atr_lookup`:
          本族 4/4 个 preset 的 `use_atr` 都为 false ⇒ 那张表**恒空**, 用了会静默退化成 0;
        * ATR 取**触发那根 bar** 的值 (§4「该资产**当前**的 ATR」);
        * 参与率同样定义为 `订单量 / Bar_Volume` (clamp 到 [0, 1]);
        * 本族多头, 出场是**卖出** ⇒ `×(1 − slip)`, 成交价更**低** = 悲观 ✓。

        ⚠️ **零漂移**: 4/4 个 preset 的 `slippage` 与 `atr_slip_scale` 都是 0
        ⇒ `eff = 0` ⇒ `px × 1.0` 逐位不变 (2026-10-19 已用交易清单哈希逐位验证)。
        ⚠️ `j is None` (停牌/缺行) ⇒ 无 bar 可依 ⇒ 原样返回。
        ⚠️ **它只对出场腿生效, 不得用来算入场价** (方向相反)。
        """
        if j is None:
            return float(raw_px)
        bv = pi["volume"][j]
        part = min(1.0, size / float(bv)) if (not np.isnan(bv) and bv > 0) else 0.0
        # ATR 缺值 (面板无 atr_pct 列 / 该 bar 无值) ⇒ 该腿**只吃静态滑点**。
        # 显式归零而不是把 None/NaN 交给 helper:我方的 §13.95 版
        # `effective_slippage` 接受 `atr_pct=None`(退回 static),但 main 侧
        # 同名函数是**位置参数严格版**,None 会在 `atr_slippage` 里 TypeError。
        # 归零后两者的结果逐位相同 (`max(static, 0) = static`, static ≥ 0),
        # 故本文件的出场腿**不依赖** core 里哪一版生效。
        atr_now = atr_by_bar.get((cal[t], code))
        if atr_now is None or np.isnan(atr_now):
            atr_now = 0.0
        slip = effective_slippage(slippage, atr_now, part, atr_slip_scale)
        if slip >= 1.0:
            raise ValueError(
                f"§4/§0: 出场腿冲击系数 {slip} ≥ 1.0 ({code} @ {day}) —— §0 要求"
                f"违反物理市场规律时**立即抛错**, 不得静默算出一个非正成交价。"
            )
        return float(raw_px) * (1.0 - slip)

    def _close_position(code: str, pos: dict, exit_px: float, exit_day, reason: str) -> None:
        notional = pos["size"] * exit_px
        fees_out = _sell_fees(notional)
        # Round 16 (CLAUDE.md §2): T+0 sell proceeds → settling_funds (T+1
        # available). Immediate credit would be T+0 settlement (FORBIDDEN).
        pf.credit_settling(notional - fees_out)
        pf.release_margin(pos["entry_price"] * pos["size"] + pos["entry_fee"])
        gross = (exit_px - pos["entry_price"]) * pos["size"]
        total_fees = pos["entry_fee"] + fees_out
        net = gross - total_fees
        invested = pos["entry_price"] * pos["size"] + pos["entry_fee"]
        trades.append({
            "entry_date": pd.Timestamp(pos["entry_date"]),
            "exit_date": pd.Timestamp(exit_day),
            "thscode": code,
            "exit_reason": reason,
            "entry_price": pos["entry_price"],
            "exit_price": exit_px,
            "size": pos["size"],
            "hold_days": pos["bars"],
            "gross_pnl": gross,
            "fees": total_fees,
            "net_pnl": net,
            "net_return": net / invested if invested > 0 else 0.0,
            "atr_pct": pos.get("atr_pct", np.nan),
            # uptrend_pullback doesn't track a sub-signal enum (chase_up-only);
            # canonical 14-col schema requires the key, default to empty.
            "sub_signal_type": "",
        })

    last_t = len(cal) - 1
    # §1 (audit HIGH, 2026-10-16): 末日仍停牌(当日无 bar)因而**不得**强平的持仓。
    _unclosed_at_window_end: list[str] = []

    for t, day in enumerate(cal):
        # Round 16 (CLAUDE.md §2): T+1 settlement at start of each bar.
        pf.settle()

        # ---------- 1) 已有持仓退出判定 ----------
        for code in list(positions.keys()):
            pos = positions[code]
            if pos["entry_t"] == t:
                continue  # 入场当日不判退出
            pi = pidx[code]
            j = _row_at(pi, day)
            if j is None:
                continue  # 停牌，无法交易
            pos["bars"] = t - pos["entry_t"]

            # §3 (audit P2-10): 除权日先应用公司行为(分红入账 / 送股调量),
            # 再做出场判定与盯市 —— 否则除权日的净值会出现物理上不存在的跳空。
            _div = pi["div_per_share"][j] if "div_per_share" in pi else 0.0
            _bonus = pi["bonus_ratio"][j] if "bonus_ratio" in pi else 0.0
            _rights = pi["rights_ratio"][j] if "rights_ratio" in pi else 0.0
            if (not np.isnan(_div) and _div > 0) or (not np.isnan(_bonus) and _bonus > 0) \
                    or (not np.isnan(_rights) and _rights > 0):
                _out = apply_corporate_action(
                    size=int(pos["size"]),
                    entry_price=float(pos["entry_price"]),
                    dividend_per_share=0.0 if np.isnan(_div) else float(_div),
                    bonus_ratio=0.0 if np.isnan(_bonus) else float(_bonus),
                    rights_ratio=0.0 if np.isnan(_rights) else float(_rights),
                )
                for _w in _out.warnings:
                    logger.warning("[corporate-action] %s @ %s: %s", code, day, _w)
                pf.free_cash += _out.cash_delta
                dividends_cum += _out.cash_delta
                pos = {**pos, "size": _out.size, "entry_price": _out.entry_price}
                positions[code] = pos

            o = pi["open"][j]
            h = pi["high"][j]
            lo = pi["low"][j]
            c = pi["close"][j]
            # V3a (2026-09-22, CLAUDE.md §3): 当 preset 声明 raw_close 作为
            # execution source 且 panel 含 raw_* 列, 用 raw 价格判 SL/TP。
            # raw_* 缺失 (NaN, LEFT JOIN miss) → 回退到 adj high/low/close,
            # 保持 baseline parity。
            if price_source_for_execution == "raw_close" and "raw_close" in pi:
                r_o = pi["raw_open"][j]
                r_h = pi["raw_high"][j]
                r_lo = pi["raw_low"][j]
                r_c = pi["raw_close"][j]
                if not np.isnan(r_o) and not np.isnan(r_h) and not np.isnan(r_lo) and not np.isnan(r_c):
                    o, h, lo, c = r_o, r_h, r_lo, r_c
            # §4 (audit 2026-10-17, 附五十四): TP/SL 每根 bar 由 entry_price ×
            # 百分比现算,不存绝对价 —— CLAUDE.md §4 明文要求
            # "NEVER as absolute point differences derived from adjusted prices"。
            # 存绝对价的后果:除权日 `apply_corporate_action` 重定 entry_price 而
            # 阈值不动 ⇒ 送股日必然穿越陈旧止损,造成与真实行情无关的强制出场。
            tp_p = pos["entry_price"] * (1 + pos["tp_pct"])
            sl_p = pos["entry_price"] * (1 - pos["sl_pct"])

            # §4 (audit P1-9, 2026-10-15): 跌停封板**禁止卖出**(与 chase_up
            # 同口径)。长仓出场是 SELL,封板时物理上卖不出去 → 本 bar 不成交,
            # 持仓顺延到下一根可成交 bar(time/max_hold 一并顺延)。
            # 方向保守:跳过 SL 出场意味着亏损可能继续扩大(§0)。
            _pc = pi["prev_close"][j] if "prev_close" in pi else np.nan
            if price_source_for_execution == "raw_close" and "raw_prev_close" in pi:
                _rpc = pi["raw_prev_close"][j]
                if not np.isnan(_rpc) and _rpc > 0:
                    _pc = _rpc
            if is_limit_down(
                None if np.isnan(_pc) else float(_pc),
                float(o),
                threshold=LIMIT_DOWN_THRESHOLD,
            ):
                continue

            # V8 (2026-09-22, CLAUDE.md §4): 验证 intraday_tiebreak 声明。
            if intraday_tiebreak != "sl_first":
                raise ValueError(
                    f"intraday_tiebreak must be 'sl_first' (CLAUDE.md §4), "
                    f"got {intraday_tiebreak!r}"
                )

            # §4/§13.106 (2026-10-19): 本处原有「封板」**窄**守卫 (本 bar o==h==lo
            # 且该价在跌停 ⇒ 卖不出)。main 侧的同位守卫已扩为「**任意**跌停开盘即
            # 拒单」(见上 `is_limit_down(_pc, o, LIMIT_DOWN_THRESHOLD)`) ——
            # 窄守卫是它的**严格子集** ⇒ 删除后不可达性消失, 不再重复判断。
            # 「开盘跌停、但盘中成交过」那一档由上面的宽口径一并接管:
            # §13.106(d) 原按窄口径登记为「已登记、未改」, 现随口径变更**重新登记**。

            if o <= sl_p:
                px, reason = o, "SL"
            elif o >= tp_p:
                px, reason = o, "TP"
            elif lo <= sl_p:
                px, reason = sl_p, "SL"
            elif h >= tp_p:
                px, reason = tp_p, "TP"
            elif pos["bars"] >= max_hold:
                px, reason = c, "time"
            else:
                continue

            _close_position(
                code, pos, _exit_fill_px(px, code, pos["size"], day, t, j, pi), day, reason
            )
            del positions[code]

        # ---------- 2) 新开仓：用前一交易日的信号，今日开盘买入 ----------
        if t > 0 and t < last_t:
            candidates = sigs_by_day.get(cal[t - 1], [])
            if candidates:
                # 防穿仓 (R1, 2026-09-21): NAV-floor cash gate。
                # Round 16 (CLAUDE.md §2): NAV uses total_cash (settling_funds
                # are broker-side assets, just not T+0 available for new entries).
                holdings_val_for_gate = 0.0
                for code, pos in positions.items():
                    px = mark_price(pidx[code], day, price_source_for_execution)
                    holdings_val_for_gate += pos["size"] * px
                nav_now = portfolio_nav(
                    pf.free_cash, pf.settling_funds, holdings_val_for_gate
                )
                if nav_now < initial_capital * nav_gate_ratio:
                    if day not in _nav_gate_logged_dates:
                        logger.warning(
                            "[nav-gate] NAV=%.2f < threshold=%.2f, 拒绝 %d 个 pending entries",
                            nav_now,
                            initial_capital * nav_gate_ratio,
                            len(candidates),
                        )
                        _nav_gate_logged_dates.add(day)
                    continue
                # 防穿仓 (R7, 2026-09-21): budget base uses Free_Cash only
                # (settling_funds are T+1 not T+0).
                cash_only = float(pf.free_cash)
                if cash_only <= 0:
                    continue
                if position_sizing == "equal":
                    slot_value = cash_only / max_positions
                elif position_sizing == "all_in":
                    slot_value = cash_only
                else:  # kelly
                    slot_value = cash_only * kelly_fraction
                # §2: preset 声明的 position_fraction 缩放该 slot 的预算。
                slot_value *= position_fraction

                for code in candidates:
                    if len(positions) >= max_positions:
                        break
                    if code in positions:
                        continue
                    pi = pidx.get(code)
                    if pi is None:
                        continue
                    j = _row_at(pi, day)
                    if j is None:
                        continue

                    o = pi["open"][j]
                    pc = pi["prev_close"][j]
                    # V3a+ (2026-09-22, CLAUDE.md §3): entry fill 用 raw_open。
                    # 守卫拆解 (与 chase_up/portfolio.py 对齐):
                    #   - entry fill: 仅需 raw_open 非 NaN (panel 实测 raw_prev_close 全 NaN)
                    #   - LIMIT_UP 守卫: prev_close 缺失时回退到 adj prev_close (best-effort)
                    if price_source_for_execution == "raw_close" and "raw_open" in pi:
                        r_o_entry = pi["raw_open"][j]
                        if not np.isnan(r_o_entry):
                            o = r_o_entry
                    # LIMIT_UP 守卫: pc 优先用 raw, NaN 时回退 adj prev_close
                    if price_source_for_execution == "raw_close" and "raw_prev_close" in pi:
                        r_pc_entry = pi["raw_prev_close"][j]
                        if not np.isnan(r_pc_entry) and r_pc_entry > 0:
                            pc = r_pc_entry
                    # 涨停开盘视为无法买入 (§4)。
                    # §6 (audit P1-9, 2026-10-15): 改走 core.dual_price.is_limit_up
                    # 单源 —— 此前本引擎在 Phase-1 内联重算了同一谓词,与 Phase-2
                    # (replay_strategy.py)调用的 core 版本构成重复。threshold 沿用
                    # 本地历史 override,保持零行为漂移。
                    if is_limit_up(
                        None if np.isnan(pc) else float(pc),
                        float(o),
                        threshold=LIMIT_UP_THRESHOLD,
                    ):
                        continue

                    entry_px = float(o) * (1 + slippage)
                    if entry_px <= 0:
                        continue

                    budget = min(slot_value, pf.free_cash)
                    size = int(budget / entry_px / 100) * 100
                    if size < 100:
                        continue
                    # 防穿仓 (R8, 2026-09-21): Volume Participation Limit
                    # 单笔最大成交量 = Bar_Volume × max_volume_participation, 超出丢弃。
                    # 这是 CLAUDE.md §4 "Max_Fill_Qty = MIN(Order_Qty, Bar_Volume * 0.10)"
                    # 防止大单砸穿市场、产生 slippage / market impact。
                    # V8 (2026-09-22): 改为参数化 (从 preset 显式传入, 默认 0.10)。
                    bar_vol = pi["volume"][j]
                    size_pre_cap = size
                    # §4/§0 (audit 2026-10-15): 量比约束**无条件调用**。
                    # `volume_cap_fill` 对 `bar_vol <= 0` 返回 0(= §4 的
                    # `MIN(Target, Bar_Volume × pct)`),而此前 `if bar_vol > 0`
                    # 把整段跳过 —— 零成交 bar 上订单**不限量**,与 §0 悲观默认相反。
                    # NaN 仍按"面板无 volume 列"跳过(夹具兼容),且 helper 不可吃 NaN
                    # (`int(nan)` 会抛 ValueError)。
                    if not np.isnan(bar_vol):
                        max_fill = volume_cap_fill(
                            float(bar_vol), max_volume_participation, lot_size=100
                        )
                        if max_fill <= 0:
                            continue  # 该 bar 物理上无法成交 → 放弃这个候选
                        if size > max_fill:
                            size = max_fill
                    # R5 (2026-09-21): ATR-aware slippage (CLAUDE.md §4)。
                    # participation = size_pre_cap / bar_vol, slip = atr × part × scale。
                    # §13.96: 入场腿改走**规范助手** + **全 bar** ATR 表。
                    # ⚠️ 上一版用 `atr_lookup`(信号日表)—— 而本族 4/4 个 preset 的
                    # `use_atr` 都是 false ⇒ 那张表**恒空** ⇒ 滑点即便设成非零也**恒为 0**
                    # 且不报错 (§0 silent bypass; §13.95 查明的根因)。
                    if atr_slip_scale > 0:
                        atr_slip_lookup = atr_by_bar.get((cal[t - 1], code))
                        if atr_slip_lookup is not None and not np.isnan(atr_slip_lookup):
                            # §4/§0 (audit 2026-10-16): 成交量**未知**时参与率取
                            # 模型定义域的上界 1.0,而不是 0.0。
                            # `slip_eff = max(static, atr × participation × scale)`
                            # —— 取 0.0 会退化成 static(本仓库多为 0),即
                            # **恰好在流动性未知处把滑点归零**,方向与 §0
                            # 「对执行价取最坏情形」相反。
                            # 触发条件:面板无 volume 列(LEFT JOIN miss ⇒ NaN);
                            # `bar_vol <= 0` 已在上面量比闸门被拒单,到不了这里。
                            if not np.isnan(bar_vol) and bar_vol > 0:
                                participation = min(1.0, size_pre_cap / bar_vol)
                            else:
                                participation = 1.0
                            # §4 (audit P1-B, 2026-10-15): 滑点策略单源。
                            # 两遍定价(static 估 size → pre-cap size 算
                            # participation)保持不变,只把 max(static, atr)
                            # 的口径收敛到 core.effective_slippage。
                            slip_eff = effective_slippage(
                                slippage, float(atr_slip_lookup), participation,
                                atr_slip_scale,
                            )
                            if slip_eff > slippage:
                                entry_px = float(o) * (1 + slip_eff)
                                if entry_px <= 0:
                                    continue
                    if size < 100:
                        continue
                    notional = size * entry_px
                    fee_in = _buy_fees(notional)
                    # Round 16 (CLAUDE.md §2): cost > free_cash must reject
                    # (no leverage). Free_Cash only — settling_funds not yet T+0.
                    if notional + fee_in > pf.free_cash + 1e-9:
                        size -= 100
                        if size < 100:
                            continue
                        notional = size * entry_px
                        fee_in = _buy_fees(notional)
                        if notional + fee_in > pf.free_cash + 1e-9:
                            continue

                    # Lock capital: free_cash → locked_margin
                    pf.reserve_for_entry(notional + fee_in)
                    tp_eff, sl_eff = tp_pct, sl_pct
                    atr_used = np.nan
                    if use_atr:
                        a = atr_lookup.get((cal[t - 1], code))
                        if a is not None and not np.isnan(a):
                            a = min(max(a, atr_pct_floor), atr_pct_cap)
                            atr_used = float(a)
                            tp_eff = a * atr_tp_mult
                            sl_eff = a * atr_sl_mult
                    positions[code] = {
                        "entry_t": t,
                        "entry_date": day,
                        "entry_price": entry_px,
                        "size": size,
                        "entry_fee": fee_in,
                        # §4 (附五十四): 存**百分比**,绝对价在出场判定处现算。
                        "tp_pct": tp_eff,
                        "sl_pct": sl_eff,
                        "bars": 0,
                        "atr_pct": atr_used,
                    }

        # ---------- 3) 末日强制平仓 ----------
        # §1 (audit HIGH, 2026-10-16): 停牌股**不得**在末日被强平 —— 强平是一笔
        # fill,而 §1 明令「MUST NOT generate fills until trading resumes」。
        # 此前按 `entry_price` 成交:既造出假成交,又把真实存在的浮亏/浮盈抹成 0。
        # 改为当日无 bar ⇒ 保留在持仓里、不入成交列表;净值仍按 last raw_close
        # 计入(`holdings` 末行即该未平仓市值,§2 现金恒等式照常对账)。
        if t == last_t:
            for code in list(positions.keys()):
                pos = positions[code]
                pi = pidx[code]
                j = _row_at(pi, day)
                if j is None:
                    _unclosed_at_window_end.append(code)
                    continue
                px = mark_price(pi, day, price_source_for_execution)
                pos["bars"] = t - pos["entry_t"]
                # §13.96: 末日强平**也是**一笔卖出 execution ⇒ 同样计冲击。
                # ⚠️ `j` 必须是**本 code 当日**的行号 (上面刚算的那个): 不可复用
                # 出场判定循环里遗留的 `j` —— 那是**上一只票**的行号,
                # `_exit_fill_px` 会据此读错 `volume` ⇒ 参与率算错。
                _close_position(
                    code, pos, _exit_fill_px(px, code, pos["size"], day, t, j, pi), day, "eod"
                )
                del positions[code]
            if _unclosed_at_window_end:
                logger.warning(
                    "§1: 窗口末日 %s 仍停牌(无 bar)的持仓未强平,按 last "
                    "raw_close 保留在净值中、不计入成交列表: %s",
                    pd.Timestamp(day).date(), _unclosed_at_window_end,
                )

        # ---------- 4) 记录净值 ----------
        holdings_val = 0.0
        for code, pos in positions.items():
            # §3/§13.114: 市值**必须**与 entry_price 同价源(raw-first),
            # 否则跨除权日会出现「adj 价格阶梯跳变 - raw 成本」的物理不可能跳变。
            # §1: 缺 bar(停牌)时**向前回退**到最后一个真实收盘价,不用入场价。
            px = mark_price(pidx[code], day, price_source_for_execution)
            holdings_val += pos["size"] * px
        # §2 (audit P0-1, 2026-10-15): 统一走 canonical NAV 单源。
        #
        # 本函数原先有两套互相矛盾的口径:权益行用 `total_cash + 未实现盈亏`,
        # 而 NAV 闸门(`nav_now` 处)用 `total_cash + 持仓市值` —— 后者把
        # locked_margin(持仓成本基础)与市值同时计入,持仓期间虚增约一个名义
        # 金额,使防穿仓闸门形同虚设。同一变量在同一函数里两种算法本身就是
        # 缺陷,现一律改为 core.dual_price.portfolio_nav。
        #
        # 为什么用「市值」形式而非「未实现盈亏」形式:入场费在
        # reserve_for_entry 时已离开现金池且 release_margin 不回补 free_cash,
        # 故 `total_cash + 未实现盈亏` 在持仓期间会高估 Σ 未平仓入场费。
        equity_rows.append({
            "date": pd.Timestamp(day),
            "cash": pf.total_cash,
            "holdings": holdings_val,
            "equity": portfolio_nav(pf.free_cash, pf.settling_funds, holdings_val),
            "free_cash": pf.free_cash,
            "locked_margin": pf.locked_margin,
            "settling_funds": pf.settling_funds,
            # §3 (audit P2-10): 累计已入账现金分红(独立于逐笔 P&L 的现金流)。
            # 缺此列会被 pd.DataFrame(columns=EQUITY_COLS) 静默填成 NaN。
            "cum_dividends": dividends_cum,
        })

    trades_df = (
        pd.DataFrame(trades, columns=TRADE_COLS) if trades else _empty_trades()
    )
    equity_df = pd.DataFrame(equity_rows, columns=EQUITY_COLS)
    logger.info("simulate_portfolio: %d 笔交易", len(trades_df))
    return trades_df, equity_df
