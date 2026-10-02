# -*- coding: utf-8 -*-
"""doc_assembler 与 CLI 端到端测试。"""
import os

import pytest

from src import cli
from src.catalog import list_scenarios
from src.doc_assembler import load_template, render, save, strip_ansi

ARTIFACTS = ["compatibility_report.md", "compat_matrix.csv", "faq.csv", "result.json"]


def test_all_scenarios_generate_all_artifacts():
    for sid in list_scenarios():
        cli.run(sid)
        base = os.path.join(cli.OUTPUT_DIR, sid)
        for name in ARTIFACTS:
            p = os.path.join(base, name)
            assert os.path.isfile(p), "缺少产物 %s" % p
            assert os.path.getsize(p) > 0, "产物为空 %s" % p


def test_report_has_required_sections():
    doc = cli.run("gov_lmm_inference")
    for h in ("## 1. 验证目标与边界", "## 2. 兼容性判定矩阵",
              "## 3. 调优建议", "## 4. 排查 FAQ",
              "## 5. 本方案未做的事（边界声明）"):
        assert h in doc, "方案文档缺少章节：%s" % h


def test_report_declares_non_client_and_no_vendor_private_data():
    doc = cli.run("gov_lmm_inference")
    assert "非真实交付项目" in doc
    assert "不含任何厂商私有测试数据" in doc


def test_report_contains_evidence_chain():
    doc = cli.run("gov_lmm_inference")
    assert "证据链" in doc
    assert "来源 S" in doc, "证据必须引用 data/sources.md 的来源编号"


def test_report_has_no_sensitive_fields():
    doc = cli.run("finance_quant_finetune")
    for banned in ("合同金额", "客户名称", "内部报价", "账号密码"):
        assert banned not in doc, "出现敏感字段：%s" % banned


def test_conflicts_command_reports_conflicts(capsys):
    assert cli.main(["--conflicts"]) == 0
    out = capsys.readouterr().out
    assert "来源冲突" in out
    assert "冲突合计" in out


def test_list_command(capsys):
    assert cli.main(["--list"]) == 0
    out = capsys.readouterr().out
    for sid in list_scenarios():
        assert sid in out


def test_bad_scenario_returns_nonzero():
    assert cli.main(["--scenario", "nope"]) == 1


def test_render_is_pure_and_repeatable():
    s = cli.load_scenario("gov_lmm_inference")
    m = cli.build_matrix(cli.all_dcu_models(), s)
    t = cli.build_tuning(m)
    f = cli.build_faq(m)
    a = render(s, m, t, f)
    b = render(s, m, t, f)
    assert a == b, "同样输入必须产出同样文档，否则无法复核"


def test_strip_ansi_removes_escape_codes():
    assert strip_ansi("\x1b[31m红\x1b[0m") == "红"


def test_load_template_missing_raises():
    with pytest.raises(FileNotFoundError):
        load_template("no-such-template.j2")


def test_save_creates_parent_dir(tmp_path):
    p = save("内容", str(tmp_path / "a" / "b.txt"))
    assert os.path.isfile(p)
    assert open(p, encoding="utf-8").read() == "内容"
