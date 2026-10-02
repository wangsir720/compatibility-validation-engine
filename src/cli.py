# -*- coding: utf-8 -*-
"""命令行入口：输入场景 -> 输出兼容性验证方案包。

    python -m src.cli --list
    python -m src.cli --scenario gov_lmm_inference
    python -m src.cli --all
    python -m src.cli --conflicts

输出落在 `output/<场景编号>/`。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

from .catalog import (CatalogError, list_scenarios, load_cpus, load_dcus, load_models,
                       load_scenario, load_swstack)
from .compat_matrix import build_matrix
from .doc_assembler import render, save
from .tuning_faq import build_faq, build_tuning

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(ROOT, "output")


def all_dcu_models() -> list[str]:
    return sorted(load_dcus().by_key().keys())


def run(scenario_id: str) -> str:
    scenario = load_scenario(scenario_id)
    matrix = build_matrix(all_dcu_models(), scenario)
    tuning = build_tuning(matrix)
    faq = build_faq(matrix)
    doc = render(scenario, matrix, tuning, faq)

    base = os.path.join(OUTPUT_DIR, scenario_id)
    save(doc, os.path.join(base, "compatibility_report.md"))

    with open(os.path.join(base, "compat_matrix.csv"), "w", encoding="utf-8-sig",
              newline="") as f:
        w = csv.writer(f)
        w.writerow(["DCU型号", "单卡显存GiB", "显存需求GiB", "判定", "理由", "可用DTK版本"])
        for e in matrix["entries"]:
            w.writerow([e["dcu"], e["dcu_vram_gib"], e["required_gib"], e["verdict"],
                        e["reason"], ";".join(e.get("stack_versions") or [])])

    with open(os.path.join(base, "faq.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["编号", "问题", "答复", "触发来源"])
        for e in faq["entries"]:
            w.writerow([e["id"], e["question"], e["answer"], e["triggered_by"]])

    save(json.dumps({"scenario": scenario, "matrix": matrix, "tuning": tuning, "faq": faq},
                    ensure_ascii=False, indent=2, default=str),
         os.path.join(base, "result.json"))
    return doc


def show_conflicts() -> int:
    """打印全部来源冲突。这是本项目最有价值的输出之一。"""
    total = 0
    for name, cat in (("CPU", load_cpus()), ("DCU", load_dcus()),
                      ("模型", load_models()), ("软件栈", load_swstack())):
        if not cat.conflicts:
            continue
        print("=== %s 目录：%d 处来源冲突 ===" % (name, len(cat.conflicts)))
        for c in cat.conflicts:
            total += 1
            print("  型号 %s 字段 %s" % (c["key"], c["field"]))
            for v, srcs in c["values"].items():
                print("     取值 %-10s 来源 %s" % (v, ", ".join(srcs)))
            print("     处置：%s" % c["action"])
    print()
    print("冲突合计 %d 处 —— 适配性验证的价值在于每条结论都能站住，冲突必须显式暴露。" % total)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="src.cli", description="信创适配性验证引擎")
    ap.add_argument("--scenario", help="场景编号（见 data/scenarios/）")
    ap.add_argument("--all", action="store_true", help="跑全部场景")
    ap.add_argument("--list", action="store_true", help="列出可用场景")
    ap.add_argument("--conflicts", action="store_true", help="只打印来源冲突")
    args = ap.parse_args(argv)

    if args.conflicts:
        return show_conflicts()
    if args.list or not (args.scenario or args.all):
        print("可用场景：")
        for s in list_scenarios():
            print("  - %s" % s)
        return 0

    for sid in (list_scenarios() if args.all else [args.scenario]):
        try:
            run(sid)
        except (CatalogError, KeyError, ValueError) as e:
            print("场景 %s 验证失败：%s: %s" % (sid, type(e).__name__, e), file=sys.stderr)
            return 1
        print("已生成：output/%s/{compatibility_report.md, compat_matrix.csv, faq.csv, "
              "result.json}" % sid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
