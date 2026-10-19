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
