"""收盘后真值信号作业 (spec §3.2): 跑引擎, 读旁路日志, 落 signals.jsonl。

**零重实现 (§6)。** 本模块不计算任何指标、不拼面板、不判定任何入场条件。
`short_reversal/indicators_bt.py` 的 8 个指标类各自编码了 v81 §3 的价格域决策
与 NaN 策略 (Am60 只累积非 NaN、BelowMa60Ratio60 无有效 pair 时返回 0.0、
Ma20SlopeN 用 polyfit 回归斜率、PctChg/ReturnN 各带 prev==0 守卫), 在 pandas
里重写它们等于把它们复制一份。因此本作业的唯一计算入口是
`short_reversal.engine.run_backtest_v3`, 判定结果从 Task 3 建立的只读旁路日志
(`signal_log`) 中读出。

§1 = as-of 的落地方式
--------------------
`run_backtest_v3` 的面板窗口恒为 `[start-180d, end+60d]`
(`_panel_loader.py:89-93`), 所以直接传 `end=signal_date` 会加载 signal_date
**之后 60 天**的行。本作业传 `end = panel_end_for_as_of(signal_date)`
(= `signal_date - PANEL_POST_BUFFER_DAYS`), 面板末端因此恰好落在 signal_date
上, 引擎看不到 as-of 之后的任何一行。**必须**用常量表达 —— 硬编码 60 会在常量
一旦变更时静默把未来数据放回来。

`universe_as_of=signal_date` 同样不可省 (见 `run_backtest_v3` 的 docstring):
缺省时 universe 会解析在 `panel_start = signal_date - 400d` 上, 实测静默排除
36 只 (1.13%) **最近上市**的票 —— 那是面板算术的副作用, 不是策略规则。

记录语义
--------
- 一条 `SignalRecord` 对应 (signal_date, preset[, leg]) 的一组候选。
  非 ensemble preset: `leg == preset`, `signal_id = "{signal_date}|{preset}"`。
  ensemble preset: **每条腿各写一条** (`leg` = 腿名,
  `signal_id = "{signal_date}|{preset}|{leg}"`), 因为 spec §3.4 的纸面账户按腿
  拆成 N 个子账户、§4.3 的账本幂等键含 `leg` —— 把多腿候选合并成一条会让资金
  分配错 n 倍。返回值为**声明顺序中第一条腿**的记录; 需要全部腿的调用方读
  `signals.jsonl` (本作业是 append-only 日志的生产者, 返回值只是便利)。
- 零候选也是合法结果, 照写一条 (`candidates == []`)。`signals.jsonl` 是追加式
  的, 「跑过但没候选」与「根本没跑」必须在日志里可区分 —— 否则又是一次 F-01
  式的静默失效。区分「塌缩到零」是 `assert_feeds_nonempty` 的职责 (它抛错)。
- `universe_size` 填 `len(load_universe_asof(...))`, **不是**当日日志里出现过的
  distinct thscode 数: 策略只为「当前未持有 且 不在 pending_entries 中」的票
  评估入场条件, breadth 门未过时更是整根 bar 全跳 (`replay_strategy_v3.py:524-532`),
  所以后者系统性低于真实 universe。
- **不**因 `adj_close` 为 NaN 剔除任何票: 引擎对这类票整体回退到 raw close
  (`replay_strategy_v3.py:334-341`), 剔除它等于换了一个 universe。
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from short_reversal._panel_loader import PANEL_POST_BUFFER_DAYS
from short_reversal.engine import run_backtest_v3
from short_reversal.presets import PRESETS, get_preset
from short_reversal.universe import load_universe_asof

logger = logging.getLogger(__name__)

SIGNALS_FILENAME = "signals.jsonl"

# 预热回看天数。与 Control Plane 的 `load_panel_for_signal(lookback_days=400)`
# 对齐: MA60 与 126 日回报需要 ~180 个交易日预热, 400 个日历日给足余量。
LOOKBACK_DAYS: int = 400

# 每只票最少 bar 数。低于此数的票由 `feed_bt.build_per_stock_feeds` 丢弃并告警
# (策略规则: 暖机不足), 与本模块无关 —— 本模块不得因暖机不足自己去缩 universe。
MIN_BARS: int = 150

# 生成信号时刻**已经检验过**的对比候选数下界的一部分: 本项目到目前为止同窗口
# 对比过的三个 ensemble (v63_ensemble / v64_ensemble_3leg / v79_ens44)。
# 它**不是** Task 8 的 `honest_n_trials()` (= 119 = RESERVED(3) + len(PRESETS)(75)
# + widest_declared_sweep(41)): 那批对比在生成这条记录时还没发生, 填 119 是对
# 未来的虚报。前者是记录字段, 后者是**报告 DSR 时**必须使用的分母, 两者
# 刻意不同。此处也**不得** import `tools/live/compare_ensembles` —— 该模块由
# Task 8 创建, 且 signals.jsonl 追加式 + signal_id 幂等, 事后不会回填。
RESERVED_AT_SIGNAL_TIME: int = 3

# task-3 的日志条目在 candidates 里落成的 schema (spec §3.2):
# 只含判定结果与短路位置, 不含逐条件中间值 (`passed` 恒为 True, 故不入库)。
_CANDIDATE_KEYS = ("thscode", "date", "preset", "failed_at")


@dataclass
class SignalRecord:
    """某日某 preset (ensemble 时为某条腿) 的真值信号。

    `generated_at` 取调用方声明的 `as_of_time` (而非墙上时钟), 因此整条记录是
    其输入的纯函数 —— 相同输入重跑产生的行逐字节相同 (§0 可复现)。CLI 应把
    运行时刻 (如 "2026-10-16T15:30:00") 作为 as_of_time 传入。
    """

    signal_id: str
    signal_date: str
    preset: str
    leg: str
    candidates: list[dict]
    universe_size: int
    engine_git_sha: str
    n_trials_at_generation: int
    generated_at: str


def panel_end_for_as_of(signal_date: str) -> str:
    """返回应传给 `run_backtest_v3(end=...)` 的值。

    `load_panel_for_backtest` 会在 end 之后再加 `PANEL_POST_BUFFER_DAYS` 天, 所以
    这里必须先减掉它, 面板末端才会恰好落在 signal_date 上。
    """
    return (
        pd.Timestamp(signal_date) - pd.Timedelta(days=PANEL_POST_BUFFER_DAYS)
    ).strftime("%Y-%m-%d")


def panel_start_for(signal_date: str) -> str:
    """返回应传给 `run_backtest_v3(start=...)` 的值 (= signal_date - LOOKBACK_DAYS)。"""
    return (
        pd.Timestamp(signal_date) - pd.Timedelta(days=LOOKBACK_DAYS)
    ).strftime("%Y-%m-%d")


def assert_feeds_nonempty(universe: list[str], usable: list[str]) -> None:
    """F-01 守卫: universe 非空而当日可用票集合为空 → 抛错, 不得静默返回「无信号」。

    `usable` 是当日旁路日志里出现过的 distinct thscode。它**低于**真实 universe
    (策略跳过已持仓、已在 pending_entries 的票, breadth 门未过时整根 bar 全跳),
    差额随当日持仓与 regime 状态浮动 —— 这无妨: 本守卫要抓的是「塌缩到 0」,
    不是精确计量 universe。空 universe 是合法输入 (合成库 / as_of 早于数据覆盖),
    此时无事可断, 直接返回。
    """
    if universe and not usable:
        raise ValueError(
            f"universe has {len(universe)} symbols but the engine evaluated 0 of "
            f"them on this date — the feed/log collapsed to zero. That is a "
            f"data or window problem (DB not synced? signal_date not a trading "
            f"day? panel window too short for min_bars?), NOT an empty-signal "
            f"day; the two must never be conflated (§0 F-01)."
        )
    return None


def engine_git_sha() -> str:
    """`git rev-parse HEAD`; 失败时返回 "unknown" 而不抛错。

    这是诊断字段: 线上不应因为一个诊断信息而整体失败。
    """
    repo_root = Path(__file__).resolve().parents[1]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root, capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # 无 git / 非仓库
        logger.warning("git rev-parse HEAD failed (%s); engine_git_sha='unknown'", exc)
        return "unknown"
    sha = out.stdout.strip()
    return sha or "unknown"


def _decode_candidate(raw: dict) -> dict:
    """把 JSON 里的 ISO 日期还原成 `datetime.date`, 使 load_records 与
    run_signal_job 返回的对象同型 (否则同一个字段的类型取决于它是否落过盘)。

    只还原 `date`; `signal_date` 是记录级字段, 按 Interfaces 定义为 `str`。
    """
    obj = dict(raw)
    d = obj.get("date")
    if isinstance(d, str):
        obj["date"] = date.fromisoformat(d)
    return obj


def load_records(path: Path) -> list[SignalRecord]:
    """按文件顺序读回 `signals.jsonl`; 文件不存在返回 `[]`。"""
    path = Path(path)
    if not path.exists():
        return []
    records: list[SignalRecord] = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno} is not valid JSON: {exc}") from exc
            payload["candidates"] = [
                _decode_candidate(c) for c in payload.get("candidates", [])
            ]
            records.append(SignalRecord(**payload))
    return records


def append_record(path: Path, rec: SignalRecord) -> bool:
    """追加一条记录; `signal_id` 已存在则返回 `False` 且**不写** (幂等键)。

    **幂等的作用域: 仅对串行调用成立, 不是并发保证。** 实现是
    「先查 signal_id 是否存在 → 再 append」, 两步之间**没有锁** (典型 TOCTOU),
    所以两个并发进程 (例如手工重跑撞上 cron) 可能双双通过检查、各写一行。
    这里刻意不加锁: 本作业每交易日跑一次、串行执行, 而追加式日志里多一行重复
    记录是无害的 (消费者按 signal_id 去重), 静默**覆盖**才有害 —— 那正是本设计
    选 append-only 而非 upsert 的原因。若将来要并发调用, 需在外层加锁。

    文件名之外的覆盖 (`--force`) 不在本函数职责内 —— 追加式日志的默认语义是
    「重复即跳过」。
    """
    path = Path(path)
    if any(r.signal_id == rec.signal_id for r in load_records(path)):
        logger.info("signal_id %s already present; not appended", rec.signal_id)
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    # sort_keys + default=str: 同一记录必然产生同一行 (§0 可复现)。
    with path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(asdict(rec), ensure_ascii=False, sort_keys=True, default=str)
            + "\n"
        )
    return True


def _candidate(entry: dict) -> dict:
    return {k: entry[k] for k in _CANDIDATE_KEYS}


def _leg_plan(preset: str, cfg: dict, tags: set[str]) -> list[str]:
    """本次作业要落盘的腿列表 (非 ensemble 时就是 [preset]), 并校验日志标签。

    标签校验是 §0 fail-fast 的一部分: `Phase3V3Strategy` 的 `signal_log_tag`
    默认值是 `""`, 只有 `run_backtest_v3` 会把它自己的 `preset` 形参传进去。
    若有人直接构造策略实例并附上日志 (scan_signals.py:107 那种写法), 每条记录
    的 `preset` 都会静默变成 `""`, ensemble 分腿归因会无声地坏掉 —— 这里让它
    显式炸掉。同时, 申报的腿名之外的标签也说明归属语义已破。
    """
    legs_declared = list(cfg.get("ensemble_substrategies", []))
    if not legs_declared:
        expected = {preset}
        planned = [preset]
    else:
        # v64_ensemble_3leg 把 v50_slope 申报了两次; 日志只有腿名字段, 同名腿
        # 无法区分, 故去重 (保留首次出现顺序) —— 这是 Task 3 日志的信息上限。
        planned = list(dict.fromkeys(legs_declared))
        expected = set(planned)

    unexpected = sorted(tags - expected)
    if unexpected:
        raise ValueError(
            f"signal log tagged {unexpected} on this date, but preset "
            f"{preset!r} can only be attributed to {sorted(expected)} — the "
            f"signal_log_tag contract is broken (a tag of '' means the strategy "
            f"was constructed directly instead of via run_backtest_v3)."
        )
    return planned


def _resolve_universe(cfg: dict, signal_date: str, db_path: Path) -> list[str]:
    """`load_universe_asof(preset 的 universe, signal_date, db)`, 空则 fail-fast。

    空 universe 对 `assert_feeds_nonempty` 是合法输入 (合成库场景), 但对**线上
    作业**它一定是数据问题: `raw_kline_daily` 的 min(date) 是 2016-10-10,
    早于它的 as-of 会返回空 universe, 而空 universe 会让整个作业静默产出零候选。
    """
    mode = cfg["universe"]
    universe = load_universe_asof(mode, signal_date, db_path)
    if not universe:
        raise ValueError(
            f"universe {mode!r} resolved EMPTY as-of {signal_date} from {db_path} "
            f"— the DB is missing coverage for this date (or is not synced). "
            f"Refusing to emit a silently empty signal set (§0)."
        )
    return universe


def run_signal_job(
    *,
    preset: str,
    signal_date: str,
    db_path: Path,
    state_dir: Path,
    as_of_time: str,
) -> SignalRecord:
    """跑 `preset` 在 `signal_date` 收盘后的真值信号, 写 `signals.jsonl`。

    永不返回 `None`: 零候选也写一条记录 (见模块 docstring 的「记录语义」)。

    参数:
      preset: PRESETS 里的名字, 可为 ensemble。
      signal_date: 交易日 (YYYY-MM-DD)。本作业**不**判交易日历 —— 由调用方保证。
      db_path: DuckDB 路径 (DB sync 必须已完成; 数据里没有这一天时本函数抛错)。
      state_dir: 状态目录, 由调用方给 (spec §4.1: 绝不放仓库内)。记录落
                 `state_dir / "signals.jsonl"`。
      as_of_time: 调用方声明的 as-of 时刻 (如 "2026-10-16" 或
                 "2026-10-16T15:30:00")。它既作为 `generated_at` 落盘, 也用于
                 §1 下限校验: as-of 早于 signal_date 意味着本作业会读到 as-of
                 之后的行, 直接抛错。

    返回: 声明顺序中第一条腿的 `SignalRecord` (非 ensemble 时即该 preset 的唯一
          一条); ensemble 的其余腿已写入 `signals.jsonl`, 用 `load_records` 读回。
    """
    db_path = Path(db_path)
    state_dir = Path(state_dir)

    if as_of_time[:10] < signal_date:
        raise ValueError(
            f"as_of_time={as_of_time!r} precedes signal_date={signal_date!r}: the "
            f"engine would have to read rows after the as-of (§1)."
        )

    cfg = get_preset(preset)  # 未知名抛 ValueError
    universe = _resolve_universe(cfg, signal_date, db_path)

    log: list[dict] = []
    run_backtest_v3(
        preset,
        panel_start_for(signal_date),
        panel_end_for_as_of(signal_date),
        db_path,
        min_bars=MIN_BARS,
        signal_log=log,
        universe_as_of=signal_date,
    )

    as_of = date.fromisoformat(signal_date)
    on_date = [e for e in log if e["date"] == as_of]
    usable = sorted({e["thscode"] for e in on_date})
    assert_feeds_nonempty(universe, usable)

    passed = [e for e in on_date if e["passed"]]
    by_leg: dict[str, list[dict]] = {}
    for entry in passed:
        by_leg.setdefault(entry["preset"], []).append(_candidate(entry))
    legs = _leg_plan(preset, cfg, {e["preset"] for e in on_date})

    sha = engine_git_sha()
    n_trials = len(PRESETS) + RESERVED_AT_SIGNAL_TIME
    journal = state_dir / SIGNALS_FILENAME

    records: list[SignalRecord] = []
    for leg in legs:
        # 非 ensemble: leg == preset, 规范编码 "{signal_date}|{preset}"。
        # ensemble 分腿: "{signal_date}|{preset}|{leg}" (spec §3.2 / §4.3)。
        signal_id = (
            f"{signal_date}|{preset}" if leg == preset
            else f"{signal_date}|{preset}|{leg}"
        )
        records.append(
            SignalRecord(
                signal_id=signal_id,
                signal_date=signal_date,
                preset=preset,
                leg=leg,
                candidates=by_leg.get(leg, []),
                universe_size=len(universe),
                engine_git_sha=sha,
                n_trials_at_generation=n_trials,
                generated_at=as_of_time,
            )
        )

    for rec in records:
        append_record(journal, rec)
    logger.info(
        "signal job %s: wrote %d record(s) for %s (legs=%s) to %s",
        preset, len(records), signal_date, [r.leg for r in records], journal,
    )
    return records[0]
