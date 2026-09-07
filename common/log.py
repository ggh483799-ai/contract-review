# -*- coding: utf-8 -*-
"""日志规范模块（对齐全局规则 1.2）。

格式：[时间戳] [级别] [模块] 消息
存储：./logs/，单文件 10MB 轮转，保留 5 份。
"""
import logging
import os
from logging.handlers import RotatingFileHandler

# 日志开关（代码开头必须设置，见全局规则 1.1 / 1.2）
LOG_ENABLED = True
LOG_LEVEL = logging.INFO

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(_PROJECT_ROOT, "logs")

_FORMATTER = logging.Formatter(
    "[%(asctime)s] [%(levelname)s] [%(module)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_configured = False


def _setup_root() -> None:
    """初始化根 logger（控制台 + 轮转文件），进程内仅执行一次。"""
    global _configured
    if _configured or not LOG_ENABLED:
        return
    os.makedirs(LOG_DIR, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(LOG_LEVEL)
    console = logging.StreamHandler()
    console.setFormatter(_FORMATTER)
    root.addHandler(console)
    file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, "contract-review.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(_FORMATTER)
    root.addHandler(file_handler)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """获取带统一格式的模块 logger。日志关闭时返回静默 logger。"""
    if not LOG_ENABLED:
        logging.disable(logging.CRITICAL)
        return logging.getLogger(name)
    _setup_root()
    return logging.getLogger(name)
