"""单 worker 异步作业队列 + **可取消**。

为什么每个作业跑在**独立子进程**里（而不是线程）——三条理由，第一条是硬需求：

1. **取消必须真的生效。** 回测是 5–8 分钟的 CPU 密集任务，而 Python 线程无法被安全中止。
   用线程的话，"取消"只能退化成"标记一下、等它跑完再丢弃结果"——CPU 照样烧完、
   排在后面的作业照样等。**这恰恰是用户最痛的地方**（选错预设 → 白等 8 分钟且堵住队列）。
   子进程可以 `terminate()`，取消才有意义。
2. **崩溃隔离。** 引擎的一次异常/段错误不该带走整个服务进程
   （cycle_price_action 在含停牌缺口的窗口上就会抛 `RuntimeError`，将来可能遇到更糟的）。
3. 绕开 GIL。当前仍**刻意只跑一个**作业（CPU 密集，串行反而更快），这一条是为将来留余地。

`RunResult` 经 JSON 往返后送回，因此 `metrics`/`trades` 一定是可序列化的
（API 本来也要 JSON 化；`NaN` 在 Python 的 json 里可往返，由 Task 6 的 `_is_nan` 收尾）。
"""
from __future__ import annotations

import json
import multiprocessing as mp
import queue
import threading
import uuid
from dataclasses import dataclass
from typing import Any

from web.runners import RunResult
from web.state import run_artifact, run_dir, state_home
from web.trials import append_trial, recent_runs

#: 单个作业的墙钟上限（防呆）。正常全量回测 5–8 分钟，30 分钟已是异常。
JOB_TIMEOUT_SECONDS = 30 * 60

#: run_id → Job
_JOBS: dict[str, "Job"] = {}
_QUEUE: "queue.Queue[str]" = queue.Queue()
_LOCK = threading.Lock()
_WORKER_STARTED = False


@dataclass
class Job:
    run_id: str
    engine: str
    preset: str
    overrides: dict[str, Any]
    start: str
    end: str
    mode: str
    status: str = "queued"          # queued | running | done | failed | cancelled
    error: str | None = None
    result: RunResult | None = None
    trial_no: int | None = None
    proc: Any = None                # 运行中才有；取消时 terminate 它


#: **仅供测试**：子进程是 `spawn` 出来的全新解释器，父进程里的 monkeypatch 不会生效，
#: 所以取消/排队这些路径需要一个能被**子进程**读到的开关。设了它就跳过真实回测。
#: 生产环境不该设它；设了会在服务端日志里**响亮**打印一行（见下）。
_CHILD_FAKE_SLEEP_ENV = "HIAGENT_JOBS_FAKE_SLEEP"


def _child_entry(conn, engine, preset, overrides, start, end, mode, log_path) -> None:
    """子进程入口：跑回测，把 JSON 安全的结果经管道送回。

    **stdout/stderr 全部落到 `log_path`**：回测要 5–8 分钟，界面若在这段时间里全黑，
    用户无法区分"在跑"与"卡死"；失败时也只有一行 error，看不到引擎自己说了什么。
    用 `os.dup2` 而不是 `sys.stdout = …`——引擎的 print 可能来自 C 层或子库，`dup2` 才盖得住。
    """
    import os
    import time

    with open(log_path, "w", buffering=1, encoding="utf-8") as _log:
        os.dup2(_log.fileno(), 1)
        os.dup2(_log.fileno(), 2)
        _child_body(conn, engine, preset, overrides, start, end, mode)


def _child_body(conn, engine, preset, overrides, start, end, mode) -> None:
    import os
    import time

    fake = os.environ.get(_CHILD_FAKE_SLEEP_ENV)
    if fake:
        print(f"[jobs] WARNING: {_CHILD_FAKE_SLEEP_ENV}={fake} — "
              f"子进程以测试模式运行，未跑真实回测", flush=True)
        time.sleep(float(fake))
        try:
            conn.send({"ok": True, "metrics": {}, "trades": [],
                       "start": start, "end": end})
        finally:
            conn.close()
        return
    try:
        from web.runners import run as _run

        r = _run(engine, preset, start, end, overrides=overrides, mode=mode)
        payload = {
            "ok": True,
            "metrics": json.loads(json.dumps(r.metrics, default=str)),
            "trades": json.loads(json.dumps(r.trades, default=str)),
            "start": r.start,
            "end": r.end,
        }
    except Exception as exc:  # noqa: BLE001 — 失败必须可见，不能吞
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    try:
        conn.send(payload)
    finally:
        conn.close()


def _worker() -> None:
    """唯一的工作线程。

    **循环体必须被异常护栏整个包住**（见 `_run_one` 的说明）——它是唯一的一条命。
    """
    while True:
        run_id = _QUEUE.get()
        try:
            _run_one(run_id)
        except Exception as exc:          # noqa: BLE001
            # **worker 是唯一的一条命。** 这个循环体里任何一次异常若逃出去，
            # 线程就死了，此后**所有**作业永远停在 queued
            #（后续 submit 只会挂进队列，没人来取），而且**没有任何错误可见** ——
            # 用户看到的是"一直在排队"，会以为是自己点得不够。
            # 所以：兜住一切，把该作业标成 failed、原因留在 `job.error`，然后继续下一个。
            job = _JOBS.get(run_id)
            if job is not None and job.status not in {"done", "cancelled"}:
                job.status = "failed"
                job.error = f"worker crashed: {type(exc).__name__}: {exc}"
            print(f"[jobs] ERROR: worker 处理 {run_id} 时抛异常: "
                  f"{type(exc).__name__}: {exc}", flush=True)
        finally:
            _QUEUE.task_done()


def _run_one(run_id: str) -> None:
    """跑一个作业。抽成独立函数，是为了让 `_worker` 的异常护栏能**完整**包住它。"""
    job = _JOBS.get(run_id)
    if job is None or job.status == "cancelled":     # 排队期间被取消
        return

    ctx = mp.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    proc = ctx.Process(
        target=_child_entry,
        args=(child_conn, job.engine, job.preset, job.overrides,
              job.start, job.end, job.mode,
              str(run_artifact(job.run_id, "run.log"))),
        daemon=True,
    )
    # **`proc.start()`、`job.proc`、`status="running"` 三件事必须在同一个临界区里发布。**
    # 分开做（先置 status、后建 proc）会让两条不变式都只剩"碰巧成立"：
    #   ① `running ⇒ 有活着的子进程`——实测紧轮询下 **40 次里 33 次**观察到
    #      `status == "running"` 而 `job.proc is None`；测试"子进程必须真的死了/真的活着"
    #      的判据正建立在这条不变式上，于是随机 AttributeError 红。
    #   ② `cancel() 看到 queued ⇒ 子进程尚未启动`——否则在"排队→运行"的缝里取消会**静默失效**：
    #      cancel 见 queued 便不 terminate，worker 随后照启子进程，白烧一次全量回测。
    with _LOCK:
        if job.status == "cancelled":            # 临界区内刚被取消：一个子进程都不许起
            parent_conn.close()
            child_conn.close()
            return
        proc.start()
        job.proc = proc
        job.status = "running"
    child_conn.close()               # 父进程不持有子进程那一端（否则 poll 永远等不到 EOF）

    timed_out = False
    try:
        if parent_conn.poll(JOB_TIMEOUT_SECONDS):
            payload = parent_conn.recv()
        else:
            payload = {"ok": False,
                       "error": f"timeout: job exceeded {JOB_TIMEOUT_SECONDS}s"}
            timed_out = True
    except EOFError:
        payload = {"ok": False, "error": "child process died without sending a result"}
    finally:
        parent_conn.close()
        # ⚠️ **超时之后必须真的把它杀掉。** 原实现只是 `join(timeout=5)` 然后放弃，
        # 于是：一次 5–8 分钟的全量回测在"作业已判 failed"之后**继续烧 CPU**，
        # 而 `job.proc` 随后被置 `None` —— `cancel()` **再也够不到它**。
        # 用户看到的是"作业失败了"，而机器上还有一个进程在满跑。
        # `terminate()` 对已退出的进程是 no-op，所以这里只需在超时分支上做。
        if timed_out:
            proc.terminate()
        proc.join(timeout=5)
        if proc.is_alive():
            # terminate 无效（子进程卡在不可中断的调用里）时强杀，别留孤儿。
            proc.kill()
            proc.join(timeout=5)

    with _LOCK:
        if job.status == "cancelled":
            pass                          # 用户取消：结果丢弃（不覆盖 status）
        elif payload.get("ok"):
            job.result = RunResult(job.engine, job.preset,
                                   payload["start"], payload["end"],
                                   payload["metrics"], payload["trades"])
            job.status = "done"
        else:
            job.status = "failed"
            job.error = payload.get("error") or "unknown error"
        job.proc = None
        # 落盘只在**真的成功**时做：被取消的作业即使子进程恰好回了 ok 也不留结果。
        should_persist = job.status == "done"

    if should_persist:
        try:
            _persist_result(job, payload)
        except OSError as exc:      # 落盘失败不该把一次成功的回测判成失败
            print(f"[jobs] WARNING: 结果落盘失败 {job.run_id}: {exc}", flush=True)


def _persist_result(job: "Job", payload: dict) -> None:
    """把结果落盘到 `runs/<id>/result.json`。

    **这是"历史"与"对比"能成立的前提**：没有它，比较两个配置就得把 5–8 分钟的回测重跑一遍。
    服务重启后内存里的 `_JOBS` 会空，但磁盘上还在——所以历史不必依赖进程存活。
    """
    import datetime as _dt

    d = run_dir(job.run_id)          # 过 §7 闸并建目录（不要自己拼路径 + mkdir）
    (d / "result.json").write_text(
        json.dumps({
            "run_id": job.run_id, "engine": job.engine, "preset": job.preset,
            "overrides": job.overrides, "start": payload["start"], "end": payload["end"],
            "mode": job.mode, "trial_no": job.trial_no,
            "metrics": payload["metrics"], "trades": payload["trades"],
            "finished_at": _dt.datetime.now().isoformat(timespec="seconds"),
        }, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def load_persisted(run_id: str) -> RunResult | None:
    """从磁盘读回一个历史 run 的结果；没有则 None。

    服务重启后 `_JOBS` 为空，但历史仍在磁盘上——**因此可以跨会话对比，而不必重跑**。
    """
    p = run_artifact(run_id, "result.json")
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    return RunResult(d["engine"], d["preset"], d["start"], d["end"],
                     d["metrics"], d["trades"])


def meta_persisted(run_id: str) -> dict[str, Any] | None:
    """磁盘上的运行元数据（`runs/<id>/job.json`）：`engine/preset/overrides/start/end/mode`。

    服务重启后 `_JOBS` 是空的，但 `job.json` 还在——**`overrides` 只在这里**，
    `result.json` 里没有（`load_persisted` 返回的 `RunResult` 也不带它）。
    """
    p = run_artifact(run_id, "job.json")
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def resolve(run_id: str) -> tuple[dict[str, Any], "RunResult"] | None:
    """把一次运行解析成 `(元数据, 结果)` —— **内存优先、磁盘兜底**。

    **结果类端点必须都走这里。** 实测（2026-10-19，起服务跑完一次 preview 后重启）：
    `GET /api/runs/{id}` 与 `/equity`、`/positions`、两处 `/export` 都能从磁盘读回，
    **而 `/trades` 与 `/trades/{i}/chart` 只查内存 `_JOBS` → 404**。
    于是历史面板里点开一次旧运行：头部说"done"，交易表与 K 线却是空的。

    那是"同一项能力在多条路径上各写一遍、其中几条漏了"的老形状
    （同 `assert_state_writable`、同 API 出口的网）。**收敛到一个入口**，
    下一个结果端点就不会又漏。

    返回 `None` 表示这个 run 既不在内存、磁盘上也没有。
    """
    job = _JOBS.get(run_id)
    if job is not None and job.result is not None:
        return ({
            "engine": job.engine, "preset": job.preset,
            "overrides": job.overrides or {},
            "start": job.start, "end": job.end, "mode": job.mode,
        }, job.result)

    meta = meta_persisted(run_id)
    result = load_persisted(run_id)
    if meta is None or result is None:
        return None
    return meta, result


def list_runs(limit: int = 50) -> list[dict[str, Any]]:
    """最近运行的摘要列表（来自 append-only 账本），带 `has_result` 与内存中的 `status`。"""
    out = []
    for r in recent_runs(limit):
        rid = r["run_id"]
        job = _JOBS.get(rid)
        out.append({
            "run_id": rid, "engine": r["engine"], "preset": r["preset"],
            "start": r["start"], "end": r["end"], "mode": r["mode"],
            "at": r.get("at"), "trial_no": r.get("trial_no"),
            "param_diff": r.get("param_diff") or {},
            "status": job.status if job else None,          # 仅本进程内可知
            "has_result": run_artifact(rid, "result.json").exists(),
        })
    return out


def _ensure_worker() -> None:
    global _WORKER_STARTED
    with _LOCK:
        if not _WORKER_STARTED:
            threading.Thread(target=_worker, name="hiagent-platform-worker",
                             daemon=True).start()
            _WORKER_STARTED = True


def assert_no_test_seam() -> None:
    """**服务进程里不许存在测试缝** —— 设了就直接拒绝启动（§0 fail-fast）。

    为什么要把"打一句警告"升级成"拒绝启动"：`HIAGENT_JOBS_FAKE_SLEEP` 一旦被设上，
    每个作业的子进程都**跳过真实回测**、回一个 `{"metrics": {}, "trades": []}` ——
    作业状态是 **`done`**、结果页上**指标全空、零笔成交**，看起来完全像
    "这个策略在这段时间没找到机会"，而**它其实一次都没跑**。
    而它**在提交时就被记进了 §5 账本**，于是账本里多出一堆没发生过的迭代。

    原实现只在**子进程**里 `print` 一句警告 —— 而那发生在 `os.dup2` **之后**，
    所以那句话只落在**这一笔自己的 `run.log`** 里，**服务端日志一句都没有**。
    警告打在人不会看的地方，等于没有警告。

    测试**不会**创建服务（`_install_fake_run` 顶掉的是 `_run_one`，不经过子进程），
    所以这条不会挡住测试。它挡的正是"调试时设了忘了取消，然后一直用假结果"。
    """
    import os

    fake = os.environ.get(_CHILD_FAKE_SLEEP_ENV)
    if fake:
        raise RuntimeError(
            f"{_CHILD_FAKE_SLEEP_ENV}={fake} 已设置 —— 这是**仅供测试**的开关，"
            "会让每次回测都跳过真实计算、返回空的 done 结果（并照常记进 §5 账本）。"
            "服务进程拒绝在这种状态下启动：请 unset 它再启动。"
        )


def submit(
    engine: str,
    preset: str,
    overrides: dict[str, Any] | None,
    start: str,
    end: str,
    mode: str,
) -> str:
    """入队并立即返回 `run_id`。

    **记账在这里发生，不在 worker 里**：一次迭代在提交时就发生了，
    即使作业随后失败或被取消也不该从账本里消失（§5）。
    """
    # ⚠️ **这里不再调 `assert_no_test_seam()`。**
    # 我第一版把它也加在 `submit()` 上，结果是**测试自己把自己挡住了**：
    # `fast_child` fixture 正是靠设 `HIAGENT_JOBS_FAKE_SLEEP` 让子进程快睡，
    # 而那些测试随后就调 `submit()` —— 10 条测试因此变红（已修）。
    # 缝的守卫属于**服务进程**（`create_app()`），不属于"有人提交了一次作业"。
    run_id = uuid.uuid4().hex[:12]
    home = run_dir(run_id)                       # 建目录 + 断言在仓库外（§7）
    trial_no = append_trial(
        run_id=run_id, engine=engine, preset=preset,
        param_diff=dict(overrides or {}), start=start, end=end, mode=mode,
    )
    job = Job(run_id=run_id, engine=engine, preset=preset,
              overrides=dict(overrides or {}), start=start, end=end, mode=mode,
              trial_no=trial_no)
    # ⚠️ **入表与入队必须在同一个临界区里。**
    # 原实现先 `_JOBS[run_id] = job`、再（隔着写 job.json 与起 worker）`_QUEUE.put`，
    # 于是两个并发 `submit` 的 **`_JOBS` 插入序可能与实际出队序相反** ——
    # 而 `queue_position` 正是按 `_JOBS` 的插入序数"前面还有几个"，
    # 于是界面会告诉用户一个**反的**排队位置。
    # `_QUEUE` 无界，`put` 不会阻塞，放在锁里是安全的。
    with _LOCK:
        _JOBS[run_id] = job
        _QUEUE.put(run_id)
    (home / "job.json").write_text(
        json.dumps({"run_id": run_id, "engine": engine, "preset": preset,
                    "overrides": job.overrides, "start": start, "end": end,
                    "mode": mode, "trial_no": trial_no},
                   ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    _ensure_worker()
    return run_id


def cancel(run_id: str) -> str:
    """取消一个作业，返回取消后的状态。

    - **排队中** → 标记 `cancelled`；worker 取到它时会跳过（不启动子进程）。
    - **运行中** → `terminate()` 子进程。**这就是"为什么要用子进程"的答案**：
      线程做不到这一点，"取消"会退化成"等它跑完再丢结果"。
    - 已结束的 → 原样返回其状态（幂等）。
    """
    job = _JOBS.get(run_id)
    if job is None:
        raise KeyError(run_id)
    with _LOCK:
        if job.status in {"done", "failed", "cancelled"}:
            return job.status
        was_queued = job.status == "queued"
        job.status = "cancelled"
        # `status` 与 `proc` 由 worker 在同一临界区（见 `_worker`）发布，所以：
        #   读到 `queued` ⇒ 子进程一定还没起，标记即可（worker 醒来会自己跳过）；
        #   读到 `running` ⇒ `job.proc` 一定已存在，不会再有"见了 running 却没东西可杀"的漏杀。
        proc = None if was_queued else job.proc
    # terminate/join 放在**临界区外**：join 最长 10 秒，握着锁做会把 submit() 一起堵住。
    if proc is not None and proc.is_alive():
        proc.terminate()
        proc.join(timeout=10)
    return job.status


def queue_position(run_id: str) -> int | None:
    """该作业前面还有几个在排队（`running` 中的算 0）。不在队列里则 None。

    单 worker 下一次只能跑一个，所以"前面还有几个"就是用户唯一能看到的等待依据。

    ⚠️ **判据不能是"queued 的总数减一"**（计划原文如此，已修）：那数的是**队列里所有人**
    而不是**我前面的人**，且把自己当成了一次占位。实测：第一个在跑、第二个在排队时
    计划实现返回 `0`——用户看到"马上就到我了"，而实际上还要等一整个 5–8 分钟。
    正确做法是**按提交顺序数前缀**（dict 保持插入顺序，即 FIFO），**正在跑的那个也算 1 个**：
    它此刻正占着唯一的 worker，挡在我前面。
    """
    job = _JOBS.get(run_id)
    if job is None or job.status in {"done", "failed", "cancelled"}:
        return None
    if job.status == "running":
        return 0
    order = list(_JOBS)                     # 插入顺序 == 提交顺序（FIFO）
    return sum(1 for rid in order[: order.index(run_id)]
               if _JOBS[rid].status in {"queued", "running"})


def get(run_id: str) -> Job | None:
    return _JOBS.get(run_id)


def wait(run_id: str, timeout: float | None = None) -> Job:
    """阻塞到作业结束（供测试用；HTTP 层用轮询，不调用这个）。

    ⚠️ **`cancelled` 也算"结束"。** 原先的终止集合是 `{"done", "failed"}`，
    于是对**已被取消**的作业调 `wait()` 会一直空转到 timeout 再抛 `TimeoutError`
    —— 与"阻塞到作业结束"这句 docstring 直接矛盾（实测复现过）。
    """
    import time

    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        job = _JOBS.get(run_id)
        if job is None:
            raise KeyError(run_id)
        if job.status in {"done", "failed", "cancelled"}:
            return job
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError(f"job {run_id} still {job.status} after {timeout}s")
        time.sleep(0.05)
