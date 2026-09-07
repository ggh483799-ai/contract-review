# -*- coding: utf-8 -*-
"""LLM 结构化抽取核心（阶段 3）。

链路：逐条款调用 LLM（JSON mode）→ Pydantic 校验（失败带错误重试，最多 2 次）
→ quote 原文校验（归一化比对；失败重试 1 次，再失败丢弃该字段）
→ 金额/日期/天数归一化（正则 + LLM 双通道，正则优先）
→ 按条款文档顺序合并（先出现且 quote 完整者胜出）。
"""
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from openai import OpenAI

from common import config
from common.log import get_logger
from extractor.prompts import build_clause_messages, build_retry_messages
from extractor.schema import ClauseExtractOut, ContractFields

logger = get_logger("extract")

FIELD_NAMES = list(ContractFields.model_fields.keys())

_client: OpenAI | None = None
_throttle_lock = threading.Lock()
_last_call_ts = 0.0


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not config.LLM_API_KEY:
            raise RuntimeError("LLM_API_KEY 未配置，请检查 .env")
        _client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
    return _client


def _throttle() -> None:
    """全局限流：两次请求发起间隔不低于 EXTRACT_INTERVAL_SEC（硅基流动限流预案）。"""
    global _last_call_ts
    with _throttle_lock:
        wait = config.EXTRACT_INTERVAL_SEC - (time.time() - _last_call_ts)
        if wait > 0:
            time.sleep(wait)
        _last_call_ts = time.time()


def call_llm_json(messages: list[dict], max_retries: int | None = None) -> str:
    """调用 LLM 并返回原始文本；网络/限流错误指数退避重试。"""
    retries = config.LLM_MAX_RETRIES if max_retries is None else max_retries
    client = _get_client()
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        _throttle()
        try:
            resp = client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=messages,
                temperature=config.LLM_TEMPERATURE,
                max_tokens=2048,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:  # noqa: BLE001 网络/限流类异常统一重试
            last_err = e
            backoff = 2 ** attempt
            logger.warn("[LLM] 请求失败（第 %d 次）：%.200s，%ds 后重试",
                        attempt + 1, str(e), backoff)
            time.sleep(backoff)
    raise RuntimeError(f"LLM 调用连续失败 {retries + 1} 次: {last_err}")


# ------------------------------------------------------------- quote 校验 ---

def _normalize_for_match(s: str) -> str:
    """quote 比对归一化：去空白、全角￥→¥、去千分位逗号（兼容 OCR 噪声）。"""
    s = re.sub(r"\s+", "", s)
    s = s.replace("￥", "¥").replace(",", "").replace("，", "")
    return s


def quote_in_text(quote: str, text: str) -> bool:
    """quote 原文校验：归一化后必须仍是原文子串（防幻觉核心闸门）。"""
    if not quote:
        return False
    return _normalize_for_match(quote) in _normalize_for_match(text)


# ------------------------------------------------------------ 值归一化 ------

_DATE_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
_AMOUNT_RE = re.compile(r"[¥￥]\s*([\d,]+(?:\.\d+)?)")
_AMOUNT_WAN_RE = re.compile(r"(\d+(?:\.\d+)?)\s*万")
_DAYS_RE = re.compile(r"在\s*(\d+)\s*日内[^，。；]{0,10}支付")
_RATE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def normalize_value(field: str, llm_value: str | None,
                    clause_text: str) -> str | int | float | None:
    """归一化：正则通道优先，LLM 值兜底（金额大写/格式转换不出错的关键）。"""
    if llm_value is None or str(llm_value).strip().lower() in ("", "null", "none"):
        return None
    llm_value = str(llm_value).strip()

    if field == "amount":
        m = _AMOUNT_RE.search(clause_text)
        if m:
            return int(float(m.group(1).replace(",", "")))
        m = _AMOUNT_WAN_RE.search(clause_text)
        if m and int(float(m.group(1)) * 10000) == _try_number(llm_value):
            return int(float(m.group(1)) * 10000)
        return _try_number(llm_value)

    if field == "payment_days":
        m = _DAYS_RE.search(clause_text)
        if m:
            return int(m.group(1))
        return _try_number(llm_value)

    if field == "penalty_rate":
        rates = [float(x) for x in _RATE_RE.findall(clause_text)]
        v = _try_number(llm_value)
        if rates:
            if v is not None and v in rates:
                return v  # LLM 值与原文 % 一致
            return rates[0]  # 正则优先
        return v

    if field in ("delivery_date", "signing_date"):
        m = _DATE_RE.search(clause_text)
        if m:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        m2 = re.search(r"(\d{4})-(\d{2})-(\d{2})", llm_value)
        return m2.group(0) if m2 else llm_value

    return llm_value


def _try_number(s: str | None) -> float | int | None:
    try:
        v = float(str(s).replace(",", ""))
        return int(v) if v == int(v) else v
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------- 单条款抽取 ------

def extract_clause(clause_text: str) -> dict[str, dict]:
    """单条款抽取：LLM → schema 校验 → quote 校验 → 归一化。

    返回 {字段名: {"value": 归一化值, "quote": 原文引用, "confidence": 置信度}}，
    quote 校验失败重试 1 次，再失败该字段直接丢弃（不进合并）。
    """
    messages = build_clause_messages(clause_text)
    error_hint = None
    for attempt in range(config.LLM_MAX_RETRIES + 1):
        if error_hint is not None:
            messages = build_retry_messages(clause_text, error_hint)
        raw = call_llm_json(messages)
        # ① JSON 解析 + Pydantic 校验（schema 是契约）
        try:
            data = json.loads(raw)
            parsed = ClauseExtractOut.model_validate(data)
        except Exception as e:  # noqa: BLE001
            error_hint = f"JSON/schema 校验失败: {e}"
            logger.warn("[抽取] schema 校验失败（第 %d 次）: %.120s", attempt + 1, str(e))
            continue
        # ② quote 原文校验 + ③ 值归一化
        out: dict[str, dict] = {}
        failed_quotes = []
        for name, rf in parsed.fields.items():
            if name not in FIELD_NAMES or rf.value is None:
                continue
            if not quote_in_text(rf.quote or "", clause_text):
                failed_quotes.append(f"{name}: quote={rf.quote!r} 不在原文中")
                continue
            value = normalize_value(name, rf.value, clause_text)
            if value is None:
                continue
            out[name] = {"value": value, "quote": rf.quote, "confidence": 0.95}
        if out:
            return out
        if failed_quotes:
            error_hint = "quote 原文校验失败：" + "；".join(failed_quotes)
            logger.warn("[抽取] quote 校验失败（第 %d 次）：%s", attempt + 1, error_hint)
            continue
        return {}  # 模型确认该片段无字段
    logger.warn("[抽取] 条款抽取重试耗尽，丢弃该条款字段")
    return {}


# ------------------------------------------------------------ 合并主入口 ----

def extract_contract_fields(clauses: list, workers: int | None = None) -> ContractFields:
    """整份合同抽取：条款级并发（限流）+ 文档顺序合并（先出现者胜出）。"""
    workers = workers or config.EXTRACT_WORKERS
    if workers <= 1:
        results = [extract_clause(c.text) for c in clauses]
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(extract_clause, [c.text for c in clauses]))

    merged: dict[str, dict] = {}
    for res in results:  # results 与 clauses 同序 = 文档顺序
        for name, item in res.items():
            if name not in merged:  # 先出现且 quote 完整的胜出
                merged[name] = item
    dropped = [n for n in FIELD_NAMES if n not in merged]
    if dropped:
        logger.info("[合并] 未能抽取的字段（置 null 低置信）: %s", ",".join(dropped))

    fields = ContractFields()
    for name, item in merged.items():
        setattr(fields, name, type(getattr(fields, name))(**item))
    return fields
