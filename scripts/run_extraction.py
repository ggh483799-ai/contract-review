# -*- coding: utf-8 -*-
"""批量抽取：对 data/samples 全量样本跑解析+抽取，结果缓存到 data/extracted/。

用法：python scripts/run_extraction.py [--ids C01,C02] [--workers 2]
"""
import argparse
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import config
from common.log import get_logger
from extractor.extract import extract_contract_fields
from parser.pdf_parser import parse_contract
from parser.segmenter import segment_clauses

logger = get_logger("run_extraction")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="", help="逗号分隔的样本 ID，空=全部")
    ap.add_argument("--workers", type=int, default=0, help="条款并发数，0=用配置默认")
    args = ap.parse_args()

    if args.workers > 0:
        config.EXTRACT_WORKERS = args.workers

    out_dir = os.path.join(config.DATA_DIR, "extracted")
    os.makedirs(out_dir, exist_ok=True)
    ids = [x for x in args.ids.split(",") if x]
    pdfs = sorted(glob.glob(os.path.join(config.SAMPLES_DIR, "*.pdf")))
    if ids:
        pdfs = [p for p in pdfs if os.path.splitext(os.path.basename(p))[0] in ids]

    t0 = time.time()
    ok = 0
    for pdf in pdfs:
        fid = os.path.splitext(os.path.basename(pdf))[0]
        started = time.time()
        parsed = parse_contract(pdf)
        clauses = segment_clauses(parsed["text"])
        fields = extract_contract_fields(clauses)
        payload = {
            "id": fid,
            "source": parsed["source"],
            "pages": parsed["pages"],
            "clause_count": len(clauses),
            "elapsed_sec": round(time.time() - started, 1),
            "fields": fields.to_display(),
        }
        out_path = os.path.join(out_dir, f"{fid}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        ok += 1
        logger.info("[进度] %s 完成（%s，%.1fs）", fid, parsed["source"],
                    payload["elapsed_sec"])
    logger.info("[完成] %d/%d 份抽取结果已缓存到 %s，总耗时 %.0fs",
                ok, len(pdfs), out_dir, time.time() - t0)


if __name__ == "__main__":
    main()
