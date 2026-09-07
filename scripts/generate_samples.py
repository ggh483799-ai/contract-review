# -*- coding: utf-8 -*-
"""仿真采购合同样本生成器（阶段 1：数据准备）。

产出：
- data/samples/*.pdf        30 份中文仿真采购合同（文本型 + 扫描件模拟）
- eval/annotations/*.json   每份样本的 ground truth 标注（字段值 + 原文引用）

设计要点：
- 文本 PDF 用 reportlab + STSong-Light（CID 字体，免字体文件）
- 扫描件模拟：PyMuPDF 把文本 PDF 栅格化为图片再封回 PDF（无文本层，逼 OCR 兜底）
- 故意埋点：账期超 60 天 / 违约金超 20% / 150 万未会签 / 字段缺失 / 付款条件模糊
- 标注 JSON 由生成过程直接产出，字段引用（quote）保证可在原文中精确命中
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import config
from common.log import get_logger

logger = get_logger("generate_samples")

# ---------------------------------------------------------------- 中文工具 ---

_CN_DIGITS = "零壹贰叁肆伍陆柒捌玖"
_CN_UNITS = ["", "拾", "佰", "仟"]
_CN_BIG = ["", "万", "亿"]


def _four_digit_to_cn(n: int) -> str:
    """1~9999 → 中文大写（含零处理），如 1501 → 壹仟伍佰零壹。"""
    out, got_nonzero, zero_pending = "", False, False
    for i in range(3, -1, -1):
        d = (n // 10 ** i) % 10
        if d == 0:
            if got_nonzero:
                zero_pending = True
        else:
            if zero_pending:
                out += "零"
                zero_pending = False
            out += _CN_DIGITS[d] + _CN_UNITS[i]
            got_nonzero = True
    return out


def cn_upper_amount(n: int) -> str:
    """整数元 → 人民币大写，如 1500000 → 壹佰伍拾万元整。"""
    if n <= 0:
        raise ValueError(f"金额必须为正整数: {n}")
    groups = []
    rest = n
    while rest > 0:
        groups.append(rest % 10000)
        rest //= 10000
    parts = []
    for idx in range(len(groups) - 1, -1, -1):
        g = groups[idx]
        if g == 0:
            continue
        seg = _four_digit_to_cn(g)
        if idx < len(groups) - 1 and g < 1000:
            seg = "零" + seg  # 组间补零：如 1000500 → 壹佰万零伍佰
        parts.append(seg + _CN_BIG[idx])
    return "".join(parts) + "元整"


_CN_NUMS = "零一二三四五六七八九十"


def cn_clause_num(n: int) -> str:
    """1~99 → 条款序号中文小写，如 11 → 十一。"""
    if n <= 10:
        return _CN_NUMS[n]
    if n < 20:
        return "十" + _CN_NUMS[n - 10]
    tens, ones = divmod(n, 10)
    return _CN_NUMS[tens] + "十" + (_CN_NUMS[ones] if ones else "")


def fmt_date_cn(y: int, m: int, d: int) -> str:
    return f"{y}年{m}月{d}日"


def fmt_date_iso(y: int, m: int, d: int) -> str:
    return f"{y:04d}-{m:02d}-{d:02d}"


# ---------------------------------------------------------------- 配置定义 ---

BUYERS = [
    "华辰智造（苏州）有限公司",
    "中恒电子科技有限公司",
    "蓝海精密仪器股份有限公司",
    "盛世云数据有限公司",
    "鼎盛机械制造有限公司",
    "恒信医疗器械有限公司",
]
SUPPLIERS = [
    "江南轴承股份有限公司",
    "鑫泰五金制品有限公司",
    "迅捷自动化设备有限公司",
    "天工精密模具有限公司",
    "华宇电子元器件有限公司",
    "金石工业材料有限公司",
]
GOODS = [
    "高精度伺服电机",
    "工业级传感器模组",
    "自动化装配线组件",
    "精密轴承",
    "工业控制柜",
    "检测仪器设备及配件",
]


def cfg(cid, buyer_i, supplier_i, goods_i, amount, payment_days, penalty_rate,
        delivery, signing, dispute=True, countersign=None, scanned=False,
        expected="pass", planted=None):
    """一份样本合同的定义。payment_days: int | 'fuzzy'（模糊付款）| None（缺失）。"""
    return {
        "id": cid,
        "buyer": BUYERS[buyer_i],
        "supplier": SUPPLIERS[supplier_i],
        "goods": GOODS[goods_i],
        "amount": amount,
        "payment_days": payment_days,
        "penalty_rate": penalty_rate,
        "delivery": delivery,
        "signing": signing,
        "dispute": dispute,
        "countersign": countersign,  # None=未提及 / "yes"=已会签 / "no"=未会签
        "scanned": scanned,
        "expected": expected,
        "planted": planted or [],
    }


CONFIGS = [
    # ---- 12 份核心样本（含全部埋点类型）----
    cfg("C01", 0, 0, 0, 480000, 45, 10.0, (2026, 9, 30), (2026, 8, 10), expected="pass"),
    cfg("C02", 1, 1, 1, 620000, 90, 15.0, (2026, 10, 15), (2026, 8, 12), scanned=True,
        expected="high", planted=["账期90天>60天红线"]),
    cfg("C03", 2, 2, 2, 350000, 75, 8.0, (2026, 9, 20), (2026, 8, 5),
        expected="high", planted=["账期75天>60天红线"]),
    cfg("C04", 3, 3, 3, 260000, 30, 25.0, (2026, 10, 8), (2026, 8, 18), scanned=True,
        expected="high", planted=["违约金25%>20%红线"]),
    cfg("C05", 4, 4, 4, 540000, 50, 22.0, (2026, 11, 10), (2026, 8, 20),
        expected="high", planted=["违约金22%>20%红线"]),
    cfg("C06", 5, 5, 5, 1500000, 40, 12.0, (2026, 12, 20), (2026, 8, 25),
        countersign="no", scanned=True, expected="high", planted=["金额150万超100万且未会签"]),
    cfg("C07", 0, 1, 2, 300000, 35, None, (2026, 9, 25), (2026, 8, 8), scanned=True,
        expected="warning", planted=["违约金条款缺失"]),
    cfg("C08", 1, 2, 3, 420000, 40, 10.0, (2026, 10, 30), (2026, 8, 15), dispute=False,
        expected="warning", planted=["无争议解决条款"]),
    cfg("C09", 2, 3, 4, 980000, 65, 18.0, (2026, 11, 15), (2026, 8, 22),
        expected="high", planted=["账期65天>60天红线"]),
    cfg("C10", 3, 4, 5, 1200000, 60, 20.0, (2026, 12, 1), (2026, 8, 28),
        countersign="yes", expected="pass", planted=[]),
    cfg("C11", 4, 5, 0, 150000, "fuzzy", 8.0, (2026, 9, 18), (2026, 8, 3),
        expected="warning", planted=["付款条件模糊无明确账期"]),
    cfg("C12", 5, 0, 1, 800000, 55, 15.0, (2026, 10, 25), (2026, 8, 30),
        expected="pass"),
    # ---- 18 份模板变体（评估集扩充）----
    cfg("V13", 1, 3, 2, 90000, 30, 5.0, (2026, 9, 12), (2026, 8, 6), expected="pass"),
    cfg("V14", 2, 4, 3, 660000, 90, 10.0, (2026, 10, 20), (2026, 8, 14),
        expected="high", planted=["账期90天>60天红线"]),
    cfg("V15", 3, 5, 4, 200000, "fuzzy", 10.0, (2026, 9, 28), (2026, 8, 9),
        expected="warning", planted=["付款条件模糊无明确账期"]),
    cfg("V16", 4, 0, 5, 380000, 45, 30.0, (2026, 11, 5), (2026, 8, 16),
        expected="high", planted=["违约金30%>20%红线"]),
    cfg("V17", 5, 1, 0, 120000, 40, 12.0, (2026, 10, 2), (2026, 8, 11), expected="pass"),
    cfg("V18", 0, 2, 1, 560000, 50, 15.0, (2026, 11, 25), (2026, 8, 19), dispute=False,
        expected="warning", planted=["无争议解决条款"]),
    cfg("V19", 1, 3, 2, 720000, 75, 18.0, (2026, 12, 8), (2026, 8, 21), scanned=True,
        expected="high", planted=["账期75天>60天红线"]),
    cfg("V20", 2, 4, 3, 1350000, 60, 20.0, (2026, 12, 15), (2026, 8, 26),
        countersign="yes", expected="pass"),
    cfg("V21", 3, 5, 4, 240000, 35, None, (2026, 9, 22), (2026, 8, 7),
        expected="warning", planted=["违约金条款缺失"]),
    cfg("V22", 4, 0, 5, 1600000, 45, 15.0, (2026, 12, 28), (2026, 8, 29),
        countersign="no", expected="high", planted=["金额160万超100万且未会签"]),
    cfg("V23", 5, 1, 0, 65000, 28, 6.0, (2026, 9, 15), (2026, 8, 4), expected="pass"),
    cfg("V24", 0, 2, 1, 310000, 40, 25.0, (2026, 10, 18), (2026, 8, 13), scanned=True,
        expected="high", planted=["违约金25%>20%红线"]),
    cfg("V25", 1, 3, 2, 450000, 55, 16.0, (2026, 11, 8), (2026, 8, 17), expected="pass"),
    cfg("V26", 2, 4, 3, 580000, 95, 10.0, (2026, 12, 22), (2026, 8, 23),
        expected="high", planted=["账期95天>60天红线"]),
    cfg("V27", 3, 5, 4, 180000, "fuzzy", 9.0, (2026, 10, 6), (2026, 8, 24),
        expected="warning", planted=["付款条件模糊无明确账期"]),
    cfg("V28", 4, 0, 5, 260000, "fuzzy", 12.0, (2026, 11, 18), (2026, 8, 27), scanned=True,
        expected="warning", planted=["付款条件模糊无明确账期"]),
    cfg("V29", 5, 1, 0, 850000, 45, 14.0, (2026, 10, 28), (2026, 8, 31), expected="pass"),
    cfg("V30", 0, 3, 1, 430000, 88, 16.0, (2026, 12, 5), (2026, 9, 1),
        expected="high", planted=["账期88天>60天红线"]),
]

# ---------------------------------------------------------------- 文本构建 ---


def build_contract_text(c: dict) -> tuple[str, dict]:
    """按配置构建合同全文，返回 (全文, 各字段 quote 映射)。"""
    y, m, d = c["signing"]
    dy, dm, dd = c["delivery"]
    quotes = {}
    lines = [
        f"合同编号：CG-2026-{c['id']}",
        f"甲方（需方）：{c['buyer']}",
        f"乙方（供方）：{c['supplier']}",
        f"签订日期：{fmt_date_cn(y, m, d)}",
        "",
        f"根据《中华人民共和国民法典》及相关法律法规，甲乙双方本着平等自愿、"
        f"诚实信用的原则，就甲方向乙方采购{c['goods']}事宜协商一致，达成如下条款：",
        "",
    ]
    quotes["buyer_name"] = f"甲方（需方）：{c['buyer']}"
    quotes["supplier_name"] = f"乙方（供方）：{c['supplier']}"
    quotes["signing_date"] = f"签订日期：{fmt_date_cn(y, m, d)}"

    upper = cn_upper_amount(c["amount"])
    no = 1

    def clause(title, body):
        nonlocal no
        lines.append(f"第{cn_clause_num(no)}条 {title}")
        lines.append(body)
        lines.append("")
        no += 1

    # 第一条（编号随缺失条款动态后移，模拟真实合同）
    clause("标的与金额",
           f"甲方向乙方采购{c['goods']}一批，具体规格型号以双方确认的订单为准。"
           f"本合同总金额为人民币{upper}（小写：¥{c['amount']:,}.00），含税，税率13%。")
    quotes["amount"] = f"（小写：¥{c['amount']:,}.00）"

    if c["payment_days"] is None:
        pass  # 付款条款整体缺失（字段缺失埋点）
    elif c["payment_days"] == "fuzzy":
        clause("付款方式",
               "货款于货物验收合格后支付，具体付款时间及比例由双方另行协商确定。"
               "乙方须在收款前开具13%增值税专用发票。")
    else:
        days = c["payment_days"]
        clause("付款方式",
               f"乙方交货并经甲方验收合格后，甲方在{days}日内向乙方支付合同总价款的100%，"
               f"乙方须在收款前开具13%增值税专用发票。")
        quotes["payment_days"] = f"甲方在{days}日内向乙方支付"

    clause("交货",
           f"乙方应于{fmt_date_cn(dy, dm, dd)}前将全部货物送达甲方指定仓库并通知甲方收货，"
           f"运费由乙方承担。")
    quotes["delivery_date"] = f"应于{fmt_date_cn(dy, dm, dd)}前"

    clause("验收",
           "货到后甲方应在7个工作日内按双方确认的技术标准完成验收，"
           "验收不合格的，乙方应在5个工作日内补货或换货。")

    if c["penalty_rate"] is not None:
        rate = c["penalty_rate"]
        rate_str = str(int(rate)) if rate == int(rate) else str(rate)
        clause("违约责任",
               f"任何一方违反本合同约定的，违约方应按合同总金额的{rate_str}%向守约方支付违约金；"
               f"违约金不足以弥补守约方实际损失的，守约方有权继续追偿。")
        quotes["penalty_rate"] = f"按合同总金额的{rate_str}%"

    if c["dispute"]:
        clause("争议解决",
               "因本合同引起的或与本合同有关的争议，双方应友好协商解决；协商不成的，"
               "任何一方均可向甲方所在地有管辖权的人民法院提起诉讼。")
        quotes["dispute_resolution"] = "向甲方所在地有管辖权的人民法院提起诉讼"

    clause("合同生效",
           "本合同自双方法定代表人或授权代表签字并加盖公章之日起生效。"
           "本合同一式两份，甲乙双方各执一份，具有同等法律效力。")

    if c["countersign"] is not None:
        cs_text = ("已会签（会签编号 HQ-2026-" + c["id"] + "）"
                   if c["countersign"] == "yes" else "未会签")
        lines.append("审批与会签")
        lines.append(f"会签记录：{cs_text}")
        lines.append("")
        quotes["countersign"] = f"会签记录：{cs_text}"

    lines.append("（以下无正文）")
    return "\n".join(lines), quotes


def build_annotation(c: dict, quotes: dict) -> dict:
    """由配置直接产出 ground truth 标注（值 + 引用）。"""
    y, m, d = c["signing"]
    dy, dm, dd = c["delivery"]
    days = c["payment_days"]
    fields = {
        "buyer_name": {"value": c["buyer"], "quote": quotes.get("buyer_name")},
        "supplier_name": {"value": c["supplier"], "quote": quotes.get("supplier_name")},
        "amount": {"value": c["amount"], "quote": quotes.get("amount")},
        "payment_days": {"value": days if isinstance(days, int) else None,
                         "quote": quotes.get("payment_days")},
        "penalty_rate": {"value": c["penalty_rate"], "quote": quotes.get("penalty_rate")},
        "delivery_date": {"value": fmt_date_iso(dy, dm, dd), "quote": quotes.get("delivery_date")},
        "signing_date": {"value": fmt_date_iso(y, m, d), "quote": quotes.get("signing_date")},
        "dispute_resolution": {"value": "甲方所在地法院诉讼" if c["dispute"] else None,
                               "quote": quotes.get("dispute_resolution")},
        "countersign": {"value": ({"yes": "已会签", "no": "未会签"}.get(c["countersign"])),
                        "quote": quotes.get("countersign")},
    }
    return {
        "id": c["id"],
        "file": f"{c['id']}.pdf",
        "source": "scanned" if c["scanned"] else "text",
        "expected_risk": c["expected"],
        "planted": c["planted"],
        "fields": fields,
    }


# ---------------------------------------------------------------- PDF 渲染 ---


def render_text_pdf(text: str, out_path: str) -> None:
    """reportlab 渲染中文文本 PDF（STSong-Light CID 字体，免字体文件）。"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    body = ParagraphStyle(
        "body", fontName="STSong-Light", fontSize=10.5, leading=19,
        wordWrap="CJK", spaceAfter=4,
    )
    title = ParagraphStyle(
        "title", parent=body, fontSize=16, leading=24, alignment=1, spaceAfter=14,
    )
    doc = SimpleDocTemplate(
        out_path, pagesize=A4,
        leftMargin=25 * mm, rightMargin=25 * mm,
        topMargin=22 * mm, bottomMargin=22 * mm,
    )
    story = [Paragraph("采购合同", title)]
    for block in text.split("\n"):
        if block.strip():
            story.append(Paragraph(block.replace("&", "&amp;").replace("<", "&lt;"), body))
        else:
            story.append(Spacer(1, 6))
    doc.build(story)


def to_scanned(src_path: str, dst_path: str, dpi: int = 150) -> None:
    """PyMuPDF 把文本 PDF 栅格化为图片再封回 PDF（无文本层，模拟扫描件）。"""
    import fitz  # PyMuPDF

    src = fitz.open(src_path)
    dst = fitz.open()
    for page in src:
        pix = page.get_pixmap(dpi=dpi)
        img = pix.tobytes("png")
        new_page = dst.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(new_page.rect, stream=img)
    dst.save(dst_path, deflate=True)
    dst.close()
    src.close()


# ---------------------------------------------------------------- 主流程 ---


def main() -> None:
    os.makedirs(config.SAMPLES_DIR, exist_ok=True)
    os.makedirs(config.EVAL_ANNOTATIONS_DIR, exist_ok=True)
    import tempfile

    tmp_dir = tempfile.mkdtemp(prefix="contract_gen_")
    logger.info("[开始] 生成 %d 份仿真合同样本", len(CONFIGS))
    stats = {"text": 0, "scanned": 0}
    for c in CONFIGS:
        text, quotes = build_contract_text(c)
        # 自检：所有 quote 必须能在全文中精确命中（防标注幻觉）
        for field, quote in quotes.items():
            if quote not in text:
                raise AssertionError(f"{c['id']} 字段 {field} 引用无法在原文命中: {quote}")
        tmp_pdf = os.path.join(tmp_dir, f"{c['id']}_tmp.pdf")
        render_text_pdf(text, tmp_pdf)
        out_pdf = os.path.join(config.SAMPLES_DIR, f"{c['id']}.pdf")
        if c["scanned"]:
            to_scanned(tmp_pdf, out_pdf)
            stats["scanned"] += 1
        else:
            shutil.move(tmp_pdf, out_pdf)
            stats["text"] += 1
        anno = build_annotation(c, quotes)
        anno_path = os.path.join(config.EVAL_ANNOTATIONS_DIR, f"{c['id']}.json")
        with open(anno_path, "w", encoding="utf-8") as f:
            json.dump(anno, f, ensure_ascii=False, indent=2)
        logger.info("[样本] %s 生成完成 source=%s expected=%s", c["id"],
                    anno["source"], c["expected"])
    logger.info("[完成] 文本型 %d 份 + 扫描件 %d 份，输出目录 %s",
                stats["text"], stats["scanned"], config.SAMPLES_DIR)


if __name__ == "__main__":
    main()
