"""trial 账本：append-only，记录每一次带参数的运行（含 preview）。

CLAUDE.md §5：任何人工迭代都递增 n_trials。本模块是这条纪律在平台里的落点。
"""
from __future__ import annotations

import datetime as dt
import threading
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
    """账本的全部记录。**坏行跳过，不让一行废掉整本账。**

    账本是 append-only 的，所以半行是**正常会发生的**：进程被杀、磁盘写满、
    机器断电，都会在文件尾留下一条不完整的 JSON。实测（2026-10-19）：
    手工追加一行撕裂记录后，`_read_all` 抛 `JSONDecodeError`，
    于是 `count_trials` / `distinct_manual_configs` / `recent_runs` **全部失效** ——
    §5 唯一的记账机制在最需要它的时候消失了。

    **一行坏数据的代价不该是"整个记账不可用"。** 跳过它、留下一句警告，
    账本其余部分照常可读：n_trials 会**少算**（偏保守方向，§5 最防的是低报……
    但这里少算的是**已经写下的**那几条，而不是新迭代；更好的做法是把解析失败的
    行数报出来，让人去修文件）。

    注意：**只跳过解析失败的行，不静默丢弃成功解析的**；也不重写文件——
    重写会破坏 append-only 语义，而且可能把用户唯一的那份证据也弄没。
    """
    p = _path()
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    bad = 0
    for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            bad += 1
            print(f"[trials] WARNING: 跳过无法解析的第 {lineno} 行"
                  f"（账本共 {len(out)} 条可读记录）", flush=True)
    return out


#: 进程级锁：只护住 `append_trial` 的"读长度 + 追加"两步（见那里的说明）。
_TRIAL_LOCK = threading.Lock()


def _pad_if_unterminated() -> None:
    """文件尾若不是换行结尾，补一个 —— 否则下一次 append 会被粘进半行里。

    append-only 的账本迟早会遇到半行（进程被杀 / 磁盘写满 / 断电）。
    只跳过坏行还不够：**坏行必须仍然是一"行"**，否则它会把下一条也吃掉。
    """
    import os

    p = _path()
    if not p.exists() or p.stat().st_size == 0:
        return
    with p.open("rb") as fh:
        fh.seek(-1, os.SEEK_END)
        if fh.read(1) != b"\n":
            with p.open("ab") as out:
                out.write(b"\n")


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
    """追加一条试验记录，返回这条记录的 `trial_no`（从 1 开始，在**单进程内**单调）。

    ⚠️ docstring 原来写的是"全局单调"，**那是假的**：原实现"先读全量长度、再追加"，
    两步之间没有锁，两个并发提交会读到同一个长度、拿到**同一个编号**。
    实测（2026-10-19，40 个线程并发 append）：只得到 **22 个不同编号**，
    其中 `1` 被用了 **9 次** —— 于是 `trial_no` 不能再标识一条记录，
    按它排序/去重的消费方（`list_runs`、`/api/compare`）全都会错。

    现在"读长度 + 追加"整个包在 `_TRIAL_LOCK` 里。

    **锁是进程级的**：本平台是单进程（uvicorn 单 worker），所以够用。
    若将来多进程部署，**这个锁等于没有** —— 必须换成文件锁（`fcntl.flock`）。
    """
    with _TRIAL_LOCK:
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
            # §0：时间戳必须是**带时区的**单一基准。naive 本地时间换台机器就漂
            # （本机与 UTC 差 8 小时），而且事后无法判断它记的是哪个时区。
            "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        }
        # ⚠️ **追加前先确认上一行以换行结尾。**
        # 若进程在写一半时被杀/磁盘写满，文件尾部会留下一条**没有换行的半行**；
        # 这时直接 `open("a")` 会把新记录**粘在**它后面 —— 两行并成一行，
        # 于是**新记录也一起废掉**（实测：`count_trials` 返回 0，而记录明明写进去了）。
        # 补一个换行，让坏行只坏它自己。
        _pad_if_unterminated()
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
      - 同一组覆盖 + **同一个窗口** 跑两次 = 同一个配置，**只计一次**；
      - 覆盖内容不同 = 不同配置，各计一次。

    用运行次数当试验数会让账本虚高：在 UI 里反复点同一个"运行"不会让你多试一个配置，
    却会把 n_trials 抬上去，从而**虚增** DSR/Bonferroni 的惩罚——与 §5 的意图相反。
    §5 明令防的是**低报**；虚报同样使判据失真，故一并堵掉。

    ⚠️ **去重键必须包含评估窗口（`start` / `end` / `mode`），不能只看 `param_diff`。**

    CLAUDE.md §5 有一句是明写的：*"Every iteration — including changes to the
    evaluation window itself — increments `n_trials`."* **换窗口本身就是一次迭代。**

    只看 `param_diff` 会**低报**（§5 最防的那个方向）：同一组覆盖扫 20 个窗口
    去找最好看的那个，账本会显示"1 次试验"。实跑复现（2026-10-19）：
    三个不同窗口 + 同一组覆盖 → 旧实现返回 **1**，§5 要求 **3**。
    那正是本节要堵的"不提记账的调参后门"。

    `mode` 同理：preview 与 full 是同覆盖、**不同窗口**（preview 把窗口缩到最近 P 天），
    设计文档 §7.2 明写 preview 也计入。
    """
    seen = set()
    for r in _read_all():
        if r["engine"] != engine or r["preset"] != preset:
            continue
        diff = r.get("param_diff") or {}
        if not diff:
            continue                      # 原件复现不是一次迭代
        seen.add(json.dumps(
            {
                "diff": diff,
                "start": r.get("start"),
                "end": r.get("end"),
                "mode": r.get("mode"),
            },
            sort_keys=True, ensure_ascii=False, default=str,
        ))
    return len(seen)
