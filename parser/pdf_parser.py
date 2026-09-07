# -*- coding: utf-8 -*-
"""文本层 PDF 解析：pdfplumber 抽文本，扫描件自动降级 OCR。

策略（面试话术）："先判断是文本层还是扫描件，能不 OCR 就不 OCR——
OCR 是兜底不是默认"，节省 80%+ 文档的解析耗时。
"""
import os

from common.log import get_logger
from parser.ocr import SCANNED_PAGE_THRESHOLD, get_ocr_provider

logger = get_logger("pdf_parser")


def _extract_text_layer(pdf_path: str) -> tuple[str, int]:
    """用 pdfplumber 抽取文本层，返回 (文本, 页数)。"""
    import pdfplumber

    pages_text = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            pages_text.append(page.extract_text() or "")
    return "\n".join(pages_text), len(pages_text)


def parse_contract(pdf_path: str) -> dict:
    """解析合同 PDF，返回 {text, source, pages}。

    source: 'text'（文本层直接抽取）| 'ocr'（扫描件走 OCR 兜底）
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"合同文件不存在: {pdf_path}")
    text, pages = _extract_text_layer(pdf_path)
    avg_chars = len(text.strip()) / max(pages, 1)
    if avg_chars >= SCANNED_PAGE_THRESHOLD:
        logger.info("[解析] %s 文本层可用（%d 页，均值 %.0f 字符/页），跳过 OCR",
                    os.path.basename(pdf_path), pages, avg_chars)
        return {"text": text, "source": "text", "pages": pages}
    # 扫描件 → OCR 兜底
    logger.info("[解析] %s 判定为扫描件（均值 %.0f 字符/页 < %d），启动 OCR",
                os.path.basename(pdf_path), avg_chars, SCANNED_PAGE_THRESHOLD)
    ocr_text = get_ocr_provider().pdf_to_text(pdf_path)
    return {"text": ocr_text, "source": "ocr", "pages": pages}
