# -*- coding: utf-8 -*-
"""解析层：PDF 文本抽取 + OCR 兜底 + 条款切分。"""
from parser.pdf_parser import parse_contract
from parser.segmenter import Clause, segment_clauses

__all__ = ["parse_contract", "Clause", "segment_clauses"]
