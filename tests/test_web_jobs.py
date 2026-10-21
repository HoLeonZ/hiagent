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
    # 子进程睡 30 秒，判据的截止是 15 秒 —— **2 倍余量**。
    # 原先写的是"睡 8 秒 / 截止 6 秒"，只有 **2 秒**余量：在同时跑浏览器、服务与
    # 其它作业的机器上会**误红**（实测过一次全套跑时它单独没红）。
    # 2 倍余量照样能判别 —— 不终止的话子进程要睡满 30 秒 ≫ 15 秒的截止。
    monkeypatch.setenv("HIAGENT_JOBS_FAKE_SLEEP", "30")   # 够长，未终止时必被察觉
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
    assert elapsed < 15, f"取消耗时 {elapsed:.1f}s——子进程没有被真正终止"
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


def test_the_jobs_table_order_matches_the_queue_order_under_concurrent_submits(home, monkeypatch):
    """**`_JOBS` 的插入序必须与实际出队序一致** —— `queue_position` 就建立在它上面。

    原实现先 `_JOBS[run_id] = job`、再（隔着写 `job.json` 与起 worker）`_QUEUE.put(run_id)`，
    两个并发 `submit` 时**两者顺序可以反过来**：`_JOBS` 里 A 在前，而队列里 B 先出队。
    于是 `queue_position`（按 `_JOBS` 插入序数"前面还有几个"）会告诉用户一个**反的**位置。

    判据就是**两个序相等**。为让它可观测，这里把 worker 顶成 no-op（没人从队列取），
    等所有提交结束后自己把队列排干再比对。

    ⚠️ **这条是竞态探测器，不是确定性的证据。** 实测（把 `put` 移出临界区的变异上连跑
    6 次）：单轮 8 线程时 **5 红 1 绿**；改成一轮跑 5 轮之后 **6 红 0 绿**。所以：
      · 它绿**不能**说明代码是对的（那一轮恰好没交错）；
      · 它红则**确实**说明序反了。
    为把检出率抬上去，一轮 8 个线程不够就跑多轮 —— 但**别把它当门禁用**，
    真正的保证是结构性的（入表与入队在同一临界区），这条只是给结构加一道报警。
    """
    monkeypatch.setattr(jobs_mod, "_ensure_worker", lambda: None)
    jobs_mod._JOBS.clear()

    # ⚠️ **不要靠"排干队列"来观测顺序。**
    # 先前测试留下的 worker 线程还活着（它是 `while True: _QUEUE.get()` 的守护线程），
    # 会把本测试塞进去的元素**偷走** —— 那样单跑绿、全文件跑红（实测踩过），
    # 而红的是"测试自己被别的测试干扰"，不是被测代码。
    # 改为**记录 `put` 的调用序**：既不受别人消费影响，又正好是这条不变式的两侧之一。
    # 替身**也不再真的入队**：先前测试留下的 worker 线程还活着（守护线程 while True 取队列），
    # 真塞进去的作业会在 fixture 还原环境变量之后被它取走 —— 那时它去默认状态目录找
    # `run.log`，抛 `FileNotFoundError`（实测踩过）。本测试只关心**调用序**，不需要真的排队。
    # 判据不受影响：替身是从临界区里被调用的，若 `put` 被移出临界区，这个序仍会交错。
    put_order: list[str] = []
    monkeypatch.setattr(jobs_mod._QUEUE, "put", lambda item, *a, **k: put_order.append(item))

    import threading

    ids, errors = [], []
    lock = threading.Lock()

    def submit_one():
        try:
            rid = jobs_mod.submit("short_reversal", "v50_slope", None,
                                  "2024-01-01", "2025-01-01", "full")
            with lock:
                ids.append(rid)
        except Exception as exc:                 # noqa: BLE001
            with lock:
                errors.append(exc)

    # 跑多轮：单轮的检出率有限，多跑几轮把它抬上去
    table_order, queue_order = [], []
    for _round in range(5):
        jobs_mod._JOBS.clear()
        put_order.clear()
        ids.clear()
        threads = [threading.Thread(target=submit_one) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, f"并发提交报错：{errors[:2]}"

        table_order = list(jobs_mod._JOBS)
        queue_order = list(put_order)
        assert len(queue_order) == 8, f"入队调用应有 8 次，实际 {len(queue_order)}"
        if table_order != queue_order:
            break
    assert table_order == queue_order, (
        "`_JOBS` 插入序与实际出队序不一致 —— `queue_position` 会给出反的排队位置。\n"
        f"  表序  {table_order}\n  队序  {queue_order}"
    )


def test_the_service_refuses_to_start_with_the_test_seam_set(monkeypatch):
    """**测试缝不许出现在服务进程里** —— 设了就直接拒绝启动（§0 fail-fast）。

    设上 `HIAGENT_JOBS_FAKE_SLEEP` 后，每个作业的子进程都**跳过真实回测**、
    回一个 `{"metrics": {}, "trades": []}`：作业状态是 **`done`**，
    结果页上**指标全空、零笔成交**——看起来完全像"这个策略没找到机会"，
    而**它其实一次都没跑**。它还**在提交时就被记进了 §5 账本**。

    原实现只在**子进程**里打一句警告，而那发生在 `os.dup2` **之后**，
    所以那句话只落在**这一笔自己的 `run.log`** 里，**服务端日志一句都没有**。
    **警告打在人不会看的地方，等于没有警告。**
    """
    from web.app import create_app

    assert create_app() is not None, "没设缝时应当正常建应用"

    monkeypatch.setenv("HIAGENT_JOBS_FAKE_SLEEP", "1")
    with pytest.raises(RuntimeError, match="HIAGENT_JOBS_FAKE_SLEEP"):
        create_app()
    with pytest.raises(RuntimeError, match="HIAGENT_JOBS_FAKE_SLEEP"):
        jobs_mod.assert_no_test_seam()


def test_the_ledger_records_the_EVALUATED_window_not_the_requested_one(home, fast_child):
    """**§5 记的是实际评估的窗口**，不是用户请求的那个。

    preview 会把窗口缩到最近 N 天，于是两个不同的请求起点可能**评估同一个窗口**。
    旧实现按请求窗口去重，把它们记成 **2 次试验** —— 可它们是**同一次迭代**
    被评估了两遍，而 §5 管的是"试过多少配置"。

    反过来，用户**改**了评估窗口**确实**是一次新迭代（§5 原文：
    *"including changes to the evaluation window itself"*）——所以必须记**实际的**那个。

    用户请求的窗口没有丢：它写在该次运行的 `job.json` 里（`meta_persisted` 能读回）。
    两处语义不同，都刻意保留。
    """
    import json as _json

    from web.runners import effective_window
    from web.trials import distinct_manual_configs

    end = "2026-10-16"
    starts = ["2025-01-01", "2026-01-01"]
    rids = []
    for start in starts:
        rid = jobs_mod.submit("short_reversal", "v50_slope", {"tp_pct": 0.09},
                              start, end, "preview")
        rids.append(rid)
        jobs_mod.wait(rid, timeout=60)

    # 两个请求起点在 preview 下确实评估同一个窗口（前提，否则本测试无意义）
    a, b = (effective_window("preview", s, end) for s in starts)
    assert a == b, f"前提不成立：两个请求评估的窗口不同（{a} vs {b}），本测试不适用"

    assert distinct_manual_configs("short_reversal", "v50_slope") == 1, \
        "同一次迭代被评估两遍，不该记成两次试验"

    # 请求的窗口仍然留在各自的 job.json 里，没有丢
    from web.state import run_artifact
    for rid, start in zip(rids, starts):
        meta = _json.loads(run_artifact(rid, "job.json").read_text(encoding="utf-8"))
        assert meta["start"] == start, "job.json 应保留用户请求的起点"


def test_a_dead_worker_is_detected_and_restarted(home, monkeypatch):
    """worker 是**唯一**的一条 —— 它死了没人接手。

    原实现用一个**一次性布尔** `_WORKER_STARTED`：置 True 之后再也不看线程
    **是否还活着**。worker 若死了（护栏之外的任何原因），后续作业只会一直躺在
    `_QUEUE` 里：状态永远是 `queued`，界面上只显示"已等 N 分钟"，
    **没有任何错误可见** —— 用户无从判断是该等还是该报告。

    本条装一个**确实已经结束**的线程对象，模拟"worker 死了"，要求
    `_ensure_worker()` 能发现并重启。
    """
    import threading

    # 用一个**会阻塞、且不去取队列**的替身代替真 worker：
    # 真 worker 起来会把 `_QUEUE` 里的东西取走，于是**别的测试**的作业被它偷跑
    # ——同一个坑今天已经踩过一次（顺序测试单跑绿、全文件跑红）。
    hold = threading.Event()
    monkeypatch.setattr(jobs_mod, "_worker", lambda: hold.wait(30))

    dead = threading.Thread(target=lambda: None, daemon=True)
    dead.start()
    dead.join()
    assert not dead.is_alive(), "前置：装进去的线程必须是死的"

    previous = jobs_mod._WORKER          # **还原**：否则本测试结束时全局仍指向一个
    jobs_mod._WORKER = dead             # 死线程，后续测试会误起第二个 worker
    jobs_mod._ensure_worker()            # → 两个 worker 抢同一个队列，别的测试随即变红
    try:
        assert jobs_mod._WORKER is not dead, "没检测到 worker 已死"
        assert jobs_mod._WORKER.is_alive(), "检测到了却没有重启"
    finally:
        hold.set()          # 让替代线程退出，不留后台线程
        jobs_mod._WORKER = previous   # 把全局状态还给原来的 worker


def test_the_run_log_is_not_empty_while_the_job_runs(home, fast_child):
    """**日志从一开始就要有内容** —— 界面那句承诺得兑现。

    实测（2026-10-21）：一次真实 preview 的 `run.log` 全程只有 **1 行**，
    而且是面板建完**之后**才打印的 —— 引擎在整个 5–8 分钟里**一行都不打印**。
    而界面上写着"运行日志（回测 5–8 分钟，这里能看出它在动）"：
    **那是一句空的承诺**，日志在整个回测期间是黑的。

    现在子进程在**开跑时**就写起始行（跑的是哪个引擎/预设/窗口/覆盖），
    结束时写用时。写日志的**只能是子进程自己** —— 它独占那个 fd；
    父进程若也往同一文件追加，两边的文件偏移会互相覆盖（日志会花掉）。

    中途"还在动"由**状态行的"已等 Ns"**承担（父进程写的，不碰这个 fd）。
    """
    from web.state import run_artifact

    rid = jobs_mod.submit("short_reversal", "v50_slope", {"tp_pct": 0.09},
                          "2024-01-01", "2025-01-01", "full")
    jobs_mod.wait(rid, timeout=60)
    text = run_artifact(rid, "run.log").read_text(encoding="utf-8")
    assert "[jobs] 回测开始" in text, f"起始行缺失，日志在回测期间是空的：{text!r}"
    assert "short_reversal" in text and "v50_slope" in text, "起始行要写明跑的是什么"
    assert "[jobs] 回测结束" in text and "用时" in text, "结束行要给出用时"


def test_a_cancelled_run_says_so_in_its_own_log(home, fast_child, monkeypatch):
    """**取消后日志要说明自己是被取消的。**

    实测（2026-10-21）：取消一次真运行的流程（提交 → 看日志 → 取消）全对，
    但日志里**只有起始行** —— 子进程被 kill，写不到它的结束行，
    于是日志读起来像"跑着跑着没了"。状态行会说 cancelled ✓，但日志没讲完。

    收尾行由**父进程**补，且只在子进程**已结束之后** —— 那时没有并发写入者，
    不会争文件偏移（子进程攥着那个 fd，两边同时写会把日志写花）。
    """
    from web.state import run_artifact

    monkeypatch.setenv("HIAGENT_JOBS_FAKE_SLEEP", "30")
    rid = jobs_mod.submit("short_reversal", "v50_slope", None,
                          "2024-01-01", "2025-01-01", "full")
    deadline = time.monotonic() + 30
    while jobs_mod.get(rid).status != "running" and time.monotonic() < deadline:
        time.sleep(0.02)
    assert jobs_mod.get(rid).status == "running", "作业没能在 30 秒内开跑"

    # ⚠️ 等日志**已经有起始行**再取消：`proc.start()` 之后子进程还要跑一小段
    # 才 `open(log_path)`，取消太早会连日志文件都还没建（实测踩过）。
    log = run_artifact(rid, "run.log")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if log.exists() and "[jobs] 回测开始" in log.read_text(encoding="utf-8"):
            break
        time.sleep(0.02)
    assert log.exists(), "子进程始终没有建出日志文件"

    assert jobs_mod.cancel(rid) == "cancelled"

    # ⚠️ `wait()` 在 `cancel()` 置状态时就返回了，而**收尾行是 worker 之后才写的**
    #（它要等 terminate/join 走完）—— 所以这里也要轮询，不能读一次就断言。
    deadline = time.monotonic() + 30
    text = ""
    while time.monotonic() < deadline:
        text = log.read_text(encoding="utf-8")
        if "已取消" in text:
            break
        time.sleep(0.05)

    assert "[jobs] 回测开始" in text
    assert "已取消" in text, f"取消后日志不说自己是被取消的：{text!r}"
