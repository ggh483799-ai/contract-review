# -*- coding: utf-8 -*-
"""服务层：FastAPI 入口（阶段 5）。

接口：
- POST /contracts/review    上传合同 PDF → 全链路审核 → JSON + Markdown 报告
- POST /contracts/feedback  人工复核修正落库（闭环数据沉淀）
- GET  /healthz             健康检查
"""
import time

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

from common.log import get_logger
from pipeline import review_contract
from rules.engine import load_rules
from storage import feedback_count, init_db, save_feedback, save_review

logger = get_logger("app")

app = FastAPI(title="采购合同智能审核系统", version="1.0.0")


@app.on_event("startup")
def _startup() -> None:
    init_db()
    load_rules()  # 预热规则缓存
    logger.info("[服务] 启动完成")


@app.middleware("http")
async def _timing_middleware(request, call_next):
    """请求耗时日志：服务可观测（运维背景落点）。"""
    start = time.time()
    response = await call_next(request)
    cost = (time.time() - start) * 1000
    logger.info("[HTTP] %s %s -> %d (%.0fms)", request.method, request.url.path,
                response.status_code, cost)
    return response


class FeedbackRequest(BaseModel):
    record_id: int
    corrections: dict[str, dict]  # {字段名: {value: ..., quote: ...}}
    comment: str = ""


@app.get("/healthz")
def healthz():
    return {"status": "ok", "feedback_records": feedback_count()}


@app.post("/contracts/review")
async def review_endpoint(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "仅支持 PDF 文件")
    import os
    import tempfile

    tmp_dir = tempfile.mkdtemp(prefix="contract_upload_")
    tmp_path = os.path.join(tmp_dir, os.path.basename(file.filename or "contract.pdf"))
    with open(tmp_path, "wb") as f:
        f.write(await file.read())
    logger.info("[审核] 收到上传：%s（%.1f KB）", file.filename, os.path.getsize(tmp_path) / 1024)
    try:
        result = review_contract(tmp_path)
    except Exception as e:  # noqa: BLE001
        logger.error("[审核] 处理失败: %.300s", str(e))
        raise HTTPException(500, f"合同审核失败: {e}") from e
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
    record_id = save_review(file.filename or "contract.pdf", result)
    return {"record_id": record_id, **result}


@app.post("/contracts/feedback")
def feedback_endpoint(body: FeedbackRequest):
    try:
        fid = save_feedback(body.record_id, body.corrections, body.comment)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return {"feedback_id": fid, "status": "saved"}
