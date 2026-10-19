"""命名配置：保存、载入、复制、删除，以及**预设漂移**的如实上报。"""
from __future__ import annotations

import pytest

from web import configs as cfg


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setenv("HIAGENT_PLATFORM_HOME", str(tmp_path))
    return tmp_path


def test_save_then_list_then_get(home):
    cfg.save_config(name="紧止损", engine="short_reversal", preset="v50_slope",
                    overrides={"sl_pct": 0.01}, note="试验")
    names = [c["name"] for c in cfg.list_configs()]
    assert names == ["紧止损"]
    got = cfg.get_config("紧止损")
    assert got["overrides"] == {"sl_pct": 0.01}
    assert got["engine"] == "short_reversal" and got["preset"] == "v50_slope"


def test_saving_the_same_name_overwrites_and_keeps_created_at(home):
    first = cfg.save_config(name="A", engine="short_reversal", preset="v50_slope",
                            overrides={"sl_pct": 0.01})
    second = cfg.save_config(name="A", engine="short_reversal", preset="v50_slope",
                             overrides={"sl_pct": 0.02})
    assert cfg.get_config("A")["overrides"] == {"sl_pct": 0.02}
    assert second["created_at"] == first["created_at"], "覆写不应重置 created_at"


def test_the_config_records_a_snapshot_and_a_preset_fingerprint(home):
    """只有 delta 是不够的——预设变了，"同一个配置"就跑出不同参数（§0）。"""
    c = cfg.save_config(name="B", engine="short_reversal", preset="v50_slope",
                        overrides={"sl_pct": 0.01})
    assert c["preset_fingerprint"], "必须记下保存当时预设的指纹"
    assert c["effective"]["sl_pct"] == 0.01, "快照必须是**生效后**的参数"
    # 快照里也应有未被改动的键（它存的不是 delta）
    assert "tp_pct" in c["effective"]


def test_no_drift_when_the_preset_is_unchanged(home):
    cfg.save_config(name="C", engine="short_reversal", preset="v50_slope",
                    overrides={"sl_pct": 0.01})
    assert cfg.get_config("C")["preset_drifted"] is False


def test_drift_is_reported_when_the_preset_changed(home, monkeypatch):
    """把预设本身改掉（模拟仓库里改了 presets.py），载入时必须如实报漂移。"""
    cfg.save_config(name="D", engine="short_reversal", preset="v50_slope",
                    overrides={"sl_pct": 0.01})
    real = cfg._preset_params

    def mutated(engine, preset):
        p = dict(real(engine, preset))
        p["tp_pct"] = 0.999          # 预设本身变了
        return p

    monkeypatch.setattr(cfg, "_preset_params", mutated)
    got = cfg.get_config("D")
    assert got["preset_drifted"] is True, "预设变了却报无漂移——用户在以为复现，其实没有"
    assert got["overrides"] == {"sl_pct": 0.01}, "漂移不改动 delta 本身"


def test_duplicate_copies_the_parameters_under_a_new_name(home):
    cfg.save_config(name="原", engine="short_reversal", preset="v50_slope",
                    overrides={"sl_pct": 0.01}, note="n")
    dup = cfg.duplicate_config("原", "副本")
    assert dup["name"] == "副本" and dup["overrides"] == {"sl_pct": 0.01}
    assert dup["preset"] == "v50_slope" and dup["note"] == "n"
    assert [c["name"] for c in cfg.list_configs()] == ["副本", "原"]


def test_delete_removes_it(home):
    cfg.save_config(name="走", engine="short_reversal", preset="v50_slope", overrides={})
    cfg.delete_config("走")
    assert cfg.list_configs() == []


def test_unknown_name_raises_keyerror(home):
    with pytest.raises(KeyError):
        cfg.get_config("不存在")
