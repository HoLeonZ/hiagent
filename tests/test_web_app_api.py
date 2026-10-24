"""HTTP 边界：状态码、稳定下标、以及前端端点契约。"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from web import jobs as jobs_mod
from web.app import create_app

from hiagent_config import get_db_path

REAL_DB = get_db_path()
SKIP_REASON = "需要 DNA_STRAT_DB 或 hiagent_config.DEFAULT_DB_PATH"


def _db() -> Path | None:
    env = os.environ.get("DNA_STRAT_DB")
    if env and Path(env).exists():
        return Path(env)
    return REAL_DB if REAL_DB.exists() else None


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("HIAGENT_PLATFORM_HOME", str(tmp_path))
    return TestClient(create_app())


def _install_fake_run(monkeypatch, fake_run):
    """把 `fake_run` 接到**真实**的作业管道上，不跑真回测。

    ⚠️ **勘误（计划 `.superpowers/sdd/platform-task-6-brief.md`）**：计划里的测试写
    `monkeypatch.setattr(jobs_mod, "_run_impl", fake_run)`，但 `web/jobs.py` 里**没有**
    `_run_impl` 这个名字——`_run_one` 是 `spawn` 一个**子进程**去跑 `web.runners.run`。
    照抄计划的话，这个 monkeypatch 是个**静默的空操作**（父进程里凭空多一个没人读的属性），
    于是一条测试会真的启动一次 6 个月全 universe 的回测（数分钟）。
    子进程里的 patch 也不会生效（`spawn` 是全新的解释器）。

    故**换到实际存在的接缝**：`_run_one` 是 worker 唯一的动作入口，顶掉它就等于
    "引擎跑在父进程里"。作业队列、状态机、`wait()`、终止条件**仍然是真货**——
    被替换的只有"具体怎么跑引擎"这一步，那正是这里要替换的东西。
    """
    def _run_one(run_id):
        job = jobs_mod.get(run_id)
        if job is None or job.status == "cancelled":
            return
        job.status = "running"
        try:
            result = fake_run(job.engine, job.preset, job.start, job.end,
                              overrides=job.overrides, mode=job.mode)
        except Exception as exc:                      # noqa: BLE001 — 与 jobs 同语义
            job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"
            return
        if job.status == "cancelled":
            return                                    # 取消：结果丢弃（与 jobs 同）
        job.result = result
        job.status = "done"

    monkeypatch.setattr(jobs_mod, "_run_one", _run_one)


#: `chase_up` 的真实预设名（计划里的两处 `engine="chase_up", preset="v50_slope"`
#: 是**不存在的组合**——`v50_slope` 只在 short_reversal 里，`create_run` 会 404，
#: 测试在 `.json()["run_id"]` 处就 KeyError。见报告勘误。）
CHASE_PRESET = "chase_v5_pos2_equal_atr_tp6_sl15_mh10"


def test_catalog_lists_all_101_presets_across_four_engines(client):
    got = client.get("/api/catalog").json()
    assert sum(e["preset_count"] for e in got["engines"]) == 101
    assert {e["name"] for e in got["engines"]} == {
        "short_reversal", "chase_up", "uptrend_pullback", "cycle_price_action"
    }


def test_catalog_ships_the_metric_render_metadata(client):
    """指标的 {label, kind} 随 catalog 下发（设计文档 §6.1）——前端不自备一份。

    没有这条，前后端各存一份标签表，漂移的表现是"某一格显示成英文/格式不对"，
    **不会有人注意到**。
    """
    from web.metrics_view import CANONICAL_KEYS

    meta = client.get("/api/catalog").json()["metric_meta"]
    assert set(meta) == set(CANONICAL_KEYS), "每个规范键都要有渲染元数据"
    assert all(m["label"] and m["kind"] for m in meta.values())
    assert all(m["kind"] in {"pct", "money", "ratio", "count", "days"} for m in meta.values())


def test_each_preset_exposes_tunable_and_readonly_declarations(client):
    got = client.get("/api/catalog").json()
    rv = next(p for p in got["presets"] if p["preset"] == "v50_slope")
    assert "tp_pct" in rv["tunable"]
    assert "n_comparisons" in rv["declarations"]
    assert not (set(rv["tunable"]) & set(rv["declarations"]))


def test_overriding_a_declaration_field_is_rejected_with_400(client):
    resp = client.post("/api/runs", json={
        "engine": "short_reversal", "preset": "v50_slope",
        "overrides": {"position_fraction": 0.5},
        "start": "2024-01-01", "end": "2025-01-01", "mode": "full",
    })
    assert resp.status_code == 400
    assert "declaration" in resp.json()["detail"]


def test_overriding_an_unknown_key_is_rejected_with_400(client):
    resp = client.post("/api/runs", json={
        "engine": "short_reversal", "preset": "v50_slope",
        "overrides": {"nope": 1},
        "start": "2024-01-01", "end": "2025-01-01", "mode": "full",
    })
    assert resp.status_code == 400
    assert "unknown" in resp.json()["detail"]


def test_unknown_preset_is_404(client):
    resp = client.post("/api/runs", json={
        "engine": "short_reversal", "preset": "does_not_exist",
        "overrides": {}, "start": "2024-01-01", "end": "2025-01-01", "mode": "full",
    })
    assert resp.status_code == 404


def test_start_after_end_is_400(client):
    resp = client.post("/api/runs", json={
        "engine": "short_reversal", "preset": "v50_slope", "overrides": {},
        "start": "2025-01-01", "end": "2024-01-01", "mode": "full",
    })
    assert resp.status_code == 400


def test_unknown_run_is_404(client):
    assert client.get("/api/runs/deadbeef").status_code == 404


def test_the_trade_index_is_a_stable_sort_over_the_full_list(client, monkeypatch):
    """图表端点的 {i} 必须是**全量列表**的稳定下标。

    若用筛选后的下标，用户一改筛选，点同一行会看到另一笔交易。
    """
    from web import jobs as jobs_mod
    from web.runners import RunResult

    def fake_run(*a, **kw):
        trades = [
            {"entry_date": "2025-03-01", "thscode": "000002.SZ", "entry_price": 2.0},
            {"entry_date": "2025-01-01", "thscode": "000001.SZ", "entry_price": 1.0},
        ]
        return RunResult("short_reversal", "v50_slope", "2025-01-01", "2025-06-01",
                         {"trades_count": 2}, trades)

    _install_fake_run(monkeypatch, fake_run)
    rid = client.post("/api/runs", json={
        "engine": "short_reversal", "preset": "v50_slope", "overrides": {},
        "start": "2025-01-01", "end": "2025-06-01", "mode": "full",
    }).json()["run_id"]
    jobs_mod.wait(rid, timeout=5)
    rows = client.get(f"/api/runs/{rid}/trades").json()["rows"]
    assert [r["entry_date"] for r in rows] == ["2025-01-01", "2025-03-01"], \
        "必须按 (entry_date, thscode) 稳定排序"
    assert [r["i"] for r in rows] == [0, 1]


def test_a_non_finite_value_never_reaches_the_wire(client, monkeypatch):
    """Global Constraints：出口不得输出 `NaN`/`±Inf` —— 否则**端点 500**。

    实测的两个产出方（不是假想）：
      · `chase_up/backtrader_engine.py:312` 在 `atr_pct` 缺失时**显式写入 `float("nan")`**；
      · `chase_up/backtest.py:64` 的 `profit_factor` 在**无亏损时无条件**是 `float("inf")`。

    非有限数的语义是"这个数没有意义"，所以正确的线上表示是 `null`——
    这跟缺键补 `None`（而不是补 0）是同一条 §0 规则。
    """
    from web import jobs as jobs_mod
    from web.runners import RunResult

    def fake_run(*a, **kw):
        trades = [{"entry_date": "2025-01-01", "thscode": "000001.SZ", "entry_price": 1.0,
                   "atr_pct": float("nan"), "net_return": float("inf")}]
        return RunResult("chase_up", CHASE_PRESET, "2025-01-01", "2025-06-01",
                         {"trades_count": 1, "sharpe": float("inf"), "cagr": float("nan")},
                         trades)

    _install_fake_run(monkeypatch, fake_run)
    rid = client.post("/api/runs", json={
        "engine": "chase_up", "preset": CHASE_PRESET, "overrides": {},
        "start": "2025-01-01", "end": "2025-06-01", "mode": "full",
    }).json()["run_id"]
    jobs_mod.wait(rid, timeout=5)

    resp = client.get(f"/api/runs/{rid}")
    assert resp.status_code == 200, f"出口吐了非有限数 → {resp.status_code}"
    assert resp.json()["metrics"]["sharpe"] is None
    assert resp.json()["metrics"]["cagr"] is None

    row = client.get(f"/api/runs/{rid}/trades").json()["rows"][0]
    assert row["atr_pct"] is None and row["net_return"] is None
    assert row["entry_price"] == 1.0          # 有限值原样保留


def test_the_net_can_actually_fire():
    """**自检**：证明这道网不是摆设。

    只断言"加了网之后是 None"是**与被测代码同源**的检查——它证明不了
    "没网时真的会坏"。这条把同一份 payload 交给**未加网的**编码器，
    要求它必须抛：如果哪天 Starlette 放宽了 `allow_nan`，这条会变红，
    提醒我这条防线的前提变了（而不是悄悄变成 no-op）。
    """
    import json as _json

    from starlette.responses import JSONResponse

    from web.app import SafeJSONResponse

    dirty = {"a": [1.0, float("inf")], "b": {"c": float("nan")}}
    assert _json.loads(SafeJSONResponse(dirty).render(dirty)) == {"a": [1.0, None], "b": {"c": None}}
    with pytest.raises(ValueError):
        JSONResponse(dirty).render(dirty)


def test_numpy_scalars_are_accepted_by_the_boundary():
    """`json.dumps(np.int64(7))` / `np.bool_(True)` / `np.float32(1.5)` 全都抛 `TypeError` → 500。

    numpy 是本仓库的硬依赖、引擎里到处在做 `np.*` 归约，所以这类标量混进
    metrics/trades 是迟早的事。网在出口把它们转成 Python 原生标量。
    """
    import json as _json

    import numpy as np

    from web.app import SafeJSONResponse

    payload = {"n": np.int64(7), "b": np.bool_(True), "f": np.float32(1.5)}
    assert _json.loads(SafeJSONResponse(payload).render(payload)) == {"n": 7, "b": True, "f": 1.5}


def test_the_gate_is_on_the_wire_not_only_on_the_response_class(client, monkeypatch):
    """**这条才是闸的判别力核心**：numpy 标量必须能真的穿过端点。

    上一条只证明 `SafeJSONResponse.render` 自己不炸——**它在线上从来没被调用过也能过**。
    本会话实测过这种情形：计划原文那套接线（只设 `default_response_class`）下，
    FastAPI 会在响应类**之前**自己 pydantic 序列化一遍，`np.int64` → 500，
    而 `SafeJSONResponse.render` 一次都没执行。所以"响应类单测绿"证明不了任何线上行为。

    这条走真 HTTP：`np.int64(5)` / `np.bool_(True)` / `np.float32(1.5)` 混进 trades，
    端点必须 200，且值原样落到 JSON 上。
    """
    from web import jobs as jobs_mod
    from web.runners import RunResult

    import numpy as np

    def fake_run(*a, **kw):
        trades = [{"entry_date": "2025-01-01", "thscode": "000001.SZ", "entry_price": 1.0,
                   "atr_pct": float("nan"), "size": np.int64(5),
                   "flag": np.bool_(True), "ratio": np.float32(1.5)}]
        return RunResult("chase_up", CHASE_PRESET, "2025-01-01", "2025-06-01",
                         {"trades_count": 1}, trades)

    _install_fake_run(monkeypatch, fake_run)
    rid = client.post("/api/runs", json={
        "engine": "chase_up", "preset": CHASE_PRESET, "overrides": {},
        "start": "2025-01-01", "end": "2025-06-01", "mode": "full",
    }).json()["run_id"]
    jobs_mod.wait(rid, timeout=5)

    resp = client.get(f"/api/runs/{rid}/trades")
    assert resp.status_code == 200, f"numpy 标量在出口炸了 → {resp.status_code}"
    row = resp.json()["rows"][0]
    assert row["size"] == 5 and type(row["size"]) is int, "np.int64 必须变成原生 int"
    assert row["flag"] is True, "np.bool_ 必须变成原生 bool"
    assert row["ratio"] == 1.5, "np.float32 必须变成原生 float"
    assert row["atr_pct"] is None


def test_the_csv_export_leaves_a_blank_cell_for_a_non_finite_number(client, monkeypatch):
    """导出的 CSV 里非有限数必须是**空单元格**，不是字面量 `nan`。

    §0 要求"这个数没有意义"与"这个数是 0"可区分；`nan` 在 CSV 里既不是数字
    也不是空，读表的人会把它当成一个真值。空单元格才是诚实的表示。
    """
    from web import jobs as jobs_mod
    from web.runners import RunResult

    def fake_run(*a, **kw):
        trades = [{"entry_date": "2025-01-01", "exit_date": "2025-01-03",
                   "thscode": "000001.SZ", "exit_reason": "TP", "entry_price": 1.0,
                   "exit_price": 1.1, "size": 100, "hold_days": 2,
                   "gross_pnl": 10.0, "fees": 1.0, "net_pnl": 9.0,
                   "net_return": 0.09, "atr_pct": float("nan"), "sub_signal_type": "a"}]
        return RunResult("chase_up", CHASE_PRESET, "2025-01-01", "2025-06-01",
                         {"trades_count": 1}, trades)

    _install_fake_run(monkeypatch, fake_run)
    rid = client.post("/api/runs", json={
        "engine": "chase_up", "preset": CHASE_PRESET, "overrides": {},
        "start": "2025-01-01", "end": "2025-06-01", "mode": "full",
    }).json()["run_id"]
    jobs_mod.wait(rid, timeout=5)

    body = client.get(f"/api/runs/{rid}/export/trades.csv").text
    assert "nan" not in body.lower(), f"CSV 里出现了字面量 nan:\n{body}"
    line = body.splitlines()[1].split(",")
    assert line[12] == "", "atr_pct 应为空单元格（第 13 列）"


def test_the_configs_endpoints_round_trip(client):
    """命名配置的增 / 查 / 复制 / 删（前端「我的策略」面板，`app.js` 走的就是这四个）。

    ⚠️ **计划里没有这条，而 `POST /api/configs` 在计划原文里是坏的**：`ConfigRequest`
    被定义在 `create_app()` **内部**，本文件又有 `from __future__ import annotations`，
    于是注解在运行时是字符串、FastAPI 只能拿**模块全局**去解析它 →
    解析不到，`req` 被当成必填 **query** 参数：任何合法请求都回
    `422 {"loc": ["query","req"], "msg": "Field required"}`（实测，与出口的网无关）。
    修法是把模型挪到模块层（见 `web/app.py` 的 `ConfigRequest` docstring）。
    """
    r = client.post("/api/configs", json={"name": "紧止损", "engine": "short_reversal",
                                          "preset": "v50_slope",
                                          "overrides": {"sl_pct": 0.01}})
    assert r.status_code == 200, r.text
    assert r.json()["effective"]["sl_pct"] == 0.01, "存的是**生效后**的完整参数快照"
    assert [c["name"] for c in client.get("/api/configs").json()["configs"]] == ["紧止损"]

    assert client.post("/api/configs/紧止损/duplicate",
                       json={"new_name": "副本"}).status_code == 200
    assert {c["name"] for c in client.get("/api/configs").json()["configs"]} == {"紧止损", "副本"}
    assert client.delete("/api/configs/副本").status_code == 200
    assert client.delete("/api/configs/副本").status_code == 404, "删两次的第二次是 404"

    assert client.post("/api/configs", json={"name": "a/b", "engine": "short_reversal",
                                             "preset": "v50_slope", "overrides": {}}).status_code == 400


def test_a_failed_run_stays_readable_after_a_restart(client, monkeypatch):
    """**失败**的运行，重启后仍然要能查到状态、读到日志。

    实测缺陷（2026-10-23，真实运行的失败预览 `f6fa740e0921`）：
    `result.json` **只在成功时**落盘，于是一次失败的运行在磁盘上只剩
    `job.json` + `run.log`；而 `/api/runs/{id}` 与 `/log` 当时的判据是
    "内存里有作业 **或** 有 result.json" —— **重启后两者都返回 404**
    （`unknown run`）。

    **那恰恰是最需要看日志的时候**：说明原因的日志就躺在磁盘上，
    API 却说这次运行不存在。用户在历史里看得见它（账本记着），点进去是 404。

    判据：状态与**原因**要读得回来，日志要读得回来，且是**失败**而不是别的状态。
    """
    from web import jobs as jobs_mod

    def boom(*a, **kw):
        raise RuntimeError("面板不足 min_bars=200")

    _install_fake_run(monkeypatch, boom)
    rid = client.post("/api/runs", json={
        "engine": "short_reversal", "preset": "v50_slope", "overrides": {},
        "start": "2025-01-01", "end": "2025-01-02", "mode": "full",
    }).json()["run_id"]
    job = jobs_mod.wait(rid, timeout=60)
    assert job.status == "failed"

    # ⚠️ 与上一条测试同理：假 runner 顶掉了 `_run_one`，生产里由它调用的
    # `_persist_outcome` / `_append_log` 都没有被走到。这里补上——**用生产自己的写入器**，
    # 写出的形态与真跑一模一样（手搓 JSON 的话，测试就在验证一个不存在的世界）。
    jobs_mod._append_log(rid, f"[jobs] 失败：{job.error}")
    jobs_mod._persist_outcome(job)

    from web.state import state_home
    run_dir = state_home() / "runs" / rid
    assert (run_dir / "outcome.json").exists(), "结局没有落盘"
    assert not (run_dir / "result.json").exists(), \
        "这条测试的前提是**没有** result.json（失败不落结果）——它变了这条就测不到东西"

    # 模拟重启：内存全清，只剩磁盘
    jobs_mod._JOBS.clear()

    got = client.get(f"/api/runs/{rid}")
    assert got.status_code == 200, \
        f"重启后失败的运行是 {got.status_code} —— 它读不到自己的失败原因"
    body = got.json()
    assert body["status"] == "failed"
    assert "min_bars=200" in (body["error"] or ""), "失败原因必须读得回来"
    assert body["metrics"] is None

    log = client.get(f"/api/runs/{rid}/log")
    assert log.status_code == 200, "重启后读不到失败运行的日志——而那正是唯一能查原因的东西"
    assert "min_bars=200" in log.json()["text"]


def test_a_run_with_no_outcome_file_is_not_reported_as_failed(client, monkeypatch):
    """**没有 outcome.json 的运行，不许被说成 "failed"。**

    进程在运行中被杀（服务崩了、机器重启）时，那次运行在磁盘上只剩
    `job.json`；平台**并不知道**它最后怎么了。把它标成 `failed` 是在
    编一个我们拿不到的事实——而"失败"会让用户去找一个并不存在的错误。

    判据：状态是 `unknown`，原因留空。
    """
    from web import jobs as jobs_mod

    rid = "killedmidway01"
    from web.state import state_home
    d = state_home() / "runs" / rid
    d.mkdir(parents=True, exist_ok=True)
    (d / "job.json").write_text(
        '{"engine": "short_reversal", "preset": "v50_slope", "start": "2025-01-01",'
        ' "end": "2025-02-01", "mode": "full"}', encoding="utf-8")
    jobs_mod._JOBS.clear()

    body = client.get(f"/api/runs/{rid}").json()
    assert body["status"] == "unknown", \
        f"没有结局证据时不该断言失败，现在报的是 {body['status']!r}"
    assert body["error"] is None


def test_result_endpoints_survive_a_restart_by_reading_from_disk(client, monkeypatch):
    """**服务重启后，交易表与 K 线仍要能打开。**

    实测缺陷（2026-10-19：起服务、跑完一次真 preview、重启、再打开那次运行）：
    `GET /api/runs/{id}`、`/equity`、`/positions`、两处 `/export` 都能从磁盘读回，
    **而 `/trades` 与 `/trades/{i}/chart` 只查内存 `_JOBS` → 404**。
    于是历史面板里点开一次旧运行：头部说 `done`，交易表与 K 线却是空的——
    而设计里"历史"面板明写"结果来自磁盘，**不重跑回测**"。

    这条测试就是那天缺的那条：跑完一次（结果落盘）→ **清空内存**（模拟重启）→ 两个端点仍须可用。
    判据不能只看状态码——`/trades` 还要真的给出那几行，`/chart` 还要真的解析出这笔交易。
    """
    import json
    from pathlib import Path as _P

    from web import jobs as jobs_mod
    from web.runners import RunResult

    def fake_run(*a, **kw):
        trades = [{"entry_date": "2025-03-05", "exit_date": "2025-03-07",
                   "thscode": "000001.SZ", "exit_reason": "SL", "entry_price": 10.0,
                   "exit_price": 10.5, "size": 100, "hold_days": 2,
                   "gross_pnl": -50.0, "fees": 1.0, "net_pnl": -51.0,
                   "net_return": -0.051, "atr_pct": 0.02, "sub_signal_type": "a"}]
        return RunResult("short_reversal", "v50_slope", "2025-01-01", "2025-06-01",
                         {"trades_count": 1}, trades)

    _install_fake_run(monkeypatch, fake_run)
    rid = client.post("/api/runs", json={
        "engine": "short_reversal", "preset": "v50_slope", "overrides": {},
        "start": "2025-01-01", "end": "2025-06-01", "mode": "full",
    }).json()["run_id"]
    job = jobs_mod.wait(rid, timeout=60)

    # ⚠️ 假 runner 顶掉的是 `_run_one`（worker 唯一的动作入口），
    # 于是**生产里由 `_run_one` 调用的 `_persist_result` 也没被走到**。
    # 这里补上这一步——用的是**生产自己的写入器**，写出的形态与真跑一模一样，
    # 而不是手搓一份 JSON（手搓的话，`resolve` 能读、生产却写不出同样形态，
    # 这条测试就变成了在验证一个不存在的世界）。
    jobs_mod._persist_result(job, {"start": job.start, "end": job.end,
                                   "metrics": job.result.metrics,
                                   "trades": job.result.trades})

    from web.state import state_home
    assert (state_home() / "runs" / rid / "result.json").exists(), "结果没有落盘"
    assert (state_home() / "runs" / rid / "job.json").exists(), "元数据没有落盘"

    # 模拟重启：内存全清，只剩磁盘
    jobs_mod._JOBS.clear()

    assert client.get(f"/api/runs/{rid}").status_code == 200

    tr = client.get(f"/api/runs/{rid}/trades")
    assert tr.status_code == 200, f"重启后 /trades 是 {tr.status_code}——它只查了内存"
    body = tr.json()
    assert body["total"] == 1 and body["rows"][0]["thscode"] == "000001.SZ"
    # 补齐的 sl/tp 也要在（用户要的就是这个）
    assert body["rows"][0]["sl_price"] is not None
    assert body["rows"][0]["tp_price"] is not None
    assert "sl_price" in body["columns"], "有值却没有列，前端表头不会出现它"

    ch = client.get(f"/api/runs/{rid}/trades/0/chart")
    assert ch.status_code == 200, f"重启后 /chart 是 {ch.status_code}——它只查了内存"
    assert ch.json()["entry"]["price"] == 10.0


def test_the_trades_list_and_the_chart_agree_on_sl_tp(client, monkeypatch):
    """交易表里的 sl/tp 与图上的 `markLine` **必须逐位相同**。

    两处都从 `web/chart.py` 的 `sl_tp_prices` 推（§6 单一来源），
    但若哪天有人在 `app.py` 里再手写一遍 `entry * (1 ± pct)`，它们就会各自漂移——
    而"表里一个数、图上一条线、两者不一致"是最难被发现的那类错。
    """
    from web import jobs as jobs_mod
    from web.runners import RunResult

    def fake_run(*a, **kw):
        return RunResult("short_reversal", "v50_slope", "2025-01-01", "2025-06-01",
                         {"trades_count": 1},
                         [{"entry_date": "2025-03-05", "exit_date": "2025-03-07",
                           "thscode": "000001.SZ", "exit_reason": "SL", "entry_price": 10.0,
                           "exit_price": 10.5, "size": 100, "hold_days": 2,
                           "gross_pnl": -50.0, "fees": 1.0, "net_pnl": -51.0,
                           "net_return": -0.051, "atr_pct": 0.02, "sub_signal_type": "a"}])

    _install_fake_run(monkeypatch, fake_run)
    rid = client.post("/api/runs", json={
        "engine": "short_reversal", "preset": "v50_slope", "overrides": {},
        "start": "2025-01-01", "end": "2025-06-01", "mode": "full",
    }).json()["run_id"]
    jobs_mod.wait(rid, timeout=60)

    row = client.get(f"/api/runs/{rid}/trades").json()["rows"][0]
    chart = client.get(f"/api/runs/{rid}/trades/0/chart").json()
    assert row["sl_price"] == chart["sl_price"], "表里的止损价与图上的止损线不是同一个数"
    assert row["tp_price"] == chart["tp_price"], "表里的止盈价与图上的止盈线不是同一个数"
    # 空头：止损在入场价**上方**、止盈在**下方**
    assert row["sl_price"] > row["entry_price"] > row["tp_price"]


def test_window_metrics_uses_the_requested_window_not_the_engine_panel():
    """**指标按请求窗口算**，不按引擎的面板（§4.6.1 同一族的口径错配）。

    实测缺陷（2026-10-21）：引擎的记录器覆盖的是**带缓冲的面板**
    （`[start-180d, end+60d]`，引擎不设 fromdate/todate），于是它
      · **在窗口之前交易**（实测 45 笔里 3 笔入场早于窗口起点）；
      · `cagr` 分母用窗口年数、分子却含窗口前的盈亏
        （`short_reversal/engine.py:65-70`）。
    平台已经把净值曲线切到 `[start, end]`（设计文档明文要求），
    而曲线端点**必然**给出窗口收益 —— 所以窗口口径是**设计自己选的**。
    指标表没跟着切，于是**同一个结果页自己跟自己不一致**：
      指标表 total_return 114.24% vs 曲线栏 strategy_return 115.03%。

    本条不依赖 DB：用一条自造的曲线与成交，把窗口语义钉死。
    """
    from web.metrics_view import window_metrics

    class _R:
        start, end = "2025-01-01", "2025-03-01"

        def __init__(self, curve, trades):
            self.metrics = {"equity_curve": curve}
            self.trades = trades

    # 曲线故意伸出窗口两头：2024-12-20（窗口前）.. 2025-03-10（窗口后）
    curve = [
        {"date": "2024-12-20", "equity": 1_000_000.0},   # 窗口外
        {"date": "2025-01-01", "equity": 900_000.0},     # 窗口起点
        {"date": "2025-02-01", "equity": 1_100_000.0},
        {"date": "2025-03-01", "equity": 1_200_000.0},   # 窗口终点
        {"date": "2025-03-10", "equity": 5_000_000.0},   # 窗口外
    ]
    trades = [
        {"entry_date": "2024-12-24", "net_pnl": 999_999.0, "hold_days": 30},  # 窗口外
        {"entry_date": "2025-01-15", "net_pnl": 100.0, "hold_days": 2},
        {"entry_date": "2025-02-15", "net_pnl": -50.0, "hold_days": 3},
        {"entry_date": "2025-03-20", "net_pnl": 888_888.0, "hold_days": 40},  # 窗口外
    ]
    m = window_metrics(_R(curve, trades))

    # 曲线：只用窗口内的 900000 → 1200000
    assert m["final_capital"] == 1_200_000.0
    assert abs(m["total_return"] - (1_200_000 / 900_000 - 1)) < 1e-12
    # 成交：只用窗口内入场的 2 笔
    assert m["trades_count"] == 2
    assert m["total_pnl"] == 50.0
    assert m["win_rate"] == 0.5
    assert m["avg_hold_days"] == 2.5
    # 盈亏比：100/50 = 2.0
    assert abs(m["profit_factor"] - 2.0) < 1e-12
    # 回撤：窗口内峰值 1_200_000 之前的 900_000 → 峰 1_100_000 → 谷 1_200_000 无回撤
    assert m["max_dd"] == 0.0


def test_the_metrics_table_and_the_curve_agree(client, monkeypatch):
    """**同一个结果页不能自己跟自己不一致**（聚宽那边两者是同一套数）。

    这是这次改动的验收点：指标表的 `total_return` 必须等于曲线栏的
    `strategy_return`，`max_dd` 必须等于曲线回撤序列的最大值。

    ⚠️ **它与另一条测试分工，不是重复**：
      · 本条测"**两个端点彼此自洽**"（同一次运行，页面不能有两个答案）；
      · `test_window_metrics_uses_the_requested_window_not_the_engine_panel` 测
        "**窗口是否真被应用**"。
    所以本条在"窗口切片被摘掉"时**仍然绿**——那时两个端点一起不切，仍然彼此一致。
    摘掉切片会让**那一条**变红。两条合起来才覆盖全部。

    ⚠️ 需要本地 DB（`/equity` 会真查库算基准序列），故按 §6 skip 而非 error。
    """
    from web import jobs as jobs_mod
    from web.runners import RunResult

    real_db = get_db_path()
    if not (real_db.exists() or Path(os.environ.get("DNA_STRAT_DB", "")).exists()):
        pytest.skip("需要 DNA_STRAT_DB 或 hiagent_config.DEFAULT_DB_PATH")

    import datetime as dt

    from web.state import state_home

    def fake_run(*a, **kw):
        # 曲线**故意伸出窗口两头**（2024-12-20 与 2025-03-10）——
        # 否则整段都在窗口内，切不切都一样，这条测试就没有判别力了。
        curve = []
        v = 1_000_000.0
        for i in range(-12, 50):
            v *= 1.01
            curve.append({"date": (dt.date(2025, 1, 1) + dt.timedelta(days=i)).isoformat(),
                          "equity": v})
        trades = [{"entry_date": "2025-01-05", "exit_date": "2025-01-07", "thscode": "000001.SZ",
                   "exit_reason": "TP", "entry_price": 1.0, "exit_price": 1.1, "size": 100,
                   "hold_days": 2, "gross_pnl": 10.0, "fees": 1.0, "net_pnl": 9.0,
                   "net_return": 0.09, "atr_pct": 0.02, "sub_signal_type": "a"}]
        return RunResult("short_reversal", "v50_slope", "2025-01-01", "2025-02-09",
                         {"trades_count": 1, "equity_curve": curve}, trades)

    _install_fake_run(monkeypatch, fake_run)
    rid = client.post("/api/runs", json={
        "engine": "short_reversal", "preset": "v50_slope", "overrides": {},
        "start": "2025-01-01", "end": "2025-02-09", "mode": "full",
    }).json()["run_id"]
    jobs_mod.wait(rid, timeout=60)

    m = client.get(f"/api/runs/{rid}").json()["metrics"]
    e = client.get(f"/api/runs/{rid}/equity").json()
    assert abs(m["total_return"] - e["strategy_return"]) < 1e-9, (
        f"指标表 total_return={m['total_return']} 与曲线栏 strategy_return="
        f"{e['strategy_return']} 不一致 —— 同一个页面不能有两个答案"
    )
    assert abs(m["max_dd"] - max(d["value"] for d in e["drawdown"])) < 1e-9, \
        "指标表的最大回撤必须与曲线回撤序列的最大值一致"

    # 年度收益：**必须与曲线同源（窗口切片后）**，且复利回去要等于累计收益。
    import math
    per = e["periods"]["rows"]
    assert per, "结果页的年度收益表是空的"
    assert per[0]["period"] == "2025", (
        f"年度收益用了**没切窗口**的曲线（首段是 {per[0]['period']}）—— "
        "假曲线故意伸到 2024-12-20，切过的首段只能是 2025"
    )
    assert per[0]["from"] >= "2025-01-01", "首段的起点必须是窗口起点，不是曲线起点"
    comp = math.prod(1 + r["return"] for r in per if r["return"] is not None)
    assert abs(comp - (1 + e["strategy_return"])) < 1e-9, (
        f"年度收益复利回去是 {comp - 1}，而累计收益是 {e['strategy_return']} —— "
        "**可加性**是两个都要显示的相邻数字之间唯一的一致性"
    )


def _fake_run_with_window_leak():
    """一次带"窗口外成交"的假运行 —— 用来验证各处的窗口口径一致。"""
    from web.runners import RunResult

    trades = []
    for i, d in enumerate(("2024-12-20",   # 窗口外（早）
                           "2025-01-05", "2025-01-15",   # 窗口内
                           "2025-03-20")):               # 窗口外（晚）
        trades.append({"entry_date": d, "exit_date": d, "thscode": f"00000{i}.SZ",
                       "exit_reason": "SL", "entry_price": 1.0 + i, "exit_price": 1.1 + i,
                       "size": 100, "hold_days": 2, "gross_pnl": 1.0, "fees": 0.1,
                       "net_pnl": 0.9, "net_return": 0.009, "atr_pct": 0.02,
                       "sub_signal_type": "a", "net": 0.009})
    return RunResult("short_reversal", "v50_slope", "2025-01-01", "2025-03-01",
                     {"trades_count": 4, "equity_curve": [
                         {"date": "2024-12-20", "equity": 1_000_000.0},
                         {"date": "2025-01-01", "equity": 900_000.0},
                         {"date": "2025-03-01", "equity": 1_200_000.0},
                         {"date": "2025-03-20", "equity": 5_000_000.0}]}, trades)


def _submit_fake(client, monkeypatch):
    from web import jobs as jobs_mod

    _install_fake_run(monkeypatch, lambda *a, **kw: _fake_run_with_window_leak())
    rid = client.post("/api/runs", json={
        "engine": "short_reversal", "preset": "v50_slope", "overrides": {},
        "start": "2025-01-01", "end": "2025-03-01", "mode": "full",
    }).json()["run_id"]
    jobs_mod.wait(rid, timeout=60)
    return rid


def test_every_surface_shows_the_same_window(client, monkeypatch):
    """**指标表、交易表、单笔图表、CSV 导出、metrics.json 必须同一个窗口。**

    实测（2026-10-21）：指标表按窗口报了 42 笔，而交易表列了 45 行 ——
    **页面又自己跟自己矛盾了**。同一个道理，导出若比表格多出窗口外的成交，
    用户会以为导错了；而 `{i}` 的下标若不建立在同一份列表上，
    点第 i 行会取到**另一笔**交易。

    这条把五处钉在一起。
    """
    rid = _submit_fake(client, monkeypatch)

    m = client.get(f"/api/runs/{rid}").json()["metrics"]
    tr = client.get(f"/api/runs/{rid}/trades").json()
    csv = client.get(f"/api/runs/{rid}/export/trades.csv").text
    mj = client.get(f"/api/runs/{rid}/export/metrics.json").json()

    assert m["trades_count"] == 2, "指标表只应计入窗口内入场的 2 笔"
    assert tr["total"] == 2, f"交易表列了 {tr['total']} 行 —— 与指标表的口径不一致"
    assert len(csv.strip().splitlines()) - 1 == 2, "CSV 导出与交易表的口径不一致"
    assert abs(mj["metrics"]["total_return"] - m["total_return"]) < 1e-12, \
        "导出的指标与页面上看到的不是同一组数"
    # {i} 的下标建立在**同一份列表**上：表的第 0 行就是图表的第 0 笔
    assert tr["rows"][0]["thscode"] == "000001.SZ"
    chart = client.get(f"/api/runs/{rid}/trades/0/chart").json()
    assert chart["entry"]["price"] == tr["rows"][0]["entry_price"], \
        "点第 0 行取到的不是第 0 笔"


def test_the_engine_only_extra_column_is_not_duplicated_in_the_table(client, monkeypatch):
    """引擎的额外字段 `net` 不该在表里另起一列。

    它是 short_reversal 自己的"每笔净收益率"，与规范列 `net_return` 是同一件事，
    **而且只有这一个引擎会产生** —— 表里会多出一列几乎一样的数，用户只会猜哪个算数。
    §6：14 列规范（`core/trade_schema.py`）是单一来源。

    ⚠️ 去掉的必须是**列**（行字典里的键），不是**行** —— 写错会让 `columns` 变成空列表。
    """
    rid = _submit_fake(client, monkeypatch)
    tr = client.get(f"/api/runs/{rid}/trades").json()
    assert "net" not in tr["columns"], "`net` 与 `net_return` 重复，不该另起一列"
    assert tr["rows"], "去掉的是列，不是行 —— 行不能被过滤掉"
    for c in ("net_return", "entry_date", "thscode", "sl_price", "tp_price"):
        assert c in tr["columns"], f"规范列 {c} 不该丢"


def test_a_restarted_run_keeps_its_preview_marker(client, monkeypatch, tmp_path):
    """**服务重启后，preview 的"非可比"标注必须还在。**

    实测缺陷（2026-10-21）：`GET /api/runs/{id}` 的**磁盘回退路径**把 `mode`
    写死成 `None` —— 而前端只在 `job.mode === "preview"` 时挂"非可比"横幅。
    于是**服务重启后打开一次 preview 运行，标注就没了**：
    那些数字看上去像全量回测的，而它们其实只覆盖了最近 90 天。
    设计要求 preview 结果**强制标注非可比**。

    这类缺陷静态契约测试看不见 —— 两条路径都返回 200。

    这里**直接造出落盘产物**（而不是用假 runner 跑一遍）：假 runner 顶掉的是
    `_run_one` 整个函数，**落盘那一步也在里面**，于是磁盘上什么都没有、
    根本走不到回退路径 —— 那样测的就不是这个缺陷了。
    """
    import json as _json

    from web.state import state_home

    monkeypatch.setenv("HIAGENT_PLATFORM_HOME", str(tmp_path))
    state_mod = __import__("web.state", fromlist=["state"])
    state_mod._ASSERTED.clear()

    rid = "diskpreview01"
    d = state_home() / "runs" / rid
    d.mkdir(parents=True, exist_ok=True)
    (d / "result.json").write_text(_json.dumps({
        "run_id": rid, "engine": "short_reversal", "preset": "v50_slope",
        "overrides": {}, "start": "2025-01-01", "end": "2025-03-01",
        "mode": "preview", "trial_no": 7,
        "metrics": {"trades_count": 0, "equity_curve": [
            {"date": "2025-01-01", "equity": 1_000_000.0},
            {"date": "2025-03-01", "equity": 1_100_000.0}]},
        "trades": [],
    }), encoding="utf-8")
    (d / "job.json").write_text(_json.dumps({
        "run_id": rid, "engine": "short_reversal", "preset": "v50_slope",
        "overrides": {}, "start": "2025-01-01", "end": "2025-03-01",
        "mode": "preview", "trial_no": 7,
    }), encoding="utf-8")

    got = client.get(f"/api/runs/{rid}").json()
    assert got.get("from_disk") is True, f"本测试要走磁盘回退路径，实得 {got}"
    assert got["mode"] == "preview", \
        f"重启后 mode 丢了（{got.get('mode')!r}）—— preview 的'非可比'标注会消失"
    assert got["trial_no"] == 7, "trial_no 同样不该丢"


def test_compare_reports_each_runs_mode_so_mixed_selections_can_be_flagged(client, monkeypatch):
    """**`/api/compare` 必须带上 `mode`。**

    实测缺陷（2026-10-22）：compare 的行里**没有 `mode`**，前端 `x.mode` 是 `undefined`
    —— 于是"preview 与 full 混着比"这类**不可比**静默通过。
    而设计文档明令 preview 的数字"不得作为业绩依据、不可与 full 模式比较"。

    没有 `mode`，前端就只能比窗口，比不出模式差异。
    """
    import json as _json

    from web.state import state_home

    # 直接造两个落盘运行：一个 preview、一个 full（同一窗口，**只差模式**）
    for rid, mode in (("cmp" + "p" * 8, "preview"), ("cmp" + "f" * 8, "full")):
        d = state_home() / "runs" / rid
        d.mkdir(parents=True, exist_ok=True)
        (d / "result.json").write_text(_json.dumps({
            "run_id": rid, "engine": "short_reversal", "preset": "v50_slope",
            "overrides": {}, "start": "2025-01-01", "end": "2025-03-01",
            "mode": mode, "trial_no": 1,
            "metrics": {"trades_count": 0, "equity_curve": []}, "trades": [],
        }), encoding="utf-8")
        (d / "job.json").write_text(_json.dumps({
            "run_id": rid, "engine": "short_reversal", "preset": "v50_slope",
            "overrides": {}, "start": "2025-01-01", "end": "2025-03-01",
            "mode": mode, "trial_no": 1,
        }), encoding="utf-8")

    got = client.get("/api/compare?ids=" + "cmp" + "p" * 8 + "," + "cmp" + "f" * 8).json()
    modes = sorted(r["mode"] for r in got["rows"])
    assert modes == ["full", "preview"], \
        f"compare 必须给出每个运行的 mode（实得 {modes}）—— 否则模式不可比判不出来"


def test_the_log_can_be_pulled_incrementally_without_losing_or_repeating_lines(client, monkeypatch):
    """**日志的增量拉取必须严丝合缝** —— `?offset=N` 续拉出来的东西，
    与从 0 拉的全量必须**逐字符相等**。

    前端就是靠这个在回测期间持续显示的（回测 5–8 分钟，日志要能边跑边看）。
    偏移算错的表现是**重复行或丢行** —— 而两者都不会报错，只会让人读到错的日志。
    """
    import json as _json

    from web.state import state_home

    rid = "logoffset01"
    text = "\n".join(f"[jobs] 第 {i} 行输出" for i in range(20)) + "\n"
    d = state_home() / "runs" / rid
    d.mkdir(parents=True, exist_ok=True)
    (d / "run.log").write_text(text, encoding="utf-8")

    full = client.get(f"/api/runs/{rid}/log").json()
    assert full["text"] == text, "全量读取应当与文件一致"
    assert full["done"] is True
    assert full["offset"] == len(text), "offset 应当是已读到的字符数"

    for cut in (0, 7, len(text) // 2, len(text) - 1, len(text)):
        head = text[:cut]
        part = client.get(f"/api/runs/{rid}/log?offset={cut}").json()
        assert head + part["text"] == text, \
            f"从 {cut} 处续拉后拼接与全量不一致（重复或丢行）"
        # ⚠️ **`offset` 是字符数，不是字节数。** 这条断言就是那个契约：
        # 它同时钉住"续拉回来的正好是没读过的那段"这件事。
        # 原实现返回字节数（实测 offset=470 而 len(text)=310），
        # 而服务端按**字节**切 —— 偏移落在字符中间时 `errors="replace"`
        # 会**静默**把半个汉字变成 `�`，拼接就不再逐字符相等。
        assert part["offset"] == len(text), \
            f"offset 必须是**字符**数（{len(text)}），不是字节数"
        assert part["offset"] - cut == len(part["text"]), \
            "offset 的增量必须恰好等于本次返回的字符数——否则前端会漏拉或重拉"


def test_a_client_whose_offset_is_past_the_end_gets_the_whole_log_again(
    client, monkeypatch
):
    """偏移越过文件尾（日志被替换/截断）→ **从头重发**，不是回空串。

    回空串的表现是界面**永久停在空白**、而且不报错 —— 客户端再也追不回来。
    本平台只追加不截断，所以这条是防御性的；但"防御性"不等于"可以没测"，
    因为它是**这条契约上唯一会让人查很久**的分支。
    """
    from web.state import state_home

    rid = "logshort01"
    d = state_home() / "runs" / rid
    d.mkdir(parents=True, exist_ok=True)
    text = "[jobs] 只剩这一行\n"
    (d / "run.log").write_text(text, encoding="utf-8")

    got = client.get(f"/api/runs/{rid}/log?offset=99999").json()
    assert got["text"] == text, "越界应当从头重发整份日志，而不是回空串"
    assert got["offset"] == len(text)
