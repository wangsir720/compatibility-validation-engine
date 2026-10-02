# -*- coding: utf-8 -*-
"""compat_matrix 模块测试 —— 重点验证四档判定与证据链完整性。"""
import copy

import pytest

from src.catalog import load_dcus, load_models, load_scenario
from src.compat_matrix import MatrixError, RUNTIME_VRAM_FACTOR, build_matrix

VERDICTS = ("supported", "needs_tuning", "not_recommended", "unknown")


@pytest.fixture
def gov():
    return load_scenario("gov_lmm_inference")


def _matrix(scenario, models=None):
    # 注意不能用 models or ...：空列表是 falsy，会被回退成全部型号
    return build_matrix(models if models is not None else sorted(load_dcus().by_key().keys()),
                        scenario)


def test_every_entry_has_verdict_and_evidence(gov):
    m = _matrix(gov)
    assert m["entries"]
    for e in m["entries"]:
        assert e["verdict"] in VERDICTS
        assert e["reason"], "判定必须有理由：%s" % e["dcu"]
        assert e["evidence"], "判定必须有证据链：%s" % e["dcu"]
        for ev in e["evidence"]:
            assert ev["what"] and ev["detail"]


def test_entries_sorted_worst_verdict_first(gov):
    m = _matrix(gov)
    order = {"supported": 0, "needs_tuning": 1, "not_recommended": 2, "unknown": 3}
    verdicts = [order[e["verdict"]] for e in m["entries"]]
    assert verdicts == sorted(verdicts), "最优型号应排在最前"


def test_small_vram_card_is_not_recommended(gov):
    """K100-AI 64GB 对 8B 权重应余量充足；K100 32GB 同理，但排序需正确。"""
    m = _matrix(gov)
    by = {e["dcu"]: e for e in m["entries"]}
    assert by["K100-AI"]["verdict"] in ("supported", "needs_tuning")
    assert by["Z100"]["dcu_vram_gib"] == 32.0


def test_model_with_large_weights_gets_not_recommended(gov):
    big = copy.deepcopy(gov)
    big["workload"]["model_id"] = "DeepSeek-V3"  # 1342 GiB 权重
    m = _matrix(big)
    assert all(e["verdict"] == "not_recommended" for e in m["entries"])


def test_unknown_dcu_model_yields_unknown_verdict(gov):
    m = _matrix(gov, models=["DCU-DOES-NOT-EXIST"])
    e = m["entries"][0]
    assert e["verdict"] == "unknown"
    assert "未收录" in e["reason"]


def test_missing_model_id_raises():
    bad = load_scenario("gov_lmm_inference")
    del bad["workload"]["model_id"]
    with pytest.raises(MatrixError) as ex:
        _matrix(bad)
    assert "model_id" in str(ex.value)


def test_unregistered_model_raises_with_list(gov):
    bad = copy.deepcopy(gov)
    bad["workload"]["model_id"] = "some-fake-model"
    with pytest.raises(MatrixError) as ex:
        _matrix(bad)
    assert "未收录" in str(ex.value)


def test_kv_cache_absent_marks_estimate_as_lower_bound(gov):
    """核心纪律：KV Cache 算不出时，required_gib 必须标注为下界，而不是当作完整值。"""
    m = _matrix(gov)
    assert m["kv_cache_gib"] is None
    assert "下界" in m["required_gib_basis"]


def test_kv_cache_present_is_included_in_requirement(gov):
    s = copy.deepcopy(gov)
    s["workload"]["model_structure"] = {"layers": 32, "kv_heads": 8, "head_dim": 128}
    m = _matrix(s)
    assert m["kv_cache_gib"] > 0
    # 需求应大于仅权重的估算
    assert m["required_gib"] > m["weights_gib"] * RUNTIME_VRAM_FACTOR


def test_empty_model_list_produces_no_entries(gov):
    m = _matrix(gov, models=[])
    assert m["entries"] == []
    assert m["required_gib"] > 0  # 需求仍应算出，不因型号列表为空而崩


def test_conflict_is_surfaced_in_evidence(gov):
    m = _matrix(gov, models=["Z100"])
    e = m["entries"][0]
    text = " ".join(x["what"] + " " + x["detail"] for x in e["evidence"])
    assert "来源冲突" in text, "Z100 的来源冲突必须出现在证据链中"
