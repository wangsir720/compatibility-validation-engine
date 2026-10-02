# -*- coding: utf-8 -*-
"""方案文档装配：矩阵 + 调优 + FAQ -> 方案草稿。

用标准库字符串模板而非模板引擎 —— 保持零第三方依赖是这个项目的一贯取舍：
拿到仓库的人 clone 完就能跑，比引一个模板库更值。
"""
from __future__ import annotations

import os
import re

TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")

VERDICT_LABEL = {
    "supported": "支持",
    "needs_tuning": "需调优",
    "not_recommended": "不推荐",
    "unknown": "待人工核实",
}


def _table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join("" if c is None else str(c) for c in r) + " |")
    return "\n".join(out)


def render(scenario: dict, matrix: dict, tuning: dict, faq: dict) -> str:
    """渲染完整方案草稿。"""
    w = scenario.get("workload", {})
    c = scenario.get("constraints", {})
    L: list[str] = []

    L.append("# %s · 兼容性验证方案草稿" % matrix["scenario_name"])
    L.append("")
    L.append("> 本文由 `src/doc_assembler.py` 从 `data/scenarios/%s.json` 与 `data/` 下的"
             "公开资料目录自动装配。**全部结论基于公开信息与估算模型，非真实交付项目，"
             "不含任何厂商私有测试数据。**" % matrix["scenario_id"])
    L.append("")

    L.append("## 1. 验证目标与边界")
    L.append(_table(
        ["项", "值"],
        [["场景编号", matrix["scenario_id"]],
         ["目标模型", matrix["model_id"]],
         ["模型权重", "%.2f GiB" % matrix["weights_gib"]],
         ["KV Cache 估算",
          "%.2f GiB" % matrix["kv_cache_gib"] if matrix["kv_cache_gib"] is not None
          else "未查到（模型结构参数未收录）"],
         ["显存需求合计", "%.2f GiB" % matrix["required_gib"]],
         ["需求口径", matrix["required_gib_basis"]],
         ["输入 / 输出长度", "%d / %d tokens" % (w.get("input_len_tokens"),
                                                  w.get("output_len_tokens"))],
         ["并发会话数", w.get("concurrent_sessions")],
         ["P95 时延目标", "%s ms" % w.get("p95_latency_ms")],
         ["可用性目标", w.get("availability_target")],
         ["操作系统", c.get("os")],
         ["数据驻留要求", c.get("data_residency")]]))
    L.append("")
    if matrix["kv_cache_gib"] is None:
        L.append("> ⚠️ **本方案的显存需求为下界估算**：KV Cache 需要模型层数/注意力头数/"
                 "头维等结构参数，本项目未收录该数据，因此按「未查到」处理并排除该项。"
                 "补齐后重跑即可得到完整估算。")
        L.append("")

    L.append("## 2. 兼容性判定矩阵")
    L.append(_table(
        ["DCU 型号", "单卡显存", "显存需求", "余量", "判定", "需锁版本", "理由"],
        [[e["dcu"],
          "%.0f GiB" % e["dcu_vram_gib"] if e["dcu_vram_gib"] is not None else "未查到",
          "%.2f GiB" % e["required_gib"],
          "%.1f%%" % (e["vram_headroom"] * 100)
          if e.get("vram_headroom") is not None else "未查到",
          VERDICT_LABEL[e["verdict"]],
          "是" if e.get("version_lock_required") else "否",
          e["reason"]] for e in matrix["entries"]]))
    L.append("")
    L.append("> 「需锁版本」指该型号在不同内核上对应不同 DTK 分支，部署时必须固定版本组合。"
             "它是独立的部署约束，不改变显存判定档位 —— 混在一起会让所有型号落进同一档，"
             "矩阵就失去区分度了。")
    L.append("")
    L.append("### 2.1 每条判定的证据链")
    for e in matrix["entries"]:
        L.append("")
        L.append("**%s → %s**" % (e["dcu"], VERDICT_LABEL[e["verdict"]]))
        L.append("")
        for ev in e["evidence"]:
            L.append("- %s：%s" % (ev["what"], ev["detail"]))
    L.append("")
    L.append("目录中收录的 DTK 版本：%s"
             % ("、".join(matrix["swstack_versions_in_catalog"]) or "未查到"))
    L.append("")

    L.append("## 3. 调优建议")
    if tuning["items"]:
        L.append(_table(
            ["规则", "适用型号", "建议", "动作", "依据", "风险"],
            [[t["rule_id"], t["dcu"], t["title"], t["action"], t["basis"], t["risk"]]
             for t in tuning["items"]]))
    else:
        L.append("无适用建议（当前所有型号的判定均不支持给调优方案）。")
    L.append("")
    if tuning["skipped"]:
        L.append("### 3.1 不给建议的型号及原因")
        L.append(_table(
            ["型号", "判定", "原因", "为何不给调优建议"],
            [[s["dcu"], VERDICT_LABEL[s["verdict"]], s["reason"], s["why_no_tuning"]]
             for s in tuning["skipped"]]))
        L.append("")

    L.append("## 4. 排查 FAQ")
    if faq["entries"]:
        for e in faq["entries"]:
            L.append("### %s %s" % (e["id"], e["question"]))
            L.append("")
            L.append(e["answer"])
            L.append("")
            L.append("*触发来源：%s*" % e["triggered_by"])
            L.append("")
    else:
        L.append("当前矩阵未产生 FAQ 触发条件。")
        L.append("")

    L.append("## 5. 本方案未做的事（边界声明）")
    for line in [
        "**未做真实验证**：无 DCU/CPU 实机，全部结论基于公开资料与估算模型。"
        "真机验证需在真实环境完成后回填。",
        "**不含厂商私有测试数据**：不生成任何看起来像厂商内部实测的数字。",
        "**不做跨厂商评测打分**：只回答「能否跑、跑多少、调什么」，不排名。",
        "**不做集群规模规划**：仅覆盖单卡/轻量微调的可行性，不覆盖大规模预训练。",
        "**不含采购与报价建议**：本方案只回答技术可行性。",
        "**数据有时效**：`data/` 中的抓取日期即为数据边界，版本与规格可能已变化，"
        "落地前须重新核对。",
    ]:
        L.append("- %s" % line)
    L.append("")
    L.append("---")
    L.append("生成命令：`python -m src.cli --scenario %s`" % matrix["scenario_id"])
    L.append("")
    return "\n".join(L)


def load_template(name: str) -> str:
    """读取模板文件（供外部流程复用；本项目默认走内联渲染）。"""
    path = os.path.join(TEMPLATE_DIR, name)
    if not os.path.isfile(path):
        raise FileNotFoundError("模板不存在：%s" % path)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def save(text: str, path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def strip_ansi(text: str) -> str:
    """去除 ANSI 转义序列，便于写入文件。"""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)
