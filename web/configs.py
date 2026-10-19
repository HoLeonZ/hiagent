"""命名配置：给「某预设 + 某组改动」起个名字，存下来、可载入、可复制。

对标聚宽的「我的策略」——但聚宽保存的是**策略源码**，本仓库的策略是**参数化的预设**，
故对应物是「命名的一组参数改动」。

## 为什么同时存 delta 和快照（§0）
`overrides` 是相对预设默认值的**改动**（与账本 `param_diff`、前端 `changedOverrides` 同一口径），
载入时直接回填表单。**但只有 delta 是不够的**：预设本身也会变，那时"同一个配置"会跑出
不同的参数，而用户以为在复现——这是 §0 的可复现性问题。

故同时存 `effective`（保存当时的完整参数向量）与 `preset_fingerprint`（预设本身的指纹）。
载入时指纹不符就如实回 `preset_drifted: true`：**不静默、也不阻断**——
delta 仍然有意义，只是它挂靠的基准变了，用户需要知道。

## 与 §5 的关系
一个命名配置**不**自动等于一次试验：§5 数的是**试过的不同参数向量**。
运行一个配置仍走 `distinct_manual_configs` 的去重口径，所以反复跑同一个配置不会被重复计数。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any

from web.state import assert_state_writable, state_home

CONFIGS_FILE = "configs.json"


def _path():
    assert_state_writable()          # 与 trials 同一个闸；别各写各的
    p = state_home() / CONFIGS_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _read() -> dict[str, dict[str, Any]]:
    p = _path()
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8") or "{}")


def _write(data: dict[str, dict[str, Any]]) -> None:
    _path().write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _preset_params(engine: str, preset: str) -> dict[str, Any]:
    """取预设的当前参数。抽成函数是为了让测试能模拟"预设被改过"。"""
    from web.catalog import all_presets

    return dict(all_presets()[engine][preset])


def _fingerprint(params: dict[str, Any]) -> str:
    canon = json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def save_config(*, name: str, engine: str, preset: str,
                overrides: dict[str, Any], note: str = "") -> dict[str, Any]:
    """新建或覆写一个命名配置。覆写**保留** `created_at`。"""
    params = _preset_params(engine, preset)
    effective = {**params, **overrides}
    now = dt.datetime.now().isoformat(timespec="seconds")
    data = _read()
    prev = data.get(name)
    rec = {
        "name": name, "engine": engine, "preset": preset,
        "overrides": dict(overrides),
        "effective": effective,
        "preset_fingerprint": _fingerprint(params),
        "note": note,
        "created_at": (prev or {}).get("created_at", now),
        "updated_at": now,
    }
    data[name] = rec
    _write(data)
    return {**rec, "preset_drifted": False}


def get_config(name: str) -> dict[str, Any]:
    """取一个配置；**顺带算出它挂靠的预设有没有漂移**。"""
    data = _read()
    if name not in data:
        raise KeyError(name)
    rec = dict(data[name])
    current = _preset_params(rec["engine"], rec["preset"])
    rec["preset_drifted"] = _fingerprint(current) != rec["preset_fingerprint"]
    return rec


def list_configs() -> list[dict[str, Any]]:
    """全部配置，按名字排序；每个都带 `preset_drifted`。"""
    return [get_config(n) for n in sorted(_read())]


def delete_config(name: str) -> None:
    data = _read()
    if name not in data:
        raise KeyError(name)
    del data[name]
    _write(data)


def duplicate_config(src: str, new_name: str) -> dict[str, Any]:
    """复制一个配置到新名字（对标聚宽的"复制策略"）。"""
    rec = get_config(src)
    return save_config(name=new_name, engine=rec["engine"], preset=rec["preset"],
                       overrides=rec["overrides"], note=rec["note"])
