# -*- coding: utf-8 -*-
"""全链路编排：解析 → 条款切分 → LLM 抽取 → 规则比对 → 报告。"""
import time

from common.log import get_logger
from extractor.extract import extract_contract_fields
from parser.pdf_parser import parse_contract
from parser.segmenter import segment_clauses
from report.report_gen import build_report
from rules.engine import evaluate_rules, risk_level

logger = get_logger("pipeline")


def review_contract(pdf_path: str, use_llm_report: bool = True) -> dict:
    """单份合同全链路审核，返回结构化结果 + Markdown 报告。"""
    t0 = time.time()
    logger.info("[审核] 开始：%s", pdf_path)
    parsed = parse_contract(pdf_path)
    clauses = segment_clauses(parsed["text"])
    fields = extract_contract_fields(clauses)
    hits = evaluate_rules(fields)
    level = risk_level(hits)
    meta = {
        "file": pdf_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1],
        "source": parsed["source"],
        "clause_count": len(clauses),
        "elapsed_sec": round(time.time() - t0, 1),
    }
    report_md = build_report(fields, hits, meta, use_llm=use_llm_report)
    result = {
        "meta": meta,
        "risk_level": level,
        "rule_hits": hits,
        "fields": fields.to_display(),
        "report_md": report_md,
    }
    logger.info("[审核] 完成：%s 分级=%s 命中=%d 耗时=%.1fs",
                meta["file"], level, len(hits), meta["elapsed_sec"])
    return result
