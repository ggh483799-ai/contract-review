# -*- coding: utf-8 -*-
"""配置加载：从项目根 .env 读取 LLM 凭据与运行参数。"""
import os

from dotenv import load_dotenv

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

# LLM 配置（OpenAI 兼容端点，默认硅基流动 DeepSeek-V4-Flash）
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))

# 抽取并发与限流（硅基流动限流预案：加间隔 + 失败重试）
EXTRACT_WORKERS = int(os.getenv("EXTRACT_WORKERS", "2"))
EXTRACT_INTERVAL_SEC = float(os.getenv("EXTRACT_INTERVAL_SEC", "0.3"))

# 数据路径
DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
SAMPLES_DIR = os.path.join(DATA_DIR, "samples")
EVAL_ANNOTATIONS_DIR = os.path.join(_PROJECT_ROOT, "eval", "annotations")
RULES_YAML = os.path.join(_PROJECT_ROOT, "rules", "rules.yaml")
DB_PATH = os.path.join(DATA_DIR, "review.db")
