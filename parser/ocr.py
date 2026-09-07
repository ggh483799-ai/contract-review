# -*- coding: utf-8 -*-
"""OCR 提供方抽象：接口隔离 + 可替换设计。

面试话术落点：OCRProvider 抽象统一 parse(path) -> str 接口，
RapidOCR / PaddleOCR / 云 OCR 换实现只改一行装配代码。
"""
import os

from common.log import get_logger

logger = get_logger("ocr")

# 每页平均可抽取字符低于该阈值 → 判定为扫描件
SCANNED_PAGE_THRESHOLD = 50


class OCRProvider:
    """OCR 抽象基类：子类实现 pdf_to_text(pdf_path) -> str。"""

    name = "base"

    def pdf_to_text(self, pdf_path: str) -> str:
        raise NotImplementedError("OCRProvider 子类必须实现 pdf_to_text")


class RapidOCRProvider(OCRProvider):
    """RapidOCR（onnxruntime，PP-OCRv4 模型 onnx 版），Windows CPU 轻量可跑。"""

    name = "rapidocr"

    def __init__(self) -> None:
        from rapidocr_onnxruntime import RapidOCR

        self._engine = RapidOCR()
        logger.info("[RapidOCR] 引擎初始化完成")

    def pdf_to_text(self, pdf_path: str) -> str:
        import fitz  # PyMuPDF：渲染页面为图片

        texts = []
        with fitz.open(pdf_path) as doc:
            for page_no, page in enumerate(doc, start=1):
                # DPI 300：实测 200dpi 时检测器会漏检部分长文本行（踩坑记录见 README）
                pix = page.get_pixmap(dpi=300)
                img_bytes = pix.tobytes("png")
                result, _ = self._engine(img_bytes)
                page_text = "\n".join(line[1] for line in (result or []))
                texts.append(page_text)
                logger.debug("[RapidOCR] 第 %d 页识别出 %d 行",
                             page_no, len(result or []))
        return "\n".join(texts)


_provider: OCRProvider | None = None


def get_ocr_provider() -> OCRProvider:
    """懒加载全局 OCR 单例；换实现只改这里（一行装配）。"""
    global _provider
    if _provider is None:
        _provider = RapidOCRProvider()
    return _provider
