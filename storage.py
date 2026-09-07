# -*- coding: utf-8 -*-
"""SQLite 存储：审核记录 + 人工复核修正（闭环数据沉淀）。"""
import json
import os
import sqlite3
import threading
import time

from common import config
from common.log import get_logger

logger = get_logger("storage")
_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _lock, _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS review_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                rule_hit_ids TEXT,
                fields_json TEXT,
                report_md TEXT,
                elapsed_sec REAL,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id INTEGER NOT NULL,
                corrections_json TEXT,
                comment TEXT,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (record_id) REFERENCES review_records(id)
            );
            """
        )
    logger.info("[存储] SQLite 初始化完成：%s", config.DB_PATH)


def save_review(file_name: str, result: dict) -> int:
    """保存一次审核记录，返回 record_id。"""
    with _lock, _connect() as conn:
        cur = conn.execute(
            "INSERT INTO review_records (file_name, risk_level, rule_hit_ids,"
            " fields_json, report_md, elapsed_sec) VALUES (?, ?, ?, ?, ?, ?)",
            (file_name, result["risk_level"],
             json.dumps([h["id"] for h in result["rule_hits"]], ensure_ascii=False),
             json.dumps(result["fields"], ensure_ascii=False),
             result["report_md"],
             result["meta"].get("elapsed_sec", 0)),
        )
        rid = cur.lastrowid
    logger.info("[存储] 审核记录落库 id=%s file=%s 分级=%s",
                rid, file_name, result["risk_level"])
    return rid


def save_feedback(record_id: int, corrections: dict, comment: str = "") -> int:
    """人工复核修正落库（复核数据沉淀，用于后续 Few-shot 样例库迭代）。"""
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT id FROM review_records WHERE id = ?", (record_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"审核记录不存在: {record_id}")
        cur = conn.execute(
            "INSERT INTO feedback (record_id, corrections_json, comment)"
            " VALUES (?, ?, ?)",
            (record_id, json.dumps(corrections, ensure_ascii=False), comment),
        )
        fid = cur.lastrowid
    logger.info("[存储] 复核反馈落库 id=%s record=%s 修正字段=%s",
                fid, record_id, list(corrections.keys()))
    return fid


def feedback_count() -> int:
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) c FROM feedback").fetchone()["c"]


if __name__ == "__main__":
    init_db()
    print("DB ready:", config.DB_PATH, "at", time.strftime("%H:%M:%S"))
