# -*- coding: utf-8 -*-
"""规则引擎：YAML 红线配置 + 通用比对器。

职责分离原则（面试话术）："确定性判断归规则，语义理解归模型，谁也不越界"——
规则引擎只消费抽取后的结构化字段，字段路径 + 操作符 + 阈值，命中即风险。
"""
import os
import threading

import yaml

from common import config
from common.log import get_logger
from extractor.schema import ContractFields

logger = get_logger("rules")

_lock = threading.Lock()
_rules_cache: list[dict] | None = None


def load_rules(path: str | None = None) -> list[dict]:
    """加载 rules.yaml（带缓存；规则文件外置，改红线不用动代码）。"""
    global _rules_cache
    path = path or config.RULES_YAML
    with _lock:
        if _rules_cache is not None and path == config.RULES_YAML:
            return _rules_cache
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        rules = data.get("rules", [])
        _rules_cache = rules if path == config.RULES_YAML else rules
        logger.info("[规则] 加载 %d 条红线规则（%s）", len(rules), os.path.basename(path))
        return rules


def _resolve(fields: ContractFields, field_path: str):
    """解析字段路径（如 payment_days.value）→ 取值；异常视为 None。"""
    obj = fields
    for part in field_path.split("."):
        if obj is None:
            return None
        if isinstance(obj, dict):
            obj = obj.get(part)
        else:
            obj = getattr(obj, part, None)
    return obj


def _match_condition(fields: ContractFields, cond: dict) -> bool:
    actual = _resolve(fields, cond["field"])
    op, target = cond["op"], cond.get("value")

    if op == "missing":
        return actual is None or actual == ""
    if op == "not_missing":
        return actual is not None and actual != ""
    if actual is None:  # 比较类操作符遇 None 一律不命中
        return False
    try:
        if op == "gt":
            return float(actual) > float(target)
        if op == "gte":
            return float(actual) >= float(target)
        if op == "lt":
            return float(actual) < float(target)
        if op == "lte":
            return float(actual) <= float(target)
    except (TypeError, ValueError):
        return False
    if op == "eq":
        return str(actual) == str(target)
    if op == "neq":
        return str(actual) != str(target)
    if op == "eq_str":
        return str(actual).strip() == str(target).strip()
    logger.warn("[规则] 未知操作符 %s，条件按不命中处理", op)
    return False


def _fill_message(message: str, fields: ContractFields) -> str:
    """把 {field.path} 占位符替换为实际字段值。"""
    import re

    def repl(m: re.Match) -> str:
        v = _resolve(fields, m.group(1))
        return "缺失" if v is None else str(v)

    return re.sub(r"\{([\w.]+)\}", repl, message)


def evaluate_rules(fields: ContractFields,
                   rules: list[dict] | None = None) -> list[dict]:
    """比对全部规则，返回命中列表 [{id, name, severity, message, conditions}]。"""
    rules = rules if rules is not None else load_rules()
    hits = []
    for rule in rules:
        conds = rule.get("conditions", [])
        if conds and all(_match_condition(fields, c) for c in conds):
            hits.append({
                "id": rule["id"],
                "name": rule["name"],
                "severity": rule["severity"],
                "message": _fill_message(rule.get("message", rule["name"]), fields),
                "conditions": conds,
            })
            logger.info("[命中] %s %s（%s）", rule["id"], rule["name"], rule["severity"])
    if not hits:
        logger.info("[规则] 无红线命中")
    return hits


def risk_level(hits: list[dict]) -> str:
    """风险分级：任一高危→高危；任一警告→警告；否则通过。"""
    severities = {h["severity"] for h in hits}
    if "high" in severities:
        return "高危"
    if "warning" in severities:
        return "警告"
    return "通过"
