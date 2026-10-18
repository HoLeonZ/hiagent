"""trial 账本：append-only，记录每一次带参数的运行（含 preview）。

CLAUDE.md §5：任何人工迭代都递增 n_trials。本模块是这条纪律在平台里的落点。
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any

from web.state import assert_state_writable, state_home

TRIALS_FILE = "trials.jsonl"


def _path():
    assert_state_writable()          # 咽喉处的闸，别绕过（见 state.assert_state_writable）
    p = state_home() / TRIALS_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _read_all() -> list[dict[str, Any]]:
    p = _path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def append_trial(
    *,
    run_id: str,
    engine: str,
    preset: str,
    param_diff: dict[str, Any],
    start: str,
    end: str,
    mode: str,
) -> int:
    """追加一条试验记录，返回这条记录的 `trial_no`（从 1 开始，全局单调）。"""
    existing = _read_all()
    trial_no = len(existing) + 1
    rec = {
        "trial_no": trial_no,
        "run_id": run_id,
        "engine": engine,
        "preset": preset,
        "param_diff": param_diff,
        "start": start,
        "end": end,
        "mode": mode,
        "at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    with _path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    return trial_no


def count_trials(engine: str, preset: str) -> int:
    """该 (engine, preset) 的**运行条数**（审计用；不是 §5 的试验数）。"""
    return sum(1 for r in _read_all() if r["engine"] == engine and r["preset"] == preset)


def recent_runs(limit: int = 50) -> list[dict[str, Any]]:
    """最近的运行（**倒序**）。账本是 append-only，故取尾部即可。

    这是"历史/对比"面板的数据源：它记录的是**运行**（含原件复现），
    与 `distinct_manual_configs` 记的**试验数**是两个口径，别混。
    """
    return list(reversed(_read_all()))[:limit]


def distinct_manual_configs(engine: str, preset: str) -> int:
    """该 (engine, preset) 上**真正试过的不同配置**数——这才是 §5 的 n_trials 增量。

    §5 管的是"试过多少**配置**"，不是"点了多少次运行"：
      - **不带覆盖**的运行 = 复现一个已声明的 preset，**不计**（那不是一次迭代）；
      - 同一组覆盖跑两次 = 同一个配置，**只计一次**；
      - 覆盖内容不同 = 不同配置，各计一次。

    用运行次数当试验数会让账本虚高：在 UI 里反复点同一个"运行"不会让你多试一个配置，
    却会把 n_trials 抬上去，从而**虚增** DSR/Bonferroni 的惩罚——与 §5 的意图相反。
    §5 明令防的是**低报**；虚报同样使判据失真，故一并堵掉。
    """
    seen = set()
    for r in _read_all():
        if r["engine"] != engine or r["preset"] != preset:
            continue
        diff = r.get("param_diff") or {}
        if diff:
            seen.add(json.dumps(diff, sort_keys=True, ensure_ascii=False, default=str))
    return len(seen)
