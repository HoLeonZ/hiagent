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


def test_running_always_implies_a_live_child_process(home, fast_child):
    """**不变量：读到 `running` ⇒ `job.proc` 一定存在且活着。**

    这是 `cancel()` 能生效的**前提**。原实现先发 `status = "running"`、
    后发 `job.proc = proc`，两次发布之间有一个窗口。实测（40 次紧轮询）：
      · **33/40** 次观察到 `running` 而 `proc is None`；
      · 排进那个窗口的 `cancel()` **静默失效、白烧一整轮 5–8 分钟的全量回测**（39/40）。
    三者在同一临界区发布后，这个不变量应当恒成立。

    **这条靠采样，天然有漏检概率**，所以：① 紧轮询（`sleep(0.001)`）提高落进窗口的机会；
    ② 断言是"任意一次采样落在窗口内即失败"；③ 它**不是**主证据——
    主证据是 `test_cancelling_a_running_job_actually_stops_it`
    （断言 `not proc.is_alive()`，不依赖采样）。
    """
    rid = jobs_mod.submit("short_reversal", "v50_slope", None,
                          "2024-01-01", "2025-01-01", "full")
    seen_running = 0
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        j = jobs_mod.get(rid)
        if j.status == "running":
            seen_running += 1
            assert j.proc is not None, \
                "看到 running 却没有子进程 —— 正是 cancel() 会静默失效的那个窗口"
            assert j.proc.is_alive(), "running 的作业必须有一个活着的子进程"
        if j.status in {"done", "failed", "cancelled"}:
            break
        time.sleep(0.001)
    assert seen_running > 0, "一次都没采到 running —— 这条测试没有真正执行过它的断言"
    jobs_mod.wait(rid, timeout=60)


def test_wait_returns_on_a_cancelled_job_instead_of_timing_out(home, fast_child):
    """`wait()` 的终止集合必须包含 `cancelled`。

    原实现是 `{"done", "failed"}`，于是对**已被取消**的作业调 `wait()`
    会一直空转到 timeout、再抛 `TimeoutError` —— 与它自己那句
    "阻塞到作业结束"的 docstring 直接矛盾。（实测复现过。）
    """
    first = jobs_mod.submit("short_reversal", "v50_slope", None,
                            "2024-01-01", "2025-01-01", "full")
    second = jobs_mod.submit("short_reversal", "v44_ratio02_buf07", None,
                             "2024-01-01", "2025-01-01", "full")
    assert jobs_mod.cancel(second) == "cancelled"
    got = jobs_mod.wait(second, timeout=10)        # 必须**返回**，不是抛 TimeoutError
    assert got.status == "cancelled"
    jobs_mod.wait(first, timeout=60)


def test_one_broken_job_does_not_kill_the_worker(home, fast_child, monkeypatch):
    """**worker 是唯一的一条命。**

    循环体若没有异常护栏，一次异常就让那**唯一**的 worker 线程死掉，
    此后所有作业永远停在 `queued`，且**没有任何错误可见**——用户看到的是"一直在排队"。

    注入一次故障验证：该作业变成 `failed` 且**原因可见**，而**后续作业照常完成**。
    """
    calls = {"n": 0}
    real = jobs_mod._run_one

    def boom(run_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("注入的故障")
        return real(run_id)

    monkeypatch.setattr(jobs_mod, "_run_one", boom)
    bad = jobs_mod.submit("short_reversal", "v50_slope", None,
                          "2024-01-01", "2025-01-01", "full")
    assert jobs_mod.wait(bad, timeout=60).status == "failed", "坏掉的作业必须变成 failed"
    assert "worker crashed" in (jobs_mod.get(bad).error or ""), \
        "失败原因必须可见，不能只是一句'失败了'"
    good = jobs_mod.submit("short_reversal", "v50_slope", None,
                           "2024-01-01", "2025-01-01", "full")
    assert jobs_mod.wait(good, timeout=60).status == "done", \
        "后续作业必须照常完成 —— 一次异常不能杀死唯一的 worker"


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_a_real_preview_run_completes_in_a_subprocess(home):
    """不经测试缝、真跑一次 preview，确认子进程路径端到端可用。

    ⚠️ **`end` 必须取库内最后一个交易日** —— 也就是 UI 的默认语义。
    原版写死 `end="2026-09-12"`（比今天早约一个月），于是引擎的 `+60d` 后置窗口
    里**恰好有数据**，面板凑到 200 根 bar —— **正好等于 min_bars，零余量**，
    于是这条测试通过，而 **UI 默认路径（`end`=今天）实际只有 178 根、必然失败**。
    测试与真实用法的输入差一个月，就把一个"preview 完全不可用"的缺陷放过去了。
    """
    import duckdb

    from hiagent_config import get_db_path

    os.environ.pop("HIAGENT_JOBS_FAKE_SLEEP", None)
    con = duckdb.connect(str(get_db_path()), read_only=True)
    try:
        last = con.execute("SELECT max(date) FROM v_daily_hfq").fetchone()[0]
    finally:
        con.close()
    rid = jobs_mod.submit("short_reversal", "v50_slope", None,
                          "2025-01-01", last.isoformat(), "preview")
    got = jobs_mod.wait(rid, timeout=900)
    assert got.status == "done", got.error
    assert got.mode == "preview"
    assert isinstance(got.result.trades, list)


def test_a_timeout_terminates_the_child_instead_of_leaving_an_orphan(home, fast_child, monkeypatch):
    """**超时之后必须真的把子进程杀掉。**

    原实现只是 `join(timeout=5)` 然后放弃：
    一次 5–8 分钟的全量回测在"作业已判 failed"之后**继续满跑 CPU**，
    而 `job.proc` 随后被置 `None` —— **`cancel()` 再也够不到它**。
    用户看到"作业失败了"，机器上却还有一个进程在烧。

    判据落在**进程对象**上（不是 status）：超时后 `is_alive()` 必须为假。
    """
    import subprocess

    monkeypatch.setattr(jobs_mod, "JOB_TIMEOUT_SECONDS", 2)
    monkeypatch.setenv("HIAGENT_JOBS_FAKE_SLEEP", "120")   # 子进程睡很久，必然超时

    rid = jobs_mod.submit("short_reversal", "v50_slope", None,
                          "2024-01-01", "2025-01-01", "full")

    # 抓下子进程的 pid（它稍后会被置 None）
    pid = None
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        j = jobs_mod.get(rid)
        if j.proc is not None and j.proc.is_alive():
            pid = j.proc.pid
            break
        if j.status in {"done", "failed", "cancelled"}:
            break
        time.sleep(0.02)
    assert pid is not None, "没抓到子进程 pid —— 这条测试没有真正执行过它的判据"

    got = jobs_mod.wait(rid, timeout=60)
    assert got.status == "failed", f"超时应当判 failed，实际 {got.status}"
    assert "timeout" in (got.error or ""), f"失败原因应说明是超时：{got.error!r}"

    # **关键**：给它一点时间收尸，然后确认那个 pid 真的没了
    time.sleep(1.0)
    alive = subprocess.run(["ps", "-p", str(pid)], capture_output=True).returncode == 0
    assert not alive, (
        f"超时后子进程 {pid} 还活着 —— 它会在无人能取消的情况下继续烧 CPU"
        "（`job.proc` 已被置 None，`cancel()` 够不到它）"
    )
