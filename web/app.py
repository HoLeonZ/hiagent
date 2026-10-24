"""HTTP 边界。只做解析、校验、序列化；不含回测与图表逻辑。"""
from __future__ import annotations

import functools
import inspect
import json
import math
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.datastructures import DefaultPlaceholder
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from web import jobs as jobs_mod
from web.catalog import ENGINE_NOTES, ENGINES, all_presets
from web.chart import ENGINE_DIRECTION, chart_payload, exit_levels
from web.metrics_view import (
    CANONICAL_KEYS,
    METRIC_KINDS,
    METRIC_LABELS,
    TRADE_LABELS,
    EXIT_REASON_LABELS,
    window_metrics,
    window_trades,
    window_slice,
    period_returns,
)
from web.params import OverrideError, split_params, validate_overrides
from web.runners import RunResult
from web.state import run_artifact, state_home
from web.trials import count_trials, distinct_manual_configs

STATIC_DIR = Path(__file__).parent / "static"
#: 本平台只在本机使用（设计文档 D2）
BIND_HOST = "127.0.0.1"
BIND_PORT = 8765

#: 允许的运行模式。`runners.effective_window` 只识别 `preview`，其余**一律当 full**——
#: 于是拼错的 mode（`"prev"`、`"Fast"`）会静默跑成整窗回测，而界面上写着别的字。
#: 在这里 fail-fast，别让一个标签与它实际跑的窗口不一致。
VALID_MODES: frozenset[str] = frozenset({"full", "preview"})


class RunRequest(BaseModel):
    engine: str
    preset: str
    overrides: dict[str, Any] = {}
    start: str
    end: str
    mode: str = "full"


class ConfigRequest(BaseModel):
    """⚠️ **必须定义在模块层，不能塞进 `create_app()`**（计划原文把它写在里面）。

    本文件有 `from __future__ import annotations`，所以注解在运行时是**字符串**；
    FastAPI 用 `call.__globals__`（**只有模块全局**，没有局部作用域）去解析它们。
    写在 `create_app()` 里的 `ConfigRequest` 于是解析不到，FastAPI 把 `req` 当成一个
    **必填 query 参数** —— `POST /api/configs` 对任何合法请求都回
    `422 {"loc": ["query","req"], "msg": "Field required"}`（实测，且与出口的网无关）。
    前端的"保存配置"按钮走的就是这个端点（`web/static/app.js`）。
    """
    name: str
    engine: str
    preset: str
    overrides: dict[str, Any] = {}
    note: str = ""


def _sorted_trades(trades: list[dict]) -> list[dict]:
    """稳定排序：`(entry_date, thscode)`。

    图表端点的 `{i}` 就建立在这个顺序上——**不能用筛选后的下标**，
    否则用户一改筛选，点同一行会看到另一笔交易。
    """
    return sorted(trades, key=lambda t: (str(t.get("entry_date", "")), str(t.get("thscode", ""))))


def _load_result(run_id: str) -> RunResult:
    """内存优先、磁盘兜底。两处导出端点共用，避免各写一遍回退逻辑。"""
    job = jobs_mod.get(run_id)
    result = (job.result if (job and job.result) else None) or jobs_mod.load_persisted(run_id)
    if result is None:
        raise HTTPException(404, detail=f"unknown or unfinished run: {run_id}")
    return result


def _effective_params(meta: dict[str, Any]) -> dict[str, Any]:
    """该次运行**实际生效**的参数：预设的可调值 + 用户覆盖。

    `meta` 来自 `jobs_mod.resolve`（内存优先、磁盘兜底），字段为
    `engine / preset / overrides / start / end / mode`。

    单一来源：`/trades`（推导 SL/TP）与 `/trades/{i}/chart`（交给 `chart_payload`）
    都从这里取，否则两处会各自拼一遍 `split_params + update(overrides)` 而漂移。
    """
    params = dict(split_params(meta["engine"], meta["preset"])["tunable"])
    params.update(meta.get("overrides") or {})
    return params


def _with_exit_levels(i: int, trade: dict, engine: str, params: dict[str, Any]) -> dict:
    """给一行成交补上 `sl_price` / `tp_price`（**价位**，由入场价与相对百分比推出）。

    为什么这三行值得单拿出来：用户要的是"看到 sl/tp"，
    而光有图上那两条 `markLine` 不够 —— 扫交易表时看不到它们。

    **复用 `web/chart.py` 的 `exit_levels` 与 `ENGINE_DIRECTION`，不在这里重写
    `entry × (1 ± pct)`**：图上的线与表里的数必须是同一份算术，否则它们会各自漂移，
    而"图上一条线、表里一个数、两者不一致"是最难被发现的那类错。
    """
    entry = trade.get("entry_price")
    if entry is None:
        return {"i": i, **trade, "sl_price": None, "tp_price": None}
    levels = exit_levels(params, float(entry), ENGINE_DIRECTION[engine], trade.get("atr_pct"))
    sl, tp = levels if levels is not None else (None, None)
    return {"i": i, **trade, "sl_price": sl, "tp_price": tp}


def _json_safe(v: Any) -> Any:
    """递归地把值变成**合法 JSON**：非有限数 → `None`；numpy 标量 → Python 标量。

    为什么是递归、而不是在每个端点里挑字段处理：GET 的 payload 里有嵌套
    （`bars` 列表、`rows` 列表、`metrics` dict），漏一层就漏一个 500。

    **为什么要有这一层**（本会话实测）：
    - `JSONResponse.render` 用 `allow_nan=False` → 任一 `NaN`/`±Inf` 让端点抛
      `ValueError` → **500**，用户看到"服务器错误"而不是结果页；
    - `json.dumps` 不认识 `np.int64` / `np.bool_` / `np.float32` → `TypeError` → 同样 500
      （`np.float64` 是 Python `float` 的子类，能过）。
    实测的产出方：`chase_up/backtrader_engine.py` 在 `atr_pct` 缺失时**显式写入
    `float("nan")`** 到成交记录；`chase_up/backtest.py` 的 `profit_factor` 无亏损时为 `inf`。

    **规则只写一次，接在两个必经之处**：`SafeJSONResponse.wire_safe`（写出 bytes 的那一刻）
    与路由层 `_wire_exit_gate`（FastAPI 在响应类之前还会自己序列化一遍，故端点返回值也得先过它，
    见那里的说明）。**没有任何端点自己处理非有限数**——计划原文在 `list_trades` 里手写的
    `_is_nan`（只认 `nan` 不认 `inf`，且只覆盖一个端点，而 `get_run` / `equity` / `positions` /
    `chart` 四个端点全裸奔）已删除，不留两套机制。
    """
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {k: _json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    if isinstance(v, (str, int, bool)) or v is None:
        return v
    # numpy 标量等：`.item()` 给回 Python 原生标量；拿不到就退回 str，绝不抛。
    item = getattr(v, "item", None)
    if callable(item):
        try:
            return _json_safe(item())
        except (TypeError, ValueError):
            pass
    return str(v)


class SafeJSONResponse(JSONResponse):
    """出口的网：保证**任何**响应都不会因非有限数或非原生标量而 500。

    它是"什么值可以上线"的**唯一**所有者（`wire_safe`）。两处都从它取：

      · `render` —— 真正写出 bytes 的那一刻；
      · 路由层（见 `_wire_exit_gate`）—— FastAPI 在构造响应时会**先自己序列化一遍**
        （`fastapi.routing.serialize_response`），那一步在 `render` **之前**，
        且**无法**从响应类覆盖。所以端点返回值必须先过同一道 `wire_safe`。
    """

    @staticmethod
    def wire_safe(content: Any) -> Any:
        """把 payload 变成**可以上线**的形态：非有限数 → `None`，numpy 标量 → 原生标量。"""
        return _json_safe(content)

    def render(self, content: Any) -> bytes:
        return super().render(self.wire_safe(content))


def _app_exit_class(app: FastAPI) -> type[Response]:
    """`app` 的出口响应类 = `default_response_class` 的实值。"""
    declared = app.router.default_response_class
    return declared.value if isinstance(declared, DefaultPlaceholder) else declared


def _wire_safe_endpoint(endpoint: Callable[..., Any],
                        wire_safe: Callable[[Any], Any] | None) -> Callable[..., Any]:
    """把端点的**返回值**先过一遍线规（`Response` 实例原样放行）。

    ⚠️ **为什么这道网必须落在端点返回值上，而不能只落在响应类上**（本会话实测，
    FastAPI 0.135 + pydantic 2.12）：

    `fastapi/routing.py` 在把端点返回值交给响应类**之前**，一定会自己序列化一次——

    | 情形 | FastAPI 先做什么 | `np.int64(7)` 的结果 |
    |---|---|---|
    | 有返回标注 + 默认响应类 | pydantic `dump_json`（Rust 核心直出 bytes） | `PydanticSerializationError` → **500** |
    | 有返回标注 + 显式响应类 | `field.serialize`（python 模式） | `PydanticSerializationError` → **500** |
    | 无返回标注 | `jsonable_encoder` | `ValueError` → **500** |

    三条路都在 `SafeJSONResponse.render` **之前**，所以"只把闸装在响应类上"是装不上、
    也抓不到的——`render` 根本没被走到。**闸必须在 FastAPI 那一遍序列化之前落地**，
    也就是这里：端点返回值的唯一出口。

    （float `NaN`/`Inf` 在第一条路上会被 pydantic 悄悄写成 `null`，所以那种接法
    "看起来没炸"是**运气**：它只对 pydantic 恰好认识的值成立。`np.int64` 就是反例。）
    """
    if wire_safe is None:      # 出口类不懂线规：原样放行 —— 结果是 500，不是坏 JSON
        return endpoint

    if inspect.iscoroutinefunction(endpoint):
        @functools.wraps(endpoint)
        async def _async(*args, **kwargs):
            result = await endpoint(*args, **kwargs)
            return result if isinstance(result, Response) else wire_safe(result)

        return _async

    @functools.wraps(endpoint)
    def _sync(*args, **kwargs):
        result = endpoint(*args, **kwargs)
        return result if isinstance(result, Response) else wire_safe(result)

    return _sync


def _wire_exit_gate(app: FastAPI) -> None:
    """把出口的网接到 `app` 的**每一条** JSON 路由上（唯一一条接线）。

    出口响应类与它的线规都取自 `app.router.default_response_class` —— **单一来源**：
    改掉那一处，整道闸就没了（`tests/test_web_app_api.py` 的变异实验正是打这里）。

    每条路由做三件事，缺一不可：
      1. **端点返回值先过 `exit_class.wire_safe`** —— 见 `_wire_safe_endpoint`：
         FastAPI 自己那遍序列化在响应类之前，闸不提前落地就等于没装；
      2. **显式带出口响应类** —— `APIRoute` 若留着默认占位符，FastAPI 会走
         `dump_json` 快路径（pydantic 直出 bytes），响应类同样不会被走到；
      3. **`response_model=None`** —— 关掉 pydantic 的响应模型（它默认取自返回标注
         `-> dict[str, Any]`，对 `Any` 里的 numpy 标量同样会抛）。
    """
    exit_class = _app_exit_class(app)
    wire_safe = getattr(exit_class, "wire_safe", None)

    class _SafeRoute(APIRoute):
        def __init__(self, *args, **kwargs):
            # `add_api_route` 总是以关键字传这几个参数；若哪天不是，就**响亮地**失败，
            # 而不是悄悄退化成"闸没装上"。
            if "endpoint" not in kwargs:
                raise RuntimeError("SafeRoute 必须收到关键字 endpoint（FastAPI 接口变了？）")
            kwargs["endpoint"] = _wire_safe_endpoint(kwargs["endpoint"], wire_safe)
            # 只在路由**没有自己指定**时才钉（显式指定者意图明确，不动它）。
            if isinstance(kwargs.get("response_class"), DefaultPlaceholder):
                kwargs["response_class"] = exit_class
            if isinstance(kwargs.get("response_model"), DefaultPlaceholder):
                kwargs["response_model"] = None
            super().__init__(*args, **kwargs)

    app.router.route_class = _SafeRoute


def _assert_no_route_bypasses_the_gate(app: FastAPI) -> None:
    """自检：没有哪条 API 路由还带着占位符响应类或响应模型字段（那就等于绕过出口的网）。

    与其等某个 `NaN` / numpy 标量在线上 500，不如在应用构造时就炸——**闸要能被证明存在**。
    """
    leaked = [
        r.path for r in app.router.routes
        if isinstance(r, APIRoute)
        and (isinstance(r.response_class, DefaultPlaceholder) or r.response_field is not None)
    ]
    if leaked:
        raise RuntimeError(
            "这些路由绕过了出口的网（响应类仍是默认占位符，或仍有响应模型字段——"
            f"FastAPI 会在 `SafeJSONResponse.render` 之前先自己 pydantic 序列化一遍）：{leaked}"
        )


def _param_defaults(engine: str, preset: str, overrides: dict[str, Any]) -> dict[str, Any]:
    """这次运行**改掉的那些键**，在预设里的原值。

    为什么需要：结果页要显示"这次运行改了什么"（聚宽的结果页会列出参数），
    只给新值的话，用户看到 `tp_pct = 0.3` 却不知道预设原本是 0.08 ——
    而**同一个键改一改就是一次新的试验**（§5），原值是判断"改了多少"的依据。

    只取**被改动的键**，不给整份预设：101 个预设 × 全部参数没有意义，
    而结果页要的是"这次动过什么"。
    """
    if not overrides:
        return {}
    from web.catalog import all_presets

    preset_values = all_presets().get(engine, {}).get(preset, {})
    return {k: preset_values.get(k) for k in overrides}


def create_app() -> FastAPI:
    # 测试缝不许出现在服务进程里（§0 fail-fast）：
    # 设了它每个作业都会跳过真实回测、返回空的 done 结果，而结果页上看不出区别。
    jobs_mod.assert_no_test_seam()
    app = FastAPI(title="hiagent 策略回测平台", default_response_class=SafeJSONResponse)
    _wire_exit_gate(app)          # ⚠️ 必须在**注册任何路由之前**——它决定路由的出口类

    @app.get("/api/catalog")
    def catalog() -> dict[str, Any]:
        presets = all_presets()
        out_presets = []
        for engine in ENGINES:
            for name in sorted(presets[engine]):
                sp = split_params(engine, name)
                out_presets.append({
                    "engine": engine, "preset": name,
                    "tunable": sp["tunable"],
                    "declarations": sp["declarations"],
                    "metadata": sp["metadata"],
                    "declared_n_comparisons": sp["declarations"].get("n_comparisons"),
                    "manual_trials": distinct_manual_configs(engine, name),
                    "run_count": count_trials(engine, name),
                })
        return {
            "engines": [{"name": e, "preset_count": len(presets[e])} for e in ENGINES],
            "presets": out_presets,
            # 指标表的渲染元数据（中文标签 + 类型），**单一来源**。
            # 放在 catalog 里是因为它随预设一起、页面加载时取一次即可；
            # 前端**不再自己写一份**标签表——两份必然会漂移，而且漂移的表现是
            # "某一格格式不对"，不会有人注意到。
            # 引擎口径说明：随 catalog 一起下发，界面按运行的引擎取用
        "engine_notes": dict(ENGINE_NOTES),
        "metric_meta": {
                k: {"label": METRIC_LABELS[k], "kind": METRIC_KINDS[k]}
                for k in CANONICAL_KEYS
            },
            # 交易明细的**中文列名与平仓原因中文值** —— 与 `metric_meta` 同一个模式。
            # 没有它，页面上指标表是中文、表头是英文（实测截图确认过）。
            "trade_meta": {
                "labels": dict(TRADE_LABELS),
                "exit_reasons": dict(EXIT_REASON_LABELS),
            },
        }

    @app.post("/api/runs")
    def create_run(req: RunRequest) -> dict[str, Any]:
        """提交一次回测。**校验必须在提交前做**——见下方 ⚠️。"""
        if req.start > req.end:
            raise HTTPException(400, detail=f"start {req.start} is after end {req.end}")
        if req.engine not in ENGINES:
            raise HTTPException(404, detail=f"unknown engine: {req.engine}")
        if req.preset not in all_presets().get(req.engine, {}):
            raise HTTPException(404, detail=f"unknown preset: {req.preset}")
        if req.mode not in VALID_MODES:
            raise HTTPException(400, detail=f"unknown mode: {req.mode}")
        # ⚠️ **`jobs.submit` 不校验 overrides**：它只入队，校验发生在**子进程**里的
        # `runners.run`。若把校验留给那条路径，一次 `{"nope": 1}` 会先拿到 200 + run_id，
        # 再在几秒后变成 status=failed —— 用户以为提交成功了。
        # 故在边界处（唯一能看到请求的地方）先校验：错就 400，不入队。
        try:
            validate_overrides(req.engine, req.preset, req.overrides)
        except OverrideError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        run_id = jobs_mod.submit(req.engine, req.preset, req.overrides,
                                 req.start, req.end, req.mode)
        return {"run_id": run_id}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        """内存优先；**服务重启后回退到磁盘**，所以历史不必依赖进程存活。"""
        job = jobs_mod.get(run_id)
        if job is None:
            hist = jobs_mod.load_persisted(run_id)
            meta0 = jobs_mod.meta_persisted(run_id)
            outcome = jobs_mod.outcome_persisted(run_id)
            if hist is None and not jobs_mod.run_exists(run_id):
                raise HTTPException(404, detail=f"unknown run: {run_id}")
            if hist is None:
                # **失败的运行没有 result.json** —— 但它存在，而且原因就在 outcome.json 里。
                # 旧实现在这里直接 404，于是重启后**看不到它为什么失败**（实测）。
                #
                # ⚠️ **没有 outcome.json 时状态是 `unknown`，不是 `failed`。**
                # 进程在运行中被杀（服务崩了 / 机器重启）时，磁盘上只剩 `job.json`——
                # 平台**并不知道**那次运行最后怎么了。报 `failed` 是在编一个拿不到的事实，
                # 而用户会据此去找一个并不存在的错误原因。pessimistic 不等于"编一个坏结局"。
                return {"run_id": run_id,
                        "engine": (meta0 or {}).get("engine"), "preset": (meta0 or {}).get("preset"),
                        "status": (outcome or {}).get("status") or "unknown",
                        "error": (outcome or {}).get("error"),
                        "mode": (meta0 or {}).get("mode"),
                        "start": (meta0 or {}).get("start"), "end": (meta0 or {}).get("end"),
                        "trial_no": (meta0 or {}).get("trial_no"),
                        # 覆盖值只在 `job.json` 里（`result.json` 不存它）——
                        # 不带回来的话，重启后打开一次运行就看不出它当时改了什么。
                        "overrides": (meta0 or {}).get("overrides") or {},
                        "param_defaults": _param_defaults(
                            (meta0 or {}).get("engine"), (meta0 or {}).get("preset"),
                            (meta0 or {}).get("overrides") or {}),
                        "metrics": None, "queue_position": None, "from_disk": True}
            # ⚠️ **`mode` 与 `trial_no` 要从落盘的 `job.json` 取，不能写死 None。**
            # 写死的后果实测过：服务重启后打开一次 **preview** 运行，`job.mode` 是 null，
            # 前端就不挂"非可比"横幅（设计要求 preview 结果**强制标注非可比**）——
            # 于是那些数字看上去像全量回测的，而它们其实只覆盖了最近 90 天。
            # 这类"标签在重启后消失"的缺陷，静态契约测试看不见：两条路径都返回 200。
            meta = jobs_mod.meta_persisted(run_id) or {}
            return {"run_id": run_id, "engine": hist.engine, "preset": hist.preset,
                    "status": "done", "error": None,
                    "mode": meta.get("mode"),
                    "start": hist.start, "end": hist.end,
                    "trial_no": meta.get("trial_no"),
                    # 覆盖值只在 `job.json` 里（`result.json` 不存它）
                    "overrides": meta.get("overrides") or {},
                    "param_defaults": _param_defaults(hist.engine, hist.preset,
                                                      meta.get("overrides") or {}),
                    "metrics": window_metrics(hist), "queue_position": None,
                    "from_disk": True}
        metrics = job.result.metrics if job.result else None
        return {
            "run_id": job.run_id, "engine": job.engine, "preset": job.preset,
            "status": job.status, "error": job.error, "mode": job.mode,
            "start": job.start, "end": job.end,
            "overrides": dict(job.overrides or {}),
            "param_defaults": _param_defaults(job.engine, job.preset,
                                              dict(job.overrides or {})),
            "trial_no": job.trial_no,
            # 指标按**请求窗口**算（与 `/equity` 的曲线同源）—— 见 `window_metrics` 的说明。
              "metrics": window_metrics(job.result) if job.result else None,
            # 单 worker 下"前面还有几个"是用户唯一能看到的等待依据
            "queue_position": jobs_mod.queue_position(run_id),
            "from_disk": False,
        }

    @app.post("/api/runs/{run_id}/cancel")
    def cancel_run(run_id: str) -> dict[str, Any]:
        """取消一个作业：排队中的会被跳过，运行中的会被 terminate（见 jobs.cancel）。"""
        try:
            status = jobs_mod.cancel(run_id)
        except KeyError:
            raise HTTPException(404, detail=f"unknown run: {run_id}") from None
        return {"run_id": run_id, "status": status}

    @app.get("/api/configs")
    def list_configs() -> dict[str, Any]:
        from web.configs import list_configs as _list

        return {"configs": _list()}

    @app.post("/api/configs")
    def save_config(req: ConfigRequest) -> dict[str, Any]:
        """保存命名配置。**存之前先校验**——存一个跑不起来的配置没有意义。"""
        from web.configs import save_config as _save

        if not req.name.strip() or "/" in req.name:
            raise HTTPException(400, detail="配置名不能为空、也不能含 '/'（它是 URL 路径的一段）")
        try:
            validate_overrides(req.engine, req.preset, req.overrides)
        except OverrideError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, detail=str(exc)) from exc
        return _save(name=req.name.strip(), engine=req.engine, preset=req.preset,
                     overrides=req.overrides, note=req.note)

    @app.delete("/api/configs/{name}")
    def delete_config(name: str) -> dict[str, Any]:
        from web.configs import delete_config as _del

        try:
            _del(name)
        except KeyError:
            raise HTTPException(404, detail=f"unknown config: {name}") from None
        return {"deleted": name}

    @app.post("/api/configs/{name}/duplicate")
    def duplicate_config(name: str, body: dict[str, Any]) -> dict[str, Any]:
        from web.configs import duplicate_config as _dup

        try:
            return _dup(name, str(body.get("new_name") or f"{name} 副本"))
        except KeyError:
            raise HTTPException(404, detail=f"unknown config: {name}") from None

    @app.get("/api/runs")
    def list_runs(limit: int = 50) -> dict[str, Any]:
        """最近的运行历史（倒序）。服务重启后 `status` 为 null，但 `has_result` 仍为真。

        每条**带上该次运行的指标**（`window_metrics`，按它自己的请求窗口算）。
        为什么：聚宽的「我的回测」列表里每条直接显示收益 —— 没有它，
        用户得把每一次运行都点开才知道哪个好，而"看出哪个更好"正是这个平台存在的理由。
        只在 `has_result` 时读盘算，被取消/失败的那些不付这个代价。
        """
        rows = jobs_mod.list_runs(limit=max(1, min(limit, 500)))
        for r in rows:
            if not r.get("has_result"):
                r["metrics"] = None
                continue
            result = jobs_mod.load_persisted(r["run_id"])
            r["metrics"] = window_metrics(result) if result is not None else None
        return {"runs": rows}

    # ⚠️ 路径**不能**写成 `/api/runs/compare`——它会被 `/api/runs/{run_id}` 抢先匹配，
    # 于是 run_id="compare" 并返回 404。放 `/api/compare` 才无歧义。
    @app.get("/api/compare")
    def compare(ids: str) -> dict[str, Any]:
        """并排比较若干历史运行（`?ids=a,b,c`）。**不重跑回测**——结果来自磁盘。

        这正是本平台存在的理由：改了参数之后，得能看出**哪个更好**。
        指标一律经 `window_metrics` 按**请求窗口**算，缺的补 `None`（不是 0）。
        """
        rows = []
        for rid in [s for s in ids.split(",") if s]:
            job = jobs_mod.get(rid)
            result = (job.result if (job and job.result) else None) or jobs_mod.load_persisted(rid)
            if result is None:
                continue
            # ⚠️ **`mode` 必须带上** —— 没有它，前端判不出"preview 与 full 混着比"
            # 这种不可比（preview 的数字设计文档明令"不得作为业绩依据、
            # 不可与 full 比较"）。实测：原先 `x.mode` 在前端是 `undefined`，
            # 于是那一类不可比**静默通过**。
            # 与 `get_run` 同一套取法：内存优先、磁盘兜底。
            meta = jobs_mod.meta_persisted(rid) or {}
            rows.append({
                "run_id": rid, "engine": result.engine, "preset": result.preset,
                "overrides": (job.overrides if job else {}),
                "start": result.start, "end": result.end,
                "mode": (job.mode if job else None) or meta.get("mode"),
                "metrics": window_metrics(result),
            })
        if not rows:
            raise HTTPException(404, detail=f"no persisted results for ids={ids}")
        return {"keys": list(CANONICAL_KEYS), "rows": rows}

    @app.get("/api/runs/{run_id}/export/trades.csv")
    def export_trades(run_id: str) -> Response:
        """导出成交明细为 CSV（14 列规范顺序，取自 core/trade_schema.py 这个单源）。"""
        import csv
        import io

        from core.trade_schema import TRADE_COLS

        result = _load_result(run_id)
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(TRADE_COLS), extrasaction="ignore")
        w.writeheader()
        # 非有限数写成**空单元格**，不是字面量 `nan`：§0 要求"这个数没有意义"与
        # "这个数是 0"可区分，而 `nan` 在 CSV 里既不是数字也不是空——是一句谎。
        # 导出与页面上的交易表**同一份列表**（按窗口切）——导出比表格多出
        # 窗口外的成交，用户会以为导错了。
        for row in window_trades(result.trades, result.start, result.end):
            w.writerow({k: _json_safe(v) for k, v in row.items()})
        return Response(content=buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{run_id}_trades.csv"'})

    @app.get("/api/runs/{run_id}/export/metrics.json")
    def export_metrics(run_id: str) -> Response:
        """导出该次运行的规范指标（与页面上看到的是同一组键）。"""
        result = _load_result(run_id)
        # `_json_safe` 而不是 `default=str`：后者会把 `Infinity` 静默写成**字符串**，
        # 产出一个既非法 JSON 又骗人的 metrics.json（Global Constraints）。
        body = json.dumps(_json_safe({
            "run_id": run_id, "engine": result.engine, "preset": result.preset,
            "start": result.start, "end": result.end,
            "metrics": window_metrics(result),
        }), ensure_ascii=False, indent=2)
        return Response(content=body, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{run_id}_metrics.json"'})

    @app.get("/api/runs/{run_id}/equity")
    def equity(run_id: str) -> dict[str, Any]:
        """净值曲线 + 基准曲线 + 回撤 + 超额。**回测的头部图表**。

        ⚠️ 策略曲线必须**切到 `[start, end]`**：记录器的 `equity_curve` 覆盖的是
        **带缓冲的面板**（`[start-180d, end+60d]`，引擎不设 fromdate/todate）。
        不切就会把窗口外的行情画进曲线——Task 8 的口径错配是同一件事，
        那里的后果是 CAGR 与基准不同口径，这里的后果是**曲线比它自己的标签更长**。

        ⚠️ 超额收益的口径警告（会随响应一起返回，前端必须显示）：
        基准是等权**多头**篮子，而 short_reversal 是**空头**策略，故 `strategy - benchmark`
        **加上了方向性偏差**，在熊市被抬高——**不得当作 alpha**。
        """
        from hiagent_config import get_db_path

        from web.benchmark import BENCHMARK_LABEL, benchmark_return, benchmark_series

        result = _load_result(run_id)
        curve = result.metrics.get("equity_curve") or []
        # 窗口切片走 `metrics_view.window_slice` —— **唯一判据**。
        # 指标表也用同一个函数，两处各写一遍筛选条件就是各自漂移的起点。
        rows = window_slice(curve, result.start, result.end)
        if not rows:
            raise HTTPException(404, detail="this run has no in-window equity curve")
        base = float(rows[0]["equity"])
        if base <= 0:
            raise HTTPException(500, detail="equity curve starts at a non-positive value")
        strat = [{"date": str(r["date"])[:10], "value": float(r["equity"]) / base} for r in rows]

        peak, dd = -1.0, []
        for p in strat:
            peak = max(peak, p["value"])
            dd.append({"date": p["date"],
                       "value": (peak - p["value"]) / peak if peak > 0 else 0.0})

        bench = benchmark_series(get_db_path(), result.start, result.end)
        # 每日收益：在 **API 侧**由已切片的净值序列算（前端仍不做统计）
        prev, daily = None, []
        for p in strat:
            if prev is not None and prev > 0:
                daily.append({"date": p["date"], "value": p["value"] / prev - 1.0})
            prev = p["value"]

        b_ret = benchmark_return(bench)
        s_ret = strat[-1]["value"] - 1.0
        return {
            "strategy": strat,
            "benchmark": bench,
            "benchmark_label": BENCHMARK_LABEL,     # 界面必须如实显示它不是指数
            "drawdown": dd,
            "daily_returns": daily,
            # 年度收益：**同一份窗口切片**的曲线（`rows` 就是上面 `strat` 的来源），
            # 所以它天然可加 —— 复利回去必须等于 `strategy_return`。
            # 聚宽的结果页有这张表，它回答"收益是不是全靠某一年"这个决策问题。
            "periods": {
                "unit": "year",
                "rows": period_returns(rows, "year"),
                # 首尾年份被窗口切过，**必须如实说**，不能让它们看起来是整年。
                "caveat": "按自然年切分。「区间」是该年实际覆盖的交易日："
                "中间年份是整年，首尾年份由回测窗口切出（可能只有几天）。",
            },
            "strategy_return": s_ret,
            "benchmark_return": b_ret,              # 无基准数据时是 None，**不是 0**
            "excess_return": (s_ret - b_ret) if b_ret is not None else None,
            "excess_caveat": (
                "超额 = 策略 − 基准。基准是等权多头篮子而该策略是空头，"
                "故此值含方向性偏差、在熊市被抬高，不得当作 alpha。"
            ),
        }

    @app.get("/api/runs/{run_id}/positions")
    def positions(run_id: str) -> dict[str, Any]:
        """每日持仓。**从成交列表推导——引擎不记录逐日持仓，但成交列表已蕴含它。**

        一笔交易在 `[entry_date, exit_date)` 期间占用仓位（退出当日已平，故不含）。
        对 `max_positions=1` 的 short_reversal 每天至多一条；多头多仓则是并集。

        「窗口内的交易日」**取自该运行的净值曲线**，与上方图表完全同步——
        不另算一套日历，免得表与图对不上。无仓位的那天 `holdings` 是**空列表**：
        **空 ≠ 缺**，前端要显示"空仓"而不是空白。
        """
        result = _load_result(run_id)
        # ⚠️ 这里**故意用全部成交**，不按窗口切。
        # 每日持仓要回答的是"窗口内某天我持有什么"——而一个**在窗口之前建仓、
        # 窗口内仍持有**的仓位**确实该被算进去**（你确实持有它）。
        # 切掉它会凭空少报持仓。（交易**明细表**与**图表下标**才按窗口切，
        # 见 `window_trades` 的说明。）
        trades = _sorted_trades(result.trades)
        curve = result.metrics.get("equity_curve") or []
        days = [str(r["date"])[:10] for r in curve
                if r.get("date") is not None
                and result.start <= str(r["date"])[:10] <= result.end]
        rows = []
        for day in days:
            held = [t for t in trades
                    if str(t.get("entry_date"))[:10] <= day < str(t.get("exit_date"))[:10]]
            rows.append({
                "date": day,
                "count": len(held),
                "holdings": [{"thscode": t["thscode"],
                              "entry_date": str(t["entry_date"])[:10],
                              "entry_price": t["entry_price"],
                              "size": t["size"]} for t in held],
            })
        return {"rows": rows}

    @app.get("/api/runs/{run_id}/log")
    def run_log(run_id: str, offset: int = 0) -> dict[str, Any]:
        """**增量**读运行日志：`offset` 是客户端**已读到的字符数**，返回新的一段。

        增量而不是整份，是因为回测会持续打印，整份重传会随运行变长而越来越贵。
        作业不在内存里（服务重启过）时视为已结束。

        ⚠️ **`offset` 的单位是字符，不是字节。** 原实现返回 `len(data)`（**字节**）
        却把 `text` 解码成**字符串**发出去 —— 中文一个字 3 字节，于是
        `offset≠len(text)`（实测一次 20 行的日志：offset=470、len(text)=310），
        而服务端按**字节**切 `data[offset:]`：落在**字符中间**时
        `errors="replace"` 把半个字变成 `�` —— **不报错，只是静默改字**。
        前端今天侥幸没事（它只用服务端发回的 offset，那总是落在边界上），
        但"发字符、收字节"这个契约自相矛盾，读代码的人看不出来。
        既然每次都读整份文件，按字符切**不额外多读一个字节**，就按字符切。

        不变量（可断言）：`offset - 上次的 offset == len(本次 text)`。
        """
        job = jobs_mod.get(run_id)
        # ⚠️ 运行"存在"的判据**不能是"内存里有作业 或 有 result.json"** ——
        # `result.json` 只在**成功**时落盘，而一次**失败**的运行在磁盘上只有
        # `job.json` + `run.log`。旧判据让重启后的失败运行在 `/log` 上返回 404（实测），
        # **而那恰恰是最需要看日志的时候**：说明原因的日志就在磁盘上。
        if job is None and not jobs_mod.run_exists(run_id):
            raise HTTPException(404, detail=f"unknown run: {run_id}")
        p = run_artifact(run_id, "run.log")
        if not p.exists():
            return {"text": "", "offset": 0, "done": True}
        text = p.read_text(encoding="utf-8", errors="replace")
        # 偏移越过文件尾 = 客户端的窗口已经不在了（日志被替换/截断）。**从头重发**，
        # 而不是回一段空字符串 —— 空的会让界面**永久停在空白**，且不报错。
        # （本平台只追加不截断，所以这条是防御性的；用一条测试把它钉住。）
        if offset < 0 or offset > len(text):
            offset = 0
        return {
            "text": text[offset:],
            "offset": len(text),
            "done": job is None or job.status in {"done", "failed", "cancelled"},
        }

    @app.get("/api/runs/{run_id}/trades")
    def list_trades(run_id: str) -> dict[str, Any]:
        # `jobs_mod.resolve`：**内存优先、磁盘兜底**。原先这里只查 `_JOBS`，
        # 于是服务一重启，历史里的运行点进来就是 404 —— 而 `/api/runs/{id}`
        # 与 `/equity`、`/export/*` 都能从磁盘读回，界面因此自相矛盾
        #（头部说 done，交易表与 K 线却是空的）。
        got = jobs_mod.resolve(run_id)
        if got is None:
            raise HTTPException(404, detail=f"unknown run: {run_id}")
        meta, result = got
        # 与指标表、与图表的下标**同一份列表**（见 `window_trades` 的说明）。
        rows = _sorted_trades(window_trades(result.trades, result.start, result.end))
        params = _effective_params(meta)
        # 去掉 `net`：它是 short_reversal 额外的"每笔净收益率"，**与规范列
        # `net_return` 是同一件事**（实测只差 1.1e-06，手续费口径的末位），
        # 而且**只有这一个引擎会产生** —— 于是表里多出一列与「净收益率」几乎一样的数，
        # 用户只会去猜"这两个哪个算数"。
        # 14 列规范（`core/trade_schema.py`）是单一来源（§6），引擎的额外字段
        # 不该在平台表里另起一列。
        # ⚠️ 去掉的是**列**（每个行字典里的那个键），不是**行** ——
        # 写成 `if "net" not in t` 会把整行过滤掉，`columns` 于是变成空列表
        # （实测踩过：单元测试的假成交没有 `net` 字段，所以没抓出来；
        #   是在真服务上核对列名时才发现的）。
        engineered = [_with_exit_levels(i, {k: v for k, v in t.items() if k != "net"},
                                        meta["engine"], params)
                      for i, t in enumerate(rows)]
        return {
            "total": len(rows),
            # 非有限数由出口的 `SafeJSONResponse` 统一处理（原先这里手写 `_is_nan`，
            # 只认 `nan` 不认 `inf`，且只覆盖这一个端点——已删除，见 `_json_safe` 的说明）。
            "rows": engineered,
            # 列名从**实际返回的行**里取（而不是从 14 列 schema 里取），
            # 这样新增的 sl_price / tp_price 会自动出现在前端表头里，不会表里有值而没列。
            "columns": list(engineered[0]) if engineered else [],
        }

    @app.get("/api/runs/{run_id}/trades/{i}/chart")
    def trade_chart(run_id: str, i: int) -> dict[str, Any]:
        got = jobs_mod.resolve(run_id)
        if got is None:
            raise HTTPException(404, detail=f"unknown run: {run_id}")
        meta, result = got
        rows = _sorted_trades(window_trades(result.trades, result.start, result.end))
        if not (0 <= i < len(rows)):
            raise HTTPException(404, detail=f"trade index {i} out of range (0..{len(rows) - 1})")
        from hiagent_config import get_db_path

        # 与 `/trades` 的 SL/TP 推导走**同一个** `_effective_params`——
        # 两处各拼一遍 `split_params + update(overrides)` 是漂移的经典起点。
        return chart_payload(meta["engine"], _effective_params(meta), rows[i], get_db_path())

    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    _assert_no_route_bypasses_the_gate(app)
    return app


app = create_app()


def main() -> None:
    import uvicorn

    # 只绑本机（设计文档 D2 / Global Constraints）
    uvicorn.run(create_app(), host=BIND_HOST, port=BIND_PORT)


if __name__ == "__main__":
    main()
