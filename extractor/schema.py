# -*- coding: utf-8 -*-
"""合同字段 Pydantic schema：schema 是契约，校验失败带错误信息重试。"""
from typing import Optional, Union

from pydantic import BaseModel, Field
class ExtractedField(BaseModel):
    """单个抽取字段：值 + 原文引用 + 置信度（quote 溯源防幻觉）。"""
    value: Optional[Union[str, int, float]] = None
    quote: Optional[str] = None
    confidence: float = 0.0


class ContractFields(BaseModel):
    """9 个关键字段（口径：字段级 F1 按 9 字段平均）。"""
    buyer_name: ExtractedField = Field(default_factory=ExtractedField)      # 甲方（需方）
    supplier_name: ExtractedField = Field(default_factory=ExtractedField)   # 乙方（供方）
    amount: ExtractedField = Field(default_factory=ExtractedField)          # 合同总金额（元，int）
    payment_days: ExtractedField = Field(default_factory=ExtractedField)    # 付款账期（天，int）
    penalty_rate: ExtractedField = Field(default_factory=ExtractedField)    # 违约金比例（%，float）
    delivery_date: ExtractedField = Field(default_factory=ExtractedField)   # 交货日期（YYYY-MM-DD）
    signing_date: ExtractedField = Field(default_factory=ExtractedField)    # 签署日期（YYYY-MM-DD）
    dispute_resolution: ExtractedField = Field(default_factory=ExtractedField)  # 争议解决方式
    countersign: ExtractedField = Field(default_factory=ExtractedField)     # 会签状态（已会签/未会签）

    def to_eval_values(self) -> dict:
        """输出 {字段名: value} 供评估比对。"""
        return {name: getattr(self, name).value for name in type(self).model_fields}

    def to_display(self) -> dict:
        """输出 {字段名: {value, quote, confidence}} 供报告与接口使用。"""
        return {
            name: getattr(self, name).model_dump()
            for name in type(self).model_fields
        }


# LLM 单条款输出的原始 schema（value 统一为字符串，归一化在 extract 层做；
# 放宽为 str|int|float——模型偶尔直接返回数字，重试是兜底不是常规路径）
class RawFieldOut(BaseModel):
    value: Optional[Union[str, int, float]] = None
    quote: Optional[str] = None


class ClauseExtractOut(BaseModel):
    fields: dict[str, RawFieldOut]
