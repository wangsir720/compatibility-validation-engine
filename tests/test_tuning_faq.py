# -*- coding: utf-8 -*-
"""tuning / FAQ 模块测试 —— 重点验证「不可推荐的组合不给调优建议」这条边界。"""
from src.catalog import load_dcus, load_scenario
from src.compat_matrix import build_matrix
from src.tuning_faq import build_faq, build_tuning

ALL = sorted(load_dcus().by_key().keys())


def _run(sid="gov_lmm_inference"):
    s = load_scenario(sid)
    m = build_matrix(ALL, s)
    return m, build_tuning(m), build_faq(m)


def test_no_tuning_advice_for_not_recommended():
    """核心边界：判 not_recommended 的型号不能给调优建议 —— 调参救不回来。"""
    s = load_scenario("gov_lmm_inference")
    s["workload"]["model_id"] = "DeepSeek-V3"  # 必然 not_recommended
    m = build_matrix(ALL, s)
    t = build_tuning(m)
    assert t["items"] == []
    assert len(t["skipped"]) == len(m["entries"])
    for sk in t["skipped"]:
        assert "A-05" in sk["why_no_tuning"]


def test_no_tuning_advice_for_unknown():
    s = load_scenario("gov_lmm_inference")
    m = build_matrix(["DCU-NOT-EXIST"], s)
    t = build_tuning(m)
    assert t["items"] == []
    assert all("unknown" == sk["verdict"] for sk in t["skipped"])


def test_every_tuning_item_has_basis_and_risk():
    _, t, _ = _run()
    assert t["items"], "至少应有型号进入可部署档并拿到建议"
    for it in t["items"]:
        assert it["basis"], "建议必须写明依据：%s" % it["rule_id"]
        assert it["risk"], "建议必须写明风险：%s" % it["rule_id"]
        assert it["action"] and it["title"]
        assert it["triggered_by"], "建议必须能追溯到触发它的判定"


def test_faq_entries_are_traceable_to_verdicts():
    s = load_scenario("gov_lmm_inference")
    s["workload"]["model_id"] = "DeepSeek-V3"
    m = build_matrix(ALL, s)
    f = build_faq(m)
    assert f["entries"], "不推荐档应触发 FAQ"
    for e in f["entries"]:
        assert e["triggered_by"], "FAQ 必须注明触发来源：%s" % e["id"]
        assert e["question"] and e["answer"]


def test_faq_includes_unknown_guidance_when_unknown_exists():
    s = load_scenario("gov_lmm_inference")
    m = build_matrix(["DCU-NOT-EXIST"], s)
    f = build_faq(m)
    assert any(e["id"] == "F-03" for e in f["entries"]), "unknown 档应触发「不下结论」说明"


def test_faq_has_no_duplicate_ids():
    _, _, f = _run()
    ids = [e["id"] for e in f["entries"]]
    assert len(ids) == len(set(ids))


def test_second_scenario_also_produces_output():
    m, t, f = _run("finance_quant_finetune")
    assert m["scenario_id"] == "finance_quant_finetune"
    assert t["scenario_id"] == m["scenario_id"]
    assert f["scenario_id"] == m["scenario_id"]
