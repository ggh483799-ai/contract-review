# -*- coding: utf-8 -*-
"""条款切分器：锚点正则切段 + 跨页/换行自然合并。

设计：先拼接全文（跨页条款天然连续），再按 `第X条` 锚点切分；
条款号若出现在行中间（如"……。第七条 争议解决："）同样能切开。
无编号的前导段落（甲乙方、签订日期等）归入"其他条款"参与抽取。
MVP 阶段用确定性规则解决 80% 的问题，AI 留给真正需要语义的部分。
"""
import re
from dataclasses import dataclass, field

from common.log import get_logger

logger = get_logger("segmenter")

# 锚点：第 + 中文/阿拉伯数字 + 条（后跟标题或冒号）
_ANCHOR = re.compile(r"第[零〇一二三四五六七八九十百千0-9]+条")


@dataclass
class Clause:
    no: str | None  # 条款号（如 "第一条"），无编号段落为 None
    title: str      # 标题（如 "标的与金额"），无编号段落为 "其他条款"
    text: str       # 条款正文（含标题行）

    def __post_init__(self) -> None:
        pass


def _clean_text(raw: str) -> str:
    """文本清洗：去多余空白行、合并被 OCR 打断的硬换行。"""
    lines = [ln.strip() for ln in raw.splitlines()]
    lines = [ln for ln in lines if ln]
    out: list[str] = []
    for ln in lines:
        # 行以锚点开头 → 新结构行，直接保留
        if _ANCHOR.match(ln) or out == []:
            out.append(ln)
            continue
        # 行以明显的结构标题开头（如 "审批与会签"）→ 保留为独立行
        if ln in ("审批与会签", "（以下无正文）"):
            out.append(ln)
            continue
        # 否则视为上一行的延续（跨行/跨页合并）
        out[-1] = out[-1] + ln
    return "\n".join(out)


def segment_clauses(raw_text: str) -> list[Clause]:
    """全文 → List[Clause]；无编号段落归入 no=None 的"其他条款"。"""
    cleaned = _clean_text(raw_text)
    clauses: list[Clause] = []
    # 按锚点切分；每个锚点匹配处开启新条款
    matches = list(_ANCHOR.finditer(cleaned))
    if not matches:
        clauses.append(Clause(no=None, title="其他条款", text=cleaned))
        logger.info("[切分] 未发现条款锚点，整篇归入其他条款（%d 字符）", len(cleaned))
        return clauses

    preamble = cleaned[: matches[0].start()].strip()
    if preamble:
        clauses.append(Clause(no=None, title="其他条款", text=preamble))

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(cleaned)
        chunk = cleaned[start:end].strip()
        # 标题 = 锚点后到第一个分隔符（冒号/句号/换行）之间的短文本
        after = chunk[len(m.group()):].lstrip()
        head = re.split(r"[\s：:。；\n]", after, maxsplit=1)[0][:20]
        clauses.append(Clause(no=m.group(), title=head or "未命名条款", text=chunk))
    logger.info("[切分] 共切出 %d 个条款（含其他条款）", len(clauses))
    return clauses
