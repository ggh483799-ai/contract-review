# -*- coding: utf-8 -*-
"""报告层：CoT 审查报告生成（LLM 生成 + 确定性模板兜底）。"""
from common import config
from common.log import get_logger
from extractor.schema import ContractFields
from rules.engine import risk_level

logger = get_logger("report")

FIELD_LABELS = {
    "buyer_name": "甲方（需方）",
    "supplier_name": "乙方（供方）",
    "amount": "合同总金额（元）",
    "payment_days": "付款账期（天）",
    "penalty_rate": "违约金比例（%）",
    "delivery_date": "交货日期",
    "signing_date": "签署日期",
    "dispute_resolution": "争议解决方式",
    "countersign": "会签状态",
}

_SEVERITY_LABEL = {"high": "🔴 高危", "warning": "🟡 警告"}


def _field_table(fields: ContractFields) -> str:
    lines = ["| 字段 | 值 | 原文引用（溯源） | 置信度 |", "|---|---|---|---|"]
    for name, label in FIELD_LABELS.items():
        f = getattr(fields, name)
        value = "缺失" if f.value is None else str(f.value)
        quote = "-" if not f.quote else f.quote[:40]
        conf = "-" if f.value is None else f"{f.confidence:.2f}"
        lines.append(f"| {label} | {value} | {quote} | {conf} |")
    return "\n".join(lines)


def build_template_report(fields: ContractFields, hits: list[dict],
                          meta: dict | None = None) -> str:
    """确定性模板报告：无 LLM 也可用（兜底路径，保证服务永远有产出）。"""
    meta = meta or {}
    level = risk_level(hits)
    parts = [f"# 合同审查报告：{meta.get('file', '未命名合同')}", ""]
    parts.append(f"**风险分级：{level}**")
    parts.append(f"- 解析方式：{meta.get('source', '-')}　条款数：{meta.get('clause_count', '-')}"
                 f"　抽取+审核耗时：{meta.get('elapsed_sec', '-')}s")
    parts.append("")
    parts.append("## 一、红线命中情况")
    if hits:
        parts.append("| 级别 | 规则 | 说明 |")
        parts.append("|---|---|---|")
        for h in hits:
            parts.append(f"| {_SEVERITY_LABEL.get(h['severity'], h['severity'])} "
                         f"| {h['name']}（{h['id']}） | {h['message']} |")
    else:
        parts.append("全部红线规则比对通过，无命中项。")
    parts.append("")
    parts.append("## 二、关键字段抽取结果（含原文溯源）")
    parts.append(_field_table(fields))
    parts.append("")
    parts.append("## 三、审查结论")
    if level == "高危":
        parts.append("存在高危红线命中，**建议退回业务方整改后再审，整改前不得签署**。")
    elif level == "警告":
        parts.append("存在警告级风险，建议人工复核确认后再签署。")
    else:
        parts.append("关键字段完整、红线规则全部通过，可进入正常签署流程（人工抽查制）。")
    return "\n".join(parts)


def build_report(fields: ContractFields, hits: list[dict],
                 meta: dict | None = None, use_llm: bool = True) -> str:
    """CoT Markdown 审查报告：优先 LLM 生成推理叙述，失败降级模板。"""
    meta = meta or {}
    template = build_template_report(fields, hits, meta)
    if not use_llm or not hits:
        return template  # 无命中时模板已足够，省一次调用
    try:
        from extractor.extract import call_llm_json
        from extractor.prompts import SYSTEM_PROMPT  # noqa: F401 复用端点配置

        level = risk_level(hits)
        hits_desc = "\n".join(
            f"- [{h['severity']}] {h['name']}（{h['id']}）：{h['message']}"
            for h in hits)
        fields_desc = "\n".join(
            f"- {FIELD_LABELS[n]}: {getattr(fields, n).value}"
            for n in FIELD_LABELS)
        prompt = (
            "你是采购合同合规审查助手。以下是系统对一份合同的红线比对结果和字段抽取结果，"
            "请按 CoT（逐步推理）写一份 Markdown 审查报告：先逐条分析每个命中风险"
            "（引用字段值说明为什么命中、业务影响是什么、给出整改建议），再给出综合结论。"
            "只输出 Markdown 正文，不要输出 JSON。\n\n"
            f"风险分级：{level}\n红线命中：\n{hits_desc}\n\n字段抽取结果：\n{fields_desc}"
        )
        raw = call_llm_json(
            [{"role": "system", "content": SYSTEM_PROMPT},
             {"role": "user", "content": prompt}],
            max_retries=1,
        )
        # LLM 输出只是推理叙述，头部信息与字段溯源表仍由模板保证（结构可靠）
        narrative = raw.strip()
        if narrative.startswith("```"):
            narrative = narrative.strip("`").removeprefix("markdown").strip()
        header = template.split("## 二、")[0]
        table = "## 二、关键字段抽取结果（含原文溯源）" + template.split("## 二、")[1]
        logger.info("[报告] LLM CoT 报告生成成功")
        return header + narrative + "\n\n" + table
    except Exception as e:  # noqa: BLE001 降级不阻断
        logger.warn("[报告] LLM 报告生成失败，降级模板: %.200s", str(e))
        return template
