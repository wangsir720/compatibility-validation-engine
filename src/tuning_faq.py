# -*- coding: utf-8 -*-
"""调优建议与排查 FAQ。

两条边界（对应 `data/assumptions.md` A-05）：

1. **只对 supported / needs_tuning 两档给调优建议**。
   对 not_recommended 或 unknown 给调优参数是误导 —— 不可推荐的组合，
   调参救不回来；数据不全时更不能装作知道怎么调。
2. **每条建议必须写明依据**。无依据的建议宁可不写。

FAQ 由矩阵中的 needs_tuning / not_recommended 判定反推而来，
每条必须能追溯到具体的矩阵判定 —— 不能是凭空写就的通用问答。
"""
from __future__ import annotations

from .compat_matrix import VRAM_HEADROOM_THRESHOLD

# 建议模板：key -> (适用判定, 依据, 动作)
TUNING_RULES = [
    {
        "id": "T-01",
        "applies_to": ["needs_tuning"],
        "title": "压低 batch size 以释放显存",
        "action": "将推理 batch size 下调，直到显存占用落入安全区",
        "basis": "显存余量低于 %.0f%% 阈值时，batch size 是最先可调的参数"
                 % (VRAM_HEADROOM_THRESHOLD * 100),
        "risk": "吞吐随 batch 下降而下降，须与延迟目标一并复核",
    },
    {
        "id": "T-02",
        "applies_to": ["needs_tuning"],
        "title": "限制上下文长度",
        "action": "按业务实际需要设定 max_seq_len 上限，超长输入先做截断或摘要",
        "basis": "KV Cache 占用与输入+输出 token 数成正比（A-01）",
        "risk": "截断会损失长文本信息，须由业务侧确认可接受范围",
    },
    {
        "id": "T-03",
        "applies_to": ["needs_tuning"],
        "title": "锁定 DTK 与框架版本组合",
        "action": "按 data/chips/swstack.csv 中该卡的 base_kernel 要求锁定内核与 DTK 分支，"
                  "并固定 vLLM / torch 等框架的适配版本",
        "basis": "同一 DCU 型号在不同 DTK 分支上的支持范围不同，版本漂移会直接导致不可用",
        "risk": "锁版本会推迟安全补丁升级，须建立补丁窗口",
    },
    {
        "id": "T-04",
        "applies_to": ["supported"],
        "title": "启用连续批处理提升吞吐",
        "action": "使用支持连续批处理的推理框架（catalog 中已收录 vLLM-DCU 适配版本）",
        "basis": "连续批处理是推理框架的通用能力，可显著提升并发场景吞吐（A-02）",
        "risk": "并发过高会推高 P95 时延，须与延迟目标一起验收",
    },
    {
        "id": "T-05",
        "applies_to": ["supported"],
        "title": "推理与微调资源分离",
        "action": "LoRA 等轻量微调使用独立节点，不与在线推理服务混部",
        "basis": "微调任务的显存峰值会挤占在线服务的余量，混部会使延迟承诺失效",
        "risk": "增加节点数，成本上升",
    },
    {
        "id": "T-06",
        "applies_to": ["supported"],
        "title": "首 token 延迟需单独压测",
        "action": "对首 token 延迟单独设定验收指标，不与稳态吞吐混用",
        "basis": "首 token 延迟由 prefill 阶段主导，与 decode 吞吐不是同一瓶颈（A-02）",
        "risk": "该指标依赖真实输入长度，实验室数据不可直接外推",
    },
]


def build_tuning(matrix: dict) -> dict:
    """按矩阵结论生成调优建议。"""
    items = []
    skipped = []
    for entry in matrix["entries"]:
        if entry["verdict"] in ("supported", "needs_tuning"):
            for rule in TUNING_RULES:
                if entry["verdict"] in rule["applies_to"]:
                    items.append({
                        "dcu": entry["dcu"],
                        "rule_id": rule["id"],
                        "title": rule["title"],
                        "action": rule["action"],
                        "basis": rule["basis"],
                        "risk": rule["risk"],
                        "triggered_by": "矩阵判定 %s：%s" % (entry["dcu"], entry["verdict"]),
                    })
        else:
            skipped.append({
                "dcu": entry["dcu"],
                "verdict": entry["verdict"],
                "reason": entry["reason"],
                "why_no_tuning": (
                    "该型号判定为 %s，按 A-05 边界不给调优建议 —— "
                    "不可推荐的组合调参无效，数据不全时给建议等于误导" % entry["verdict"]),
            })

    return {
        "scenario_id": matrix["scenario_id"],
        "items": items,
        "skipped": skipped,
        "scope_note": "全部建议均来自本文件内登记的规则集，无来源依据的建议不生成。",
    }


# FAQ 模板：按判定类型 + 原因关键词匹配，保证每条可追溯到矩阵判定
FAQ_TEMPLATES = [
    {
        "id": "F-01",
        "match": "not_recommended",
        "question": "模型权重放不进单卡显存，应该怎么处理？",
        "answer": "三条路径：① 多卡切分（张量并行 / 流水并行），由框架自动分片；"
                   "② 量化到更低精度（如 INT8，需评估精度损失）；"
                   "③ 换更小参数量的模型并复评业务效果。"
                   "本引擎不代为选择 —— 选择依据是业务对精度与成本的权衡。",
        "trace": "矩阵判定 not_recommended 时触发",
    },
    {
        "id": "F-02",
        "match": "needs_tuning",
        "question": "显存够用但余量很小，现场该怎么调？",
        "answer": "按顺序试：先降 batch size（T-01），再压上下文长度（T-02），"
                   "仍不足则锁 DTK 版本并核对框架适配版本（T-03）。"
                   "每步之后重测 P95 时延，避免为省显存牺牲延迟承诺。",
        "trace": "矩阵判定 needs_tuning 时触发",
    },
    {
        "id": "F-03",
        "match": "unknown",
        "question": "矩阵给出 unknown，是不是就没结论了？",
        "answer": "不是没有结论，是**不下结论**。unknown 表示关键字段在公开资料中缺失"
                   "或来源存在冲突。此时应：① 查厂商官方文档或索取规格书补齐字段；"
                   "② 现场实测该型号的可用显存与软件栈版本；"
                   "③ 补齐后重跑本引擎。在此之前给出支持或不推荐的结论都是不负责的。",
        "trace": "矩阵判定 unknown 时触发",
    },
    {
        "id": "F-04",
        "match": "version",
        "question": "同一张卡在不同 DTK 版本上行为不一致，怎么排查？",
        "answer": "按 data/chips/swstack.csv 核对该型号的 base_kernel 要求与当前内核版本；"
                   "再核对 DTK 分支是否在支持列表内。跨分支混用是最常见的原因。",
        "trace": "矩阵证据中出现「软件栈覆盖」时附加",
    },
    {
        "id": "F-05",
        "match": "conflict",
        "question": "公开资料给出的参数对不上，以哪个为准？",
        "answer": "本引擎已按可信等级处理：高等级来源优先，且**冲突会显式输出**。"
                   "若冲突未消解（同等级来源打架），相关字段不参与判定，"
                   "此时应回到厂商官方文档确认，不要自行取中间值。",
        "trace": "矩阵证据中出现「来源冲突」时触发",
    },
]


def build_faq(matrix: dict) -> dict:
    """由矩阵判定反推 FAQ，每条注明触发来源。"""
    entries = []
    seen = set()
    for e in matrix["entries"]:
        triggers = []
        if e["verdict"] in ("not_recommended", "needs_tuning", "unknown"):
            triggers.append(e["verdict"])
        ev_text = " ".join(x["detail"] for x in e["evidence"])
        if "软件栈覆盖" in ev_text or "DTK" in ev_text:
            triggers.append("version")
        if "来源冲突" in ev_text:
            triggers.append("conflict")

        for t in triggers:
            for tpl in FAQ_TEMPLATES:
                if tpl["match"] != t or tpl["id"] in seen:
                    continue
                seen.add(tpl["id"])
                entries.append({
                    "id": tpl["id"],
                    "question": tpl["question"],
                    "answer": tpl["answer"],
                    "triggered_by": "%s —— %s（%s）" % (e["dcu"], e["verdict"], e["reason"]),
                    "trace": tpl["trace"],
                })
    return {
        "scenario_id": matrix["scenario_id"],
        "entries": entries,
        "scope_note": "FAQ 全部由矩阵判定反推，不含任何与矩阵无关的通用问答；"
                      "每条均可追溯到触发它的具体判定。",
    }
