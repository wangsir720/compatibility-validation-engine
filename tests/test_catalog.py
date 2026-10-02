# -*- coding: utf-8 -*-
"""catalog 模块测试 —— 重点验证「缺数据不猜」与「冲突不静默消解」两条纪律。"""
import pytest

from src import catalog
from src.catalog import CatalogError, load_cpus, load_dcus, load_models, load_scenario, load_swstack


def test_all_catalogs_load_with_required_fields():
    for cat in (load_cpus(), load_dcus(), load_models(), load_swstack()):
        assert cat.rows, "%s 目录为空" % cat.kind
        for r in cat.rows:
            assert r.source_id, "%s 缺 source_id" % r.key
            assert r.credibility in ("official", "secondary", "unverified")


def test_missing_field_returns_none_not_zero():
    """空字段必须归一为 None，绝不能当 0 用 —— 0 是个具体数值，会污染下游计算。"""
    dcu = load_dcus()
    bw = dcu.get("BW100")
    assert bw.num("fp32_tflops") is None
    assert bw.num("vram_gib") == 64.0


def test_conflicts_are_detected_not_ignored():
    dcu = load_dcus()
    z100 = [c for c in dcu.conflicts if c["key"] == "Z100"]
    assert z100, "Z100 的 FP32 冲突必须被检出"
    c = z100[0]
    assert c["field"] == "fp32_tflops"
    assert len(c["values"]) >= 2
    assert c["resolution"] == "adopted_higher_credibility"
    assert c["action"]


def test_unresolved_conflicts_are_flagged():
    cpus = load_cpus()
    keys = {(c["key"], c["field"]) for c in cpus.conflicts}
    assert ("3490", "turbo_ghz") in keys, "3490 睿频冲突必须被检出"
    assert ("7480", "base_ghz") in keys, "7480 基础频率冲突必须被检出"
    for c in cpus.conflicts:
        assert c["resolution"] in ("adopted_higher_credibility", "unresolved")


def test_unknown_model_raises_with_available_list():
    with pytest.raises(CatalogError) as e:
        load_dcus().get("DCU-NOT-EXIST")
    assert "未收录" in str(e.value)


def test_duplicate_key_prefers_higher_credibility():
    cpus = load_cpus()
    idx = cpus.by_key()
    # 7490 两条均为 secondary，保留首条且不报错
    assert "7490" in idx
    assert idx["7490"].credibility == "secondary"


def test_dcu_supported_by_stack_respects_scope():
    stacks = catalog.dcu_supported_by_stack("K100-AI")
    versions = {s.get("version") for s in stacks}
    assert "rock-6.3" in versions, "K100-AI 应命中 rock-6.3 分支"
    for s in stacks:
        raw = (s.data.get("supports_dcu") or "")
        assert "K100-AI" in raw or raw.strip() == "全系列", \
            "K100-AI 不应匹配到仅支持其他型号的条目：%s" % raw


def test_missing_scenario_raises():
    with pytest.raises(CatalogError) as e:
        load_scenario("no-such")
    assert "可用场景" in str(e.value)


def test_scenarios_reference_known_models():
    models = load_models().by_key()
    for sid in catalog.list_scenarios():
        s = load_scenario(sid)
        assert s["workload"]["model_id"] in models, \
            "场景 %s 引用了未收录模型" % sid
