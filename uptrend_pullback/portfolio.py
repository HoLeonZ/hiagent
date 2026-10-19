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
    validate_price_source,
    volume_cap_fill,
)
from core.trade_schema import TRADE_COLS

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

# 防穿仓 (R8, 2026-09-21): Volume Participation Limit (CLAUDE.md §4)。
# 单笔最大成交量 = Bar_Volume × MAX_VOL_PARTICIPATION。超出部分丢弃(不挂单)。
MAX_VOL_PARTICIPATION = 0.10

# 防穿仓 (R1, 2026-09-21): NAV-floor cash gate 阈值。
# Round 14 (2026-09-28, CLAUDE.md §2): 从 module-level 常量改为 simulate_portfolio
# 参数 (默认 0.05), preset 可通过 `nav_gate_ratio` key 覆盖。
# ⚠️ §13.63: 本族默认 **0.05**; short_reversal 的同类参数 (`min_cash_ratio`) 默认
# **None**(故意的 fail-fast 哨兵)。一致的是**闸门语义**, 不是默认值 —— 旧注释
# "与 replay_strategy_v3.py:64 (min_cash_ratio=0.05) 口径一致" 的行号与值都已不存在。

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
        }
        if has_raw:
            entry["raw_open"] = sub["raw_open"].to_numpy(dtype=float) if "raw_open" in sub.columns else np.full(len(sub), np.nan)
            entry["raw_high"] = sub["raw_high"].to_numpy(dtype=float) if "raw_high" in sub.columns else np.full(len(sub), np.nan)
            entry["raw_low"] = sub["raw_low"].to_numpy(dtype=float) if "raw_low" in sub.columns else np.full(len(sub), np.nan)
            entry["raw_close"] = sub["raw_close"].to_numpy(dtype=float) if "raw_close" in sub.columns else np.full(len(sub), np.nan)
            entry["raw_prev_close"] = sub["raw_prev_close"].to_numpy(dtype=float) if "raw_prev_close" in sub.columns else np.full(len(sub), np.nan)
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
        return _empty_trades(), pd.DataFrame(columns=["date", "cash", "holdings", "equity"])

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
        slip = effective_slippage(
            slippage, atr_by_bar.get((cal[t], code)), part, atr_slip_scale
        )
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
            tp_p, sl_p = pos["tp"], pos["sl"]
            # V8 (2026-09-22, CLAUDE.md §4): 验证 intraday_tiebreak 声明。
            if intraday_tiebreak != "sl_first":
                raise ValueError(
                    f"intraday_tiebreak must be 'sl_first' (CLAUDE.md §4), "
                    f"got {intraday_tiebreak!r}"
                )

            # ----- §4/§13.106 (2026-10-19): 跌停**封板**时卖单无法成交 -----
            # §4 明文: "Limit-Up / Limit-Down No-Fill: ... a **sell/cover on a
            # limit-down-sealed bar MUST be rejected (no fill)**"。
            # ⚠️ 本族此前**只有买入侧的 `is_limit_up`**, 完全没有卖出侧 ——
            #    而 §4 那句话的另一半正是卖出侧。
            # **"封板"的无歧义判据**: 本 bar 的 o/h/lo **三者相等** (单一价 ⇒ 全天没有
            # 成交区间) 且该价在跌停之下 ⇒ 物理上卖不出去, 不是"价格不好"。
            # ⚠️ **只守这一种**。「开盘跌停、但盘中成交过」**不在其中** —— 那种该不该拒单
            #    是一个**建模选择** (拒单可能因随后的反弹而变好), **方向不单一** ⇒
            #    已登记、未改 (§13.106(d))。
            # ⚠️ 一律用 **raw** 价判 (§3: 涨跌停是**未复权**世界的制度约束)。
            # ⚠️⚠️ 2026-10-19 (§13.121): 这段守卫**第一版无条件读 `pi["raw_open"]`**
            # ⇒ 面板**没有 raw 列**时 (合成测试面板 / legacy panel) 直接 `KeyError`
            # —— 而本文件其它 raw 访问**全都**先判成员存在 (见 `raw_close" in pi`)。
            # **它是我引入的一个回归**, 由全量回归的分拣抓到;
            # 受害者是 `tests/test_uptrend_pullback_equity_curve_integrity.py` 的两条
            # (**本该**是 §13.114 那个缺陷的守卫, 却因为这一行**根本没跑起来**)。
            _raw_ok = all(k in pi for k in ("raw_open", "raw_high", "raw_low", "raw_prev_close"))
            if _raw_ok:
                _r_o, _r_h, _r_lo = pi["raw_open"][j], pi["raw_high"][j], pi["raw_low"][j]
                _r_pc = pi["raw_prev_close"][j]
                if (
                    not np.isnan(_r_o) and not np.isnan(_r_h) and not np.isnan(_r_lo)
                    and not np.isnan(_r_pc) and _r_pc > 0
                    and _r_o == _r_h == _r_lo
                    and is_limit_down(float(_r_pc), float(_r_o))
                ):
                    continue  # 封死跌停 ⇒ 本 bar 不成交, 持仓顺延到下一根

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
                    j = _row_at(pidx[code], day)
                    px = pidx[code]["close"][j] if j is not None else pos["entry_price"]
                    holdings_val_for_gate += pos["size"] * px
                nav_now = pf.total_cash + holdings_val_for_gate
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
                    # 涨停开盘视为无法买入
                    if not np.isnan(pc) and pc > 0 and (o / pc - 1) >= LIMIT_UP_THRESHOLD:
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
                    if not np.isnan(bar_vol) and bar_vol > 0:
                        max_fill = volume_cap_fill(
                            float(bar_vol), max_volume_participation, lot_size=100
                        )
                        if max_fill > 0 and size > max_fill:
                            size = max_fill
                    # R5 (2026-09-21): ATR-aware slippage (CLAUDE.md §4)。
                    # participation = size_pre_cap / bar_vol, slip = atr × part × scale。
                    # §13.96: 入场腿改走**规范助手** + **全 bar** ATR 表。
                    # ⚠️ 上一版用 `atr_lookup`(信号日表)—— 而本族 4/4 个 preset 的
                    # `use_atr` 都是 false ⇒ 那张表**恒空** ⇒ 滑点即便设成非零也**恒为 0**
                    # 且不报错 (§0 silent bypass; §13.95 查明的根因)。
                    if atr_slip_scale > 0:
                        atr_slip_lookup = atr_by_bar.get((cal[t - 1], code))
                        participation = (
                            min(1.0, size_pre_cap / bar_vol)
                            if (not np.isnan(bar_vol) and bar_vol > 0)
                            else 0.0
                        )
                        entry_px = float(o) * (
                            1
                            + effective_slippage(
                                slippage, atr_slip_lookup, participation, atr_slip_scale
                            )
                        )
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
                        "tp": entry_px * (1 + tp_eff),
                        "sl": entry_px * (1 - sl_eff),
                        "bars": 0,
                        "atr_pct": atr_used,
                    }

        # ---------- 3) 末日强制平仓 ----------
        if t == last_t:
            for code in list(positions.keys()):
                pos = positions[code]
                pi = pidx[code]
                j = _row_at(pi, day)
                px = float(pi["close"][j]) if j is not None else pos["entry_price"]
                pos["bars"] = t - pos["entry_t"]
                # §13.96: 末日强平**也是**一笔卖出 execution ⇒ 同样计冲击。
                _close_position(
                    code, pos, _exit_fill_px(px, code, pos["size"], day, t, j, pi), day, "eod"
                )
                del positions[code]

        # ---------- 4) 记录净值 ----------
        holdings_val = 0.0
        unrealized = 0.0
        for code, pos in positions.items():
            j = _row_at(pidx[code], day)
            # ⚠️⚠️ §3/§13.114 (2026-10-19): **市值必须用 raw 价** —— 与 entry_price 同价源。
            # §3 明文: "ALWAYS use **Raw Prices** (`raw_close`) for evaluating limit order
            # triggers, stop-losses, and **portfolio physical cash mark-to-market**"。
            # 旧写法用 `pidx[code]["close"]`(前复权 adj) 去减 `pos["entry_price"]`(**raw**)
            # ⇒ **两个价源相减**。持仓跨除权日时 adj 价按复权因子**阶梯跳变**而 raw 价不动
            # ⇒ 权益曲线出现**物理上不可能**的单日跳变 (实测 uptrend 最高 **+252.78%**,
            # 14/244 天超 ±10%; chase 最高 +103%, **48/244** 天)。
            # ⇒ 回退顺序与执行价一致: raw 优先, 缺失 (NaN) 时回退 adj。
            px = pos["entry_price"]
            if j is not None:
                _rc = pidx[code].get("raw_close")
                if _rc is not None and not np.isnan(_rc[j]):
                    px = float(_rc[j])
                else:
                    px = pidx[code]["close"][j]
            holdings_val += pos["size"] * px
            # total_cash 是「已实现盈亏账本」, 建仓时并不扣减现金 (只有平仓时把
            # net_pnl 计入)。因此持仓期内 NAV 只能加**未实现盈亏**; 若加持仓市值
            # (size × px), 建仓名义金额就被计入两次 —— equity 会在建仓那根 bar 凭空
            # 跳增约一个名义金额、平仓时再跳回, 单日权益收益出现 ±50%~+110% 这种
            # 物理上不可能的跳变 (长仓 + max_positions=1 + A 股 ±10% 涨跌停 ⇒ 单日
            # 对权益影响上限约 ±10%)。compute_metrics 的 sharpe/max_dd/exposure 全部
            # 由这条曲线算出, 于是 §5 依赖的 DSR 输入不可信。
            unrealized += (px - pos["entry_price"]) * pos["size"]
        # Round 16 (CLAUDE.md §2): equity row uses total_cash.
        equity_rows.append({
            "date": pd.Timestamp(day),
            "cash": pf.total_cash,
            "holdings": holdings_val,
            "equity": pf.total_cash + unrealized,
        })

    trades_df = (
        pd.DataFrame(trades, columns=TRADE_COLS) if trades else _empty_trades()
    )
    equity_df = pd.DataFrame(equity_rows, columns=["date", "cash", "holdings", "equity"])
    logger.info("simulate_portfolio: %d 笔交易", len(trades_df))
    return trades_df, equity_df
