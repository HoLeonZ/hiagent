"""作业队列：异步、单 worker、**可取消**、失败可见、且记账发生在**提交**时。

关于测试缝：子进程是 `spawn` 出来的**全新解释器**，父进程里的 monkeypatch 不会传播过去。
所以"取消/排队"这类路径用一个能被**子进程**读到的环境变量（`HIAGENT_JOBS_FAKE_SLEEP`）
让子进程只睡一会儿——它会在服务端日志里打印警告，生产环境不该设它。
真实回测路径由最后一条测试（若 DB 在）覆盖。
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from web import jobs as jobs_mod
from web.trials import count_trials, distinct_manual_configs

from hiagent_config import get_db_path

REAL_DB = get_db_path()
SKIP_REASON = "需要 DNA_STRAT_DB 或 hiagent_config.DEFAULT_DB_PATH"


def _db() -> Path | None:
    env = os.environ.get("DNA_STRAT_DB")
    if env and Path(env).exists():
        return Path(env)
    return REAL_DB if REAL_DB.exists() else None


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setenv("HIAGENT_PLATFORM_HOME", str(tmp_path))
    jobs_mod._JOBS.clear()
    return tmp_path


@pytest.fixture
def fast_child(monkeypatch):
    """让子进程只睡 3 秒，从而能测取消/排队而不跑真实回测。"""
    monkeypatch.setenv("HIAGENT_JOBS_FAKE_SLEEP", "3")


def test_submit_returns_immediately_with_a_run_id(home, fast_child):
    """submit 必须立刻返回，不能等回测跑完——回测是分钟级的。"""
    t0 = time.monotonic()
    run_id = jobs_mod.submit("short_reversal", "v50_slope", None,
                             "2024-01-01", "2025-01-01", "full")
    elapsed = time.monotonic() - t0
    assert elapsed < 0.5, f"submit 阻塞了 {elapsed:.2f}s"
    assert jobs_mod.get(run_id).status in {"queued", "running"}
    assert jobs_mod.wait(run_id, timeout=60).status == "done"


def test_a_trial_is_recorded_at_submit_time(home, fast_child):
    """记账发生在提交时：即使随后失败或被取消，那次迭代也已经发生了（§5）。"""
    rid = jobs_mod.submit("short_reversal", "v50_slope", {"tp_pct": 0.09},
                          "2024-01-01", "2025-01-01", "full")
    assert jobs_mod.get(rid).trial_no == 1
    jobs_mod.wait(rid, timeout=60)
    assert count_trials("short_reversal", "v50_slope") == 1
    assert distinct_manual_configs("short_reversal", "v50_slope") == 1


def test_cancelling_a_running_job_actually_stops_it(home, fast_child, monkeypatch):
    """运行中的作业被取消后，**子进程必须真的死掉**。

    这是"为什么要用子进程"的验收点：线程版做不到这一点——"取消"会退化成
    "等它跑完再丢结果"，CPU 照样烧完、后面的作业照样等。

    ⚠️ **不要用 status 判断"停没停"**：`cancel()` 是**先**把 `job.status` 置成
    `cancelled`、**再** `terminate()`。所以"status 不再是 running"这句话在
    `cancel()` 返回的瞬间就为真，**与子进程死没死无关**——用 status 写的等待循环
    **一次都不会转**，测试会在"子进程还在烧 CPU"的情况下全绿。
    **判据必须落在进程对象上**（`job.proc.is_alive()`）。
    """
    monkeypatch.setenv("HIAGENT_JOBS_FAKE_SLEEP", "8")   # 够长，未终止时必被察觉
    rid = jobs_mod.submit("short_reversal", "v50_slope", None,
                          "2024-01-01", "2025-01-01", "full")
    # 等它真的开跑，并拿到子进程对象
    deadline = time.monotonic() + 30
    while jobs_mod.get(rid).status != "running" and time.monotonic() < deadline:
        time.sleep(0.05)
    job = jobs_mod.get(rid)
    assert job.status == "running", "作业没能在 30 秒内开跑"
    assert job.proc is not None and job.proc.is_alive(), "running 的作业必须有一个活着的子进程"

    # 把**那个**进程对象握在手里：worker 收尾时会把 `job.proc` 置回 `None`，
    # 而 cancel() 之后 worker 往往在同一瞬间收尾——直接读字段会撞上竞态
    # （实测 12 次里 5 次 `AttributeError: 'NoneType' object has no attribute 'is_alive'`）。
    # 判据仍是 `proc.is_alive()`（进程对象），不是 status、也不是字段现值。
    proc = job.proc
    t0 = time.monotonic()
    assert jobs_mod.cancel(rid) == "cancelled"
    elapsed = time.monotonic() - t0

    # ① 真正的判据：进程对象已经死了（不是"status 变了"）
    assert not proc.is_alive(), "cancel 之后子进程仍然活着——terminate 没生效（或只改了状态）"
    # ② 时间判据：cancel() 内部会 join(timeout=10)，若 terminate 无效就会**等满 8 秒**
    #    （子进程自然跑完）。故这条判别力**由 cancel 里的 join 承载**，不是由 status 承载。
    assert elapsed < 6, f"取消耗时 {elapsed:.1f}s——子进程没有被真正终止"
    assert jobs_mod.get(rid).status == "cancelled"
    assert jobs_mod.get(rid).result is None, "被取消的作业不应留下结果"


def test_cancelling_a_queued_job_never_starts_it(home, fast_child):
    """排队中被取消的作业不该启动子进程（省掉一次 5–8 分钟的浪费）。

    **判据是 `proc is None`**，不是"status 是 cancelled"——后者在排队阶段取消也会为真，
    却完全可以在"已经 spawn 了一个子进程再杀掉"的实现下发生。要断言的是
    **它从来没有被启动过**。
    """
    first = jobs_mod.submit("short_reversal", "v50_slope", None,
                            "2024-01-01", "2025-01-01", "full")
    second = jobs_mod.submit("short_reversal", "v44_ratio02_buf07", None,
                             "2024-01-01", "2025-01-01", "full")
    assert jobs_mod.cancel(second) == "cancelled"
    jobs_mod.wait(first, timeout=60)
    time.sleep(1)
    assert jobs_mod.get(second).status == "cancelled"
    assert jobs_mod.get(second).result is None
    assert jobs_mod.get(second).proc is None, "排队中取消的作业仍被启动了子进程——白烧一次 5–8 分钟"


def test_queue_position_is_visible(home, fast_child):
    """单 worker 下"前面还有几个"是用户唯一能看到排队依据的东西。"""
    first = jobs_mod.submit("short_reversal", "v50_slope", None,
                            "2024-01-01", "2025-01-01", "full")
    second = jobs_mod.submit("short_reversal", "v44_ratio02_buf07", None,
                             "2024-01-01", "2025-01-01", "full")
    deadline = time.monotonic() + 30
    while jobs_mod.get(first).status != "running" and time.monotonic() < deadline:
        time.sleep(0.05)
    assert jobs_mod.queue_position(second) == 1, "第二个作业前面应还有 1 个"
    jobs_mod.wait(first, timeout=60)
    jobs_mod.wait(second, timeout=60)


def test_cancel_is_idempotent(home, fast_child):
    rid = jobs_mod.submit("short_reversal", "v50_slope", None,
                          "2024-01-01", "2025-01-01", "full")
    jobs_mod.wait(rid, timeout=60)
    assert jobs_mod.cancel(rid) == "done", "已结束的作业取消应原样返回状态，不报错"


def test_unknown_run_cancel_raises_keyerror(home):
    with pytest.raises(KeyError):
        jobs_mod.cancel("deadbeef")


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_a_real_preview_run_completes_in_a_subprocess(home):
    """不经测试缝、真跑一次 preview，确认子进程路径端到端可用。"""
    os.environ.pop("HIAGENT_JOBS_FAKE_SLEEP", None)
    rid = jobs_mod.submit("short_reversal", "v50_slope", None,
                          "2025-01-01", "2026-09-12", "preview")
    got = jobs_mod.wait(rid, timeout=900)
    assert got.status == "done", got.error
    assert got.mode == "preview"
    assert isinstance(got.result.trades, list)
