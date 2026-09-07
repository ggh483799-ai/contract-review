# -*- coding: utf-8 -*-
"""离线回归测试：不调 LLM，验证可确定性验证的全部组件。

用法：python tests/test_pipeline.py   （pytest 亦可）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import config
from extractor.extract import _normalize_for_match, quote_in_text
from extractor.schema import ContractFields, ExtractedField
from parser.segmenter import segment_clauses
from report.report_gen import build_template_report
from rules.engine import evaluate_rules, load_rules, risk_level
from scripts.generate_samples import (CONFIGS, build_annotation, build_contract_text,
                                      cn_clause_num, cn_upper_amount)

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def _fields(**kwargs) -> ContractFields:
    """构造字段对象：默认全字段填有效值（只测目标规则），kwargs 覆盖/置 None。"""
    defaults = dict(
        buyer_name="甲公司", supplier_name="乙公司", amount=500000,
        payment_days=30, penalty_rate=10.0, delivery_date="2026-09-30",
        signing_date="2026-08-01", dispute_resolution="甲方所在地法院诉讼",
        countersign=None,  # 默认未提及会签：金额<100万时不触发 R004
    )
    defaults.update(kwargs)
    f = ContractFields()
    for k, v in defaults.items():
        setattr(f, k, ExtractedField(value=v, quote="x", confidence=0.95))
    return f


def test_chinese_utils():
    print("[测试] 中文工具函数")
    check("大写金额 1500000", cn_upper_amount(1500000) == "壹佰伍拾万元整")
    check("大写金额 1200000", cn_upper_amount(1200000) == "壹佰贰拾万元整")
    check("大写金额 480000", cn_upper_amount(480000) == "肆拾捌万元整")
    check("大写金额 100000", cn_upper_amount(100000) == "壹拾万元整")
    check("条款号 1/10/11/21", (cn_clause_num(1), cn_clause_num(10),
                                cn_clause_num(11), cn_clause_num(21))
          == ("一", "十", "十一", "二十一"))


def test_segmenter():
    print("[测试] 条款切分器")
    text = ("合同编号：X\n甲方（需方）：A公司\n乙方（供方）：B公司\n"
            "第一条 标的与金额\n本合同总金额为人民币壹拾万元整。\n"
            "第二条 付款方式\n甲方在30日内向乙方支付。\n"
            "第三条 合同生效\n本合同自签字盖章之日起生效。")
    clauses = segment_clauses(text)
    check("切出 4 段（含其他条款）", len(clauses) == 4, str(len(clauses)))
    check("前导段归其他条款", clauses[0].no is None and "甲方（需方）" in clauses[0].text)
    check("锚点标题提取", clauses[1].title.startswith("标的与金额"), clauses[1].title)
    check("正文归属正确", "30日内" in clauses[2].text)


def test_rules_engine():
    print("[测试] 规则引擎")
    load_rules()
    hits = evaluate_rules(_fields(payment_days=90, penalty_rate=15))
    check("账期 90 命中 R001", any(h["id"] == "R001" for h in hits))
    check("分级=高危", risk_level(hits) == "高危")

    hits = evaluate_rules(_fields(penalty_rate=25.0, payment_days=30))
    check("违约金 25% 命中 R002", any(h["id"] == "R002" for h in hits))

    hits = evaluate_rules(_fields(amount=1500000, countersign="未会签", payment_days=40,
                                  penalty_rate=12))
    check("150万未会签命中 R003", any(h["id"] == "R003" for h in hits))

    hits = evaluate_rules(_fields(amount=1500000, payment_days=40, penalty_rate=12))
    check("150万未提及会签命中 R004 警告", any(h["id"] == "R004" for h in hits)
          and risk_level(hits) == "警告")

    hits = evaluate_rules(_fields(amount=1200000, countersign="已会签",
                                  payment_days=60, penalty_rate=20))
    check("边界 60天/20%/已会签 通过", hits == [] and risk_level(hits) == "通过")

    hits = evaluate_rules(_fields(buyer_name=None, supplier_name="B公司"))
    check("甲方缺失命中 R008", any(h["id"] == "R008" for h in hits))

    hits = evaluate_rules(_fields(payment_days=None, penalty_rate=10))
    check("账期缺失命中 R005 警告", any(h["id"] == "R005" for h in hits)
          and risk_level(hits) == "警告")


def test_quote_validation():
    print("[测试] quote 校验（防幻觉）")
    text = "本合同总金额为人民币壹佰伍拾万元整（小写：¥1,500,000.00），含税。"
    check("精确命中", quote_in_text("（小写：¥1,500,000.00）", text))
    check("OCR 全角￥/丢千分位仍命中", quote_in_text("（小写：￥1500000.00）", text))
    check("编造的 quote 被拦截", not quote_in_text("合同金额为两百万元", text))
    check("跨断行空白归一化命中", quote_in_text("¥1,500,000.00），含税", text))


def test_report_template():
    print("[测试] 报告模板兜底")
    fields = _fields(buyer_name="A公司", supplier_name="B公司", amount=620000,
                     payment_days=90, penalty_rate=15)
    hits = evaluate_rules(fields)
    md = build_template_report(fields, hits, {"file": "C02.pdf", "source": "ocr",
                                              "clause_count": 8, "elapsed_sec": 20})
    check("报告含风险分级", "高危" in md)
    check("报告含命中规则", "R001" in md and "付款账期 90 天" in md)
    check("报告含字段表", "甲方（需方）" in md and "溯源" in md)


def test_samples_consistency():
    print("[测试] 样本生成一致性（标注引用可溯源）")
    ok = 0
    for c in CONFIGS:
        text, quotes = build_contract_text(c)
        anno = build_annotation(c, quotes)
        all_in = all(q is None or q in text for q in quotes.values())
        missing_ok = True
        for fname, f in anno["fields"].items():
            if f["quote"] is not None and f["quote"] not in text:
                missing_ok = False
        if all_in and missing_ok:
            ok += 1
    check(f"全部 {len(CONFIGS)} 份标注引用可在原文命中", ok == len(CONFIGS), f"{ok}")


def main():
    test_chinese_utils()
    test_segmenter()
    test_rules_engine()
    test_quote_validation()
    test_report_template()
    test_samples_consistency()
    print(f"\n结果: {PASS} PASS / {FAIL} FAIL")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
