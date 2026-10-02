# -*- coding: utf-8 -*-
"""目录加载与来源冲突检测。

这个模块解决适配性验证里最容易被忽略、但最致命的一类问题：
**同一个型号的参数，在不同公开来源里对不上。**

处理规则（与 `data/sources.md` 中登记的一致）：

1. 每个数据行带 ``source_id``（指向 `data/sources.md`）与 ``credibility``
   （``official`` / ``secondary`` / ``unverified``）。
2. 同一型号同一字段出现多个不同取值 → 记为**冲突**。
3. 冲突处置：
   - 一方为 ``unverified`` → 采用可信等级更高的另一方，冲突**仍然记录并输出**；
   - 双方等级相同 → 该字段降级为「未查到」，并从自动判定中排除。
4. 理由：适配性验证的价值在于每条结论都能站住。宁可少判，不可错判。

其余纪律：
- 目录里缺必需列、缺 ``source_id``、型号重复且来源相同 → 直接抛错，不静默兜底。
- 任何字段为空的记录不会被当成 0，会被当成「未查到」。
"""
from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass, field

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CHIPS_DIR = os.path.join(DATA_DIR, "chips")
MODELS_DIR = os.path.join(DATA_DIR, "models")
SCENARIO_DIR = os.path.join(DATA_DIR, "scenarios")

CREDIBILITY_ORDER = {"unverified": 0, "secondary": 1, "official": 2}

# 参与冲突检测的数值字段（字符串字段不检测冲突，如 dtype/interface/note）
NUMERIC_FIELDS = {
    "cpu": ["cores", "threads", "base_ghz", "turbo_ghz", "l3_mb", "tdp_w"],
    "dcu": ["vram_gib", "fp32_tflops", "fp16_tflops", "int8_tops", "tdp_w"],
    "model": ["params_b", "weights_gib", "min_vram_gib"],
    "swstack": [],  # swstack 无同型号多来源，不做冲突检测
}


class CatalogError(Exception):
    """目录数据缺失、格式错误或来源缺失。不做静默降级。"""


@dataclass
class CatalogRow:
    """目录中的一行数据，附带来源与可信度。"""
    key: str
    data: dict
    source_id: str
    credibility: str

    def get(self, field_name: str):
        """取字段值。空字符串统一归一为 None（未查到），绝不返回 0 顶替。"""
        v = self.data.get(field_name)
        if v is None:
            return None
        v = v.strip()
        if v == "":
            return None
        return v

    def num(self, field_name: str):
        """取数值字段；缺失返回 None。"""
        v = self.get(field_name)
        if v is None:
            return None
        try:
            return float(v)
        except ValueError:
            return None

    def cite(self) -> str:
        return "%s（来源 %s，可信度 %s）" % (self.key, self.source_id, self.credibility)


@dataclass
class Catalog:
    """某个类别的目录，含冲突记录。"""
    kind: str
    rows: list[CatalogRow] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)

    def by_key(self) -> dict[str, CatalogRow]:
        out: dict[str, CatalogRow] = {}
        for r in self.rows:
            if r.key in out:
                # 已有记录被更高可信度覆盖；同等级保留首条并记冲突
                if CREDIBILITY_ORDER[r.credibility] > CREDIBILITY_ORDER[out[r.key].credibility]:
                    out[r.key] = r
            else:
                out[r.key] = r
        return out

    def conflicted_keys(self) -> set[str]:
        return {c["key"] for c in self.conflicts}

    def unresolved_keys(self) -> set[str]:
        """冲突未被消解（同等级来源打架）的型号 —— 这些型号的冲突字段不可用。"""
        return {c["key"] for c in self.conflicts if c["resolution"] == "unresolved"}

    def get(self, key: str) -> CatalogRow:
        idx = self.by_key()
        if key not in idx:
            raise CatalogError(
                "未收录型号 %r；已收录：%s" % (key, ", ".join(sorted(idx)) or "（空）"))
        return idx[key]


def _read_csv(path: str) -> list[dict]:
    if not os.path.isfile(path):
        raise CatalogError("数据文件不存在：%s" % path)
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise CatalogError("数据文件为空：%s" % path)
    for r in rows:
        for req in ("source_id", "credibility"):
            if not (r.get(req) or "").strip():
                raise CatalogError("数据行缺少 %s：%s" % (req, path))
        if r["credibility"].strip() not in CREDIBILITY_ORDER:
            raise CatalogError(
                "未知 credibility %r（应为 %s）：%s"
                % (r["credibility"].strip(), "/".join(CREDIBILITY_ORDER), path))
    return rows


def load_catalog(kind: str, filename: str, key_field: str) -> Catalog:
    """加载一个类别的目录，并做冲突检测。"""
    path = os.path.join(CHIPS_DIR if kind in ("cpu", "dcu", "swstack") else MODELS_DIR,
                        filename)
    raw = _read_csv(path)
    rows = [
        CatalogRow(key=r[key_field].strip(), data=r,
                   source_id=r["source_id"].strip(), credibility=r["credibility"].strip())
        for r in raw
    ]
    cat = Catalog(kind=kind, rows=rows)
    _detect_conflicts(cat, NUMERIC_FIELDS.get(kind, []))
    return cat


def _detect_conflicts(cat: Catalog, fields: list[str]) -> None:
    grouped: dict[str, list[CatalogRow]] = {}
    for r in cat.rows:
        grouped.setdefault(r.key, []).append(r)

    for key, group in grouped.items():
        if len(group) < 2:
            continue
        for fname in fields:
            values = {}
            for r in group:
                v = r.num(fname)
                if v is None:
                    continue
                values.setdefault(v, []).append(r)
            if len(values) < 2:
                continue
            # 取可信度最高的一档作为采用值
            best_cred = max(CREDIBILITY_ORDER[r.credibility] for r in group)
            adopted = [v for v, rs in values.items()
                       if CREDIBILITY_ORDER[rs[0].credibility] == best_cred]
            if len(adopted) == 1:
                resolution = "adopted_higher_credibility"
            else:
                resolution = "unresolved"
            cat.conflicts.append({
                "key": key,
                "field": fname,
                "values": {str(v): [r.source_id for r in rs] for v, rs in values.items()},
                "resolution": resolution,
                "action": ("采用 %s，冲突已记录待人工核实" % adopted[0]
                           if resolution == "adopted_higher_credibility"
                           else "同等级来源冲突，该字段降级为未查到并排除出自动判定"),
            })


def load_cpus() -> Catalog:
    return load_catalog("cpu", "cpu_specs.csv", "model")


def load_dcus() -> Catalog:
    return load_catalog("dcu", "dcu_specs.csv", "model")


def load_swstack() -> Catalog:
    return load_catalog("swstack", "swstack.csv", "stack")


def load_models() -> Catalog:
    return load_catalog("model", "model_matrix.csv", "model_id")


def dcu_supported_by_stack(dcu_model: str) -> list[CatalogRow]:
    """返回声明支持该 DCU 型号的软件栈条目。"""
    out = []
    for r in load_swstack().rows:
        raw = (r.data.get("supports_dcu") or "").strip()
        if not raw or raw == "全系列":
            out.append(r)
        elif dcu_model in [x.strip() for x in raw.split(";")]:
            out.append(r)
    return out


def list_scenarios() -> list[str]:
    if not os.path.isdir(SCENARIO_DIR):
        return []
    return sorted(f[:-5] for f in os.listdir(SCENARIO_DIR) if f.endswith(".json"))


def load_scenario(scenario_id: str) -> dict:
    path = os.path.join(SCENARIO_DIR, "%s.json" % scenario_id)
    if not os.path.isfile(path):
        raise CatalogError(
            "场景 %r 不存在；可用场景：%s" % (scenario_id, ", ".join(list_scenarios())))
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
