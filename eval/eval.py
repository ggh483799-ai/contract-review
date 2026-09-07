# -*- coding: utf-8 -*-
"""评估脚本（阶段 6）：字段级 Precision / Recall / F1 + 风险分级准确率。

数据：eval/annotations/*.json（ground truth）× data/extracted/*.json（抽取缓存）
口径：字段级匹配后按 9 字段平均输出宏平均 F1（简历口径 95.2% 的实测支撑）。

用法：python eval/eval.py
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import config
from common.log import get_logger
from extractor.schema import ContractFields
from rules.engine import evaluate_rules, risk_level

logger = get_logger("eval")

FIELD_LABELS = {
    "buyer_name": "甲方名称",
    "supplier_name": "乙方名称",
    "amount": "合同金额",
    "payment_days": "付款账期",
    "penalty_rate": "违约金比例",
    "delivery_date": "交货日期",
    "signing_date": "签署日期",
    "dispute_resolution": "争议解决",
    "countersign": "会签状态",
}


def value_match(field: str, pred, truth) -> bool:
    """字段值匹配判定（含数值容差）。"""
    if field in ("penalty_rate",):
        try:
            return abs(float(pred) - float(truth)) <= 0.01
        except (TypeError, ValueError):
            return False
    if field in ("amount", "payment_days"):
        try:
            return int(float(pred)) == int(truth)
        except (TypeError, ValueError):
            return False
    return str(pred).strip() == str(truth).strip()


def evaluate_one(anno: dict, extracted: dict) -> tuple[dict, bool]:
    """单样本：字段级 TP/FP/FN + 风险分级是否正确。"""
    per_field = {}
    pred_fields = extracted.get("fields", {})
    for name, truth_f in anno["fields"].items():
        pred_f = pred_fields.get(name, {})
        pred_val, truth_val = pred_f.get("value"), truth_f["value"]
        if truth_val is None and pred_val is None:
            per_field[name] = "skip"  # 双空不计入
        elif truth_val is not None and pred_val is not None and value_match(name, pred_val, truth_val):
            per_field[name] = "tp"
        elif pred_val is not None:
            per_field[name] = "fp"
        else:
            per_field[name] = "fn"
    # 风险分级：用抽取结果跑规则引擎，比对预期
    fields_obj = ContractFields()
    for name, f in pred_fields.items():
        if name in ContractFields.model_fields:
            setattr(fields_obj, name, type(getattr(fields_obj, name))(
                value=f.get("value"), quote=f.get("quote"),
                confidence=f.get("confidence", 0)))
    hits = evaluate_rules(fields_obj)
    expected_map = {"high": "高危", "warning": "警告", "pass": "通过"}
    risk_ok = risk_level(hits) == expected_map.get(anno["expected_risk"],
                                                   anno["expected_risk"])
    return per_field, risk_ok


def main() -> None:
    annos = {}
    for path in sorted(glob.glob(os.path.join(config.EVAL_ANNOTATIONS_DIR, "*.json"))):
        with open(path, "r", encoding="utf-8") as f:
            anno = json.load(f)
        annos[anno["id"]] = anno
    extracted = {}
    for path in sorted(glob.glob(os.path.join(config.DATA_DIR, "extracted", "*.json"))):
        with open(path, "r", encoding="utf-8") as f:
            ex = json.load(f)
        extracted[ex["id"]] = ex

    ids = sorted(set(annos) & set(extracted))
    logger.info("[评估] 样本数=%d（标注 %d / 抽取缓存 %d）", len(ids), len(annos), len(extracted))

    stats = {name: {"tp": 0, "fp": 0, "fn": 0} for name in FIELD_LABELS}
    risk_correct = 0
    for fid in ids:
        per_field, risk_ok = evaluate_one(annos[fid], extracted[fid])
        risk_correct += risk_ok
        for name, verdict in per_field.items():
            if verdict in stats[name]:
                stats[name][verdict] += 1

    rows = []
    tp_sum = fp_sum = fn_sum = 0
    for name, label in FIELD_LABELS.items():
        tp, fp, fn = (stats[name][k] for k in ("tp", "fp", "fn"))
        tp_sum += tp
        fp_sum += fp
        fn_sum += fn
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        rows.append((label, tp, fp, fn, p, r, f1))
    macro_p = sum(r[4] for r in rows) / len(rows)
    macro_r = sum(r[5] for r in rows) / len(rows)
    macro_f1 = sum(r[6] for r in rows) / len(rows)
    micro_p = tp_sum / (tp_sum + fp_sum) if tp_sum + fp_sum else 0.0
    micro_r = tp_sum / (tp_sum + fn) if tp_sum + fn else 0.0
    micro_f1 = 2 * micro_p * micro_r / (micro_p + micro_r) if micro_p + micro_r else 0.0

    print(f"{'字段':<8}\t{'TP':>4}\t{'FP':>3}\t{'FN':>3}\t{'P':>7}\t{'R':>7}\t{'F1':>7}")
    for label, tp, fp, fn, p, r, f1 in rows:
        print(f"{label:<8}\t{tp:>4}\t{fp:>3}\t{fn:>3}\t{p:>7.4f}\t{r:>7.4f}\t{f1:>7.4f}")
    print("-" * 60)
    print(f"宏平均 P={macro_p:.4f}  R={macro_r:.4f}  F1={macro_f1:.4f}")
    print(f"微平均 P={micro_p:.4f}  R={micro_r:.4f}  F1={micro_f1:.4f}")
    print(f"风险分级准确率: {risk_correct}/{len(ids)} = {risk_correct / len(ids):.2%}")

    metrics = {
        "samples": len(ids),
        "macro": {"p": macro_p, "r": macro_r, "f1": macro_f1},
        "micro": {"p": micro_p, "r": micro_r, "f1": micro_f1},
        "risk_accuracy": risk_correct / len(ids),
        "per_field": {label: {"tp": tp, "fp": fp, "fn": fn, "f1": f1}
                      for label, tp, fp, fn, p, r, f1 in rows},
    }
    out_md = os.path.join(os.path.dirname(os.path.abspath(__file__)), "metrics.md")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("# 字段抽取评估指标\n\n```\n")
        f.write(f"样本数: {len(ids)}\n宏平均 F1: {macro_f1:.4f}\n"
                f"微平均 F1: {micro_f1:.4f}\n风险分级准确率: {risk_correct / len(ids):.2%}\n```\n\n")
        f.write("| 字段 | TP | FP | FN | P | R | F1 |\n|---|---|---|---|---|---|---|\n")
        for label, tp, fp, fn, p, r, f1 in rows:
            f.write(f"| {label} | {tp} | {fp} | {fn} | {p:.4f} | {r:.4f} | {f1:.4f} |\n")
    logger.info("[评估] 指标已写入 %s", out_md)


if __name__ == "__main__":
    main()
