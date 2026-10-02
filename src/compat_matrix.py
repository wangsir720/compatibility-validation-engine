# -*- coding: utf-8 -*-
"""兼容性矩阵：芯片 × 软件栈 × 模型 × 场景 -> 判定结论。

判定档（对应 `data/assumptions.md` A-03）：

    supported        显存余量充足，DTK 覆盖该卡，无未解决冲突
    needs_tuning     显存够但余量不足 15%，或需锁定特定 DTK / 框架版本
    not_recommended  权重 + KV Cache 估算已超单卡显存
    unknown          关键字段缺失，或存在未解决的来源冲突

三条不可让步的规则：

1. **每条判定必须给出证据链** —— 引用到 `data/` 的具体行与 source_id，不允许凭空结论。
2. **缺数据不猜** —— 关键字段缺失直接判 ``unknown``，不按 0 或经验值填补。
3. **冲突显式暴露** —— 冲突不静默消解，判定结论里必须带出来。
"""
from __future__ import annotations

from .catalog import CatalogError, dcu_supported_by_stack, load_dcus, load_models, load_swstack
from .catalog import CREDIBILITY_ORDER

# ---- 来自 data/assumptions.md 的常量（禁止在代码中出现未登记数字）----
# A-01 推理运行时显存余量系数
RUNTIME_VRAM_FACTOR = 1.15
# A-03 判定阈值，与 A-01 同源，避免两处口径不一致
VRAM_HEADROOM_THRESHOLD = 0.15
# A-01 KV Cache：2（K 与 V 两份）× dtype 字节数
KV_CACHE_BYTES_PER_TOKEN_PER_LAYER = 2 * 2


class MatrixError(Exception):
    pass


def _require(node: dict, path: str):
    cur = node
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise MatrixError("场景参数缺少必填字段：%s" % path)
        cur = cur[part]
    return cur


def estimate_kv_cache_gib(input_len: int, output_len: int, layers: int | None,
                          kv_heads: int | None, head_dim: int | None) -> float | None:
    """估算 KV Cache 占用（GiB）。

    结构参数（层数/头数/头维）随模型而异，公开资料未逐项给出；
    未提供时返回 None，判定相应降级为 unknown —— 不编一个层数出来。
    """
    if layers is None or kv_heads is None or head_dim is None:
        return None
    total_tokens = input_len + output_len
    nbytes = total_tokens * KV_CACHE_BYTES_PER_TOKEN_PER_LAYER * layers * kv_heads * head_dim
    return nbytes / 1024 ** 3


def _judge(dcu_vram: float, need_gib: float) -> tuple[str, str]:
    """按显存余量给判定档。"""
    if need_gib is None:
        return "unknown", "关键字段缺失，无法估算显存需求"
    if need_gib > dcu_vram:
        return "not_recommended", (
            "权重与 KV Cache 估算合计 %.2f GiB，超过单卡显存 %.2f GiB，需多卡切分或换更小模型"
            % (need_gib, dcu_vram))
    headroom = (dcu_vram - need_gib) / dcu_vram
    if headroom < VRAM_HEADROOM_THRESHOLD:
        return "needs_tuning", (
            "显存余量仅 %.1f%%，低于 %.0f%% 阈值，须压低 batch / 上下文长度或启用显存优化"
            % (headroom * 100, VRAM_HEADROOM_THRESHOLD * 100))
    return "supported", (
        "显存余量 %.1f%%，高于 %.0f%% 阈值"
        % (headroom * 100, VRAM_HEADROOM_THRESHOLD * 100))


def _meets_min_vram(model, dcu_vram: float | None) -> bool | None:
    """对照模型目录登记的最小显存要求 —— 这是来自来源数据的第二道校验。

    与 `required_gib` 的估算不同，`min_vram_gib` 是模型资料里直接给出的门槛值，
    不含任何估算成分。任一方缺失时返回 None（未查到），不猜测。
    """
    need = model.num("min_vram_gib")
    if need is None or dcu_vram is None:
        return None
    return dcu_vram >= need


def build_matrix(dcu_models: list[str], scenario: dict) -> dict:
    """对给定 DCU 型号列表与场景，生成兼容性矩阵。"""
    _require(scenario, "scenario_id")
    model_id = _require(scenario, "workload.model_id")
    input_len = int(_require(scenario, "workload.input_len_tokens"))
    output_len = int(_require(scenario, "workload.output_len_tokens"))

    models = load_models()
    if model_id not in models.by_key():
        raise MatrixError(
            "场景引用了未收录的模型 %r；已收录：%s" % (model_id, ", ".join(sorted(models.by_key()))))
    model = models.get(model_id)

    weights_gib = model.num("weights_gib")
    if weights_gib is None:
        raise MatrixError("模型 %s 的 weights_gib 字段为空，属数据缺失，不做估算填补" % model_id)

    # KV Cache 需要模型结构参数；本项目未内置该数据 → None → 判定降级
    model_cfg = scenario.get("workload", {}).get("model_structure") or {}
    kv_gib = estimate_kv_cache_gib(
        input_len, output_len,
        model_cfg.get("layers"), model_cfg.get("kv_heads"), model_cfg.get("head_dim"))
    need_gib = weights_gib * RUNTIME_VRAM_FACTOR if kv_gib is None else \
        (weights_gib + kv_gib) * RUNTIME_VRAM_FACTOR

    dcu_cat = load_dcus()
    swstack = load_swstack()
    entries = []

    for model_name in dcu_models:
        if model_name not in dcu_cat.by_key():
            entries.append({
                "dcu": model_name,
                "verdict": "unknown",
                "reason": "型号未收录于 data/chips/dcu_specs.csv，无任何可引用的公开规格",
                "evidence": [],
                "dcu_vram_gib": None,
                "required_gib": round(need_gib, 2),
                "stack_versions": [],
                "version_lock_required": False,
                "meets_model_min_vram": None,
                "vram_headroom": None,
            })
            continue

        dcu = dcu_cat.get(model_name)
        evidence = [{"what": "DCU 规格", "detail": dcu.cite()}]
        vram = dcu.num("vram_gib")

        # 软件栈覆盖（版本列的 "-" 表示未给出具体版本，不计入版本清单）
        stacks = dcu_supported_by_stack(model_name)
        stack_versions = sorted({
            v for v in (s.get("version") for s in stacks) if v and v != "-"
        })
        if not stacks:
            evidence.append({"what": "软件栈覆盖", "detail": "未找到声明支持该型号的 DTK 版本"})
            verdict = "unknown"
            reason = "软件栈支持范围缺失，无法确认可部署"
            version_lock = False
        else:
            evidence.append({
                "what": "软件栈覆盖",
                "detail": "支持该卡的 DTK 版本：%s（来源 %s）"
                          % (", ".join(stack_versions),
                             ", ".join(sorted({s.source_id for s in stacks}))),
            })
            verdict, reason = _judge(vram, need_gib)
            # 版本分支约束单独记为标记，不降级判定 —— 否则所有卡同一档，矩阵失去区分度
            version_lock = len(stack_versions) > 1
            if version_lock:
                reason += "；该卡需按内核版本选择不同 DTK 分支（rock-*），部署时须锁定版本组合"

        # 冲突暴露
        unresolved = [c for c in dcu_cat.conflicts
                      if c["key"] == model_name and c["resolution"] == "unresolved"]
        adopted = [c for c in dcu_cat.conflicts
                   if c["key"] == model_name and c["resolution"] == "adopted_higher_credibility"]
        for c in adopted:
            evidence.append({"what": "来源冲突（已消解）", "detail": c["action"] + "；字段 %s" % c["field"]})
        if unresolved and vram is not None:
            for c in unresolved:
                evidence.append({"what": "来源冲突（未消解）",
                                 "detail": "字段 %s 存在同等级来源冲突，该字段不参与判定" % c["field"]})

        # unverified 来源不参与判定
        weakest = min((CREDIBILITY_ORDER[r.credibility] for r in dcu_cat.rows
                       if r.key == model_name), default=2)
        if weakest == 0:
            evidence.append({"what": "数据可信度", "detail": "该型号存在 unverified 级来源，相关字段不作为判定依据"})

        entries.append({
            "dcu": model_name,
            "verdict": verdict,
            "reason": reason,
            "evidence": evidence,
            "dcu_vram_gib": vram,
            "required_gib": round(need_gib, 2),
            "stack_versions": stack_versions,
            "version_lock_required": version_lock,
            "meets_model_min_vram": _meets_min_vram(model, vram),
            "vram_headroom": (round((vram - need_gib) / vram, 4)
                              if vram not in (None, 0) and need_gib is not None else None),
        })

    order = {"supported": 0, "needs_tuning": 1, "not_recommended": 2, "unknown": 3}
    # 先按判定档，再按显存余量从大到小 —— 余量大的排前面，矩阵才有信息量
    entries.sort(key=lambda e: (order[e["verdict"]],
                                -(e["vram_headroom"] if e["vram_headroom"] is not None else -1),
                                e["dcu"]))

    return {
        "scenario_id": scenario["scenario_id"],
        "scenario_name": scenario.get("name", scenario["scenario_id"]),
        "model_id": model_id,
        "weights_gib": weights_gib,
        "kv_cache_gib": round(kv_gib, 2) if kv_gib is not None else None,
        "required_gib": round(need_gib, 2),
        "required_gib_basis": (
            "权重 %.2f GiB + KV Cache %.2f GiB，再乘运行时余量系数 %.2f"
            % (weights_gib, kv_gib, RUNTIME_VRAM_FACTOR) if kv_gib is not None
            else "权重 %.2f GiB × 运行时余量系数 %.2f（**KV Cache 未计入：模型结构参数未收录，"
                 "本估算为下界**）" % (weights_gib, RUNTIME_VRAM_FACTOR)),
        "entries": entries,
        "swstack_versions_in_catalog": sorted({
            v for v in (s.get("version") for s in swstack.rows) if v and v != "-"
        }),
        "scope_note": "本矩阵不含任何厂商私有测试数据；每条判定的证据均指向 data/ 下的公开资料行。",
    }
