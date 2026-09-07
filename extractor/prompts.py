# -*- coding: utf-8 -*-
"""Prompt 构造：系统提示（角色+字段定义+输出规则）+ Few-shot 示例 + JSON 输出指令。

设计要点（面试话术）：
- Few-shot 2 例分别演示"前导信息抽取"与"空字段不编造"，压制幻觉
- 每字段强制附 quote（逐字原文引用），quote 校验失败重试、再失败置 null
- 抽取任务不需要深度推理，temperature=0，输出 JSON
"""

FIELD_DEFINITIONS = """\
1. buyer_name        甲方（需方）公司全称
2. supplier_name     乙方（供方）公司全称
3. amount            合同总金额，输出纯数字（单位：元），如 620000
4. payment_days      付款账期，输出纯数字（单位：天），如 90；仅指"多少日内支付货款"
5. penalty_rate      违约金比例，输出纯数字（百分比数值），如 15 表示 15%
6. delivery_date     交货日期，格式 YYYY-MM-DD
7. signing_date      签署日期，格式 YYYY-MM-DD
8. dispute_resolution 争议解决方式，简短概括，可选值：甲方所在地法院诉讼 / 乙方所在地法院诉讼 / 提交仲裁委员会仲裁 / 其他（概括原文）
9. countersign       会签状态，可选值：已会签 / 未会签；合同未提及会签时为 null"""

SYSTEM_PROMPT = f"""你是采购合同字段抽取引擎。输入是合同的一个片段（可能是一个条款或前导信息），请从中抽取以下字段。片段中没有的信息一律返回 null，禁止编造。

字段定义：
{FIELD_DEFINITIONS}

抽取规则：
1. 每个非 null 字段必须附带 quote：从片段原文中【逐字复制】的、能支持该字段值的连续片段（10~40 字）。quote 必须能在片段中找到，禁止改写、增删字符。
2. value 格式严格遵守字段定义；日期一律换算为 YYYY-MM-DD。
3. 输出纯 JSON，格式：{{"fields": {{"字段名": {{"value": ...}}  , "quote": ...}}}}，字段名只用上面 9 个名字；没有抽取到任何字段时输出 {{"fields": {{}}}}。
4. 不要输出 JSON 以外的任何内容。"""

# Few-shot 示例 1：前导信息段（演示 parties/日期抽取与无关字段置空）
_FEWSHOT_USER_1 = """合同片段：
合同编号：CG-2026-Demo
甲方（需方）：华辰智造（苏州）有限公司
乙方（供方）：江南轴承股份有限公司
签订日期：2026年3月5日

请抽取字段并输出 JSON。"""

_FEWSHOT_ASSISTANT_1 = """{"fields": {"buyer_name": {"value": "华辰智造（苏州）有限公司", "quote": "甲方（需方）：华辰智造（苏州）有限公司"}, "supplier_name": {"value": "江南轴承股份有限公司", "quote": "乙方（供方）：江南轴承股份有限公司"}, "signing_date": {"value": "2026-03-05", "quote": "签订日期：2026年3月5日"}}}"""

# Few-shot 示例 2：违约金条款（演示 value 数字化 + 无关字段不编造）
_FEWSHOT_USER_2 = """合同片段：
第四条 违约责任
任何一方违反本合同约定的，违约方应按合同总金额的15%向守约方支付违约金；违约金不足以弥补守约方实际损失的，守约方有权继续追偿。

请抽取字段并输出 JSON。"""

_FEWSHOT_ASSISTANT_2 = """{"fields": {"penalty_rate": {"value": "15", "quote": "按合同总金额的15%向守约方支付违约金"}}}"""


def build_clause_messages(clause_text: str) -> list[dict]:
    """单条款抽取消息：system + 2 个 few-shot + 用户片段。"""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _FEWSHOT_USER_1},
        {"role": "assistant", "content": _FEWSHOT_ASSISTANT_1},
        {"role": "user", "content": _FEWSHOT_USER_2},
        {"role": "assistant", "content": _FEWSHOT_ASSISTANT_2},
        {"role": "user", "content": f"合同片段：\n{clause_text}\n\n请抽取字段并输出 JSON。"},
    ]


def build_retry_messages(clause_text: str, error_msg: str) -> list[dict]:
    """quote/schema 校验失败后的重试消息：把错误信息喂回去让模型自己修。"""
    messages = build_clause_messages(clause_text)
    messages.append({"role": "user", "content":
                     f"上次输出未通过校验：{error_msg}\n"
                     "请修正后重新输出 JSON。quote 必须是片段原文的逐字连续子串。"})
    return messages
