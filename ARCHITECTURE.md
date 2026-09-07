# 采购合同智能审核系统 — 架构说明（ARCHITECTURE.md）

> 定位：文档理解纵深项目。覆盖 JD 职责：Prompt/CoT 设计（主）、结构化输出约束、规则引擎与 LLM 的职责分离、人工复核闭环（LoRA 概念级）。

## 一、五层架构

```
[输入] 合同文件（文本型 PDF / 扫描件）
   ↓
[1] 解析层 parser/
    ├─ pdf_parser.py   文本层判定：pdfplumber 抽取，均值 <50 字符/页 → 判扫描件
    ├─ ocr.py          OCRProvider 抽象 → RapidOCRProvider（PyMuPDF 300dpi 渲染 → onnx 推理）
    └─ segmenter.py    条款切分：`第X条` 锚点正则，跨页/换行合并，无编号段落归"其他条款"
   ↓
[2] 抽取层 extractor/
    ├─ schema.py       9 个关键字段（value + quote + confidence），LLM 输出 Pydantic 校验
    ├─ prompts.py      System（角色+字段定义+输出规则）+ 2 个 Few-shot + JSON 指令
    └─ extract.py      逐条款调用 → schema 校验重试 → quote 原文校验 → 正则/LLM 双通道归一化 → 文档序合并
   ↓
[3] 规则引擎 rules/
    ├─ rules.yaml      10 条红线（账期≤60天 / 违约金≤20% / 金额>100万需会签 / 必填字段 / 争议条款…）
    └─ engine.py       通用比对器：field_path + op(gt/gte/eq/missing/eq_str…) + 阈值，AND 组合，severity 分层
   ↓
[4] 报告层 report/
    └─ report_gen.py   CoT Markdown 报告（LLM 推理叙述 + 确定性模板兜底；字段溯源表永远由模板生成）
   ↓
[5] 服务层
    ├─ app.py          POST /contracts/review、POST /contracts/feedback、GET /healthz，请求耗时日志
    ├─ pipeline.py     全链路编排
    └─ storage.py      SQLite：review_records / feedback（复核数据沉淀）
```

## 二、抽取层细节（本项目核心）

### 2.1 防幻觉三道闸门

1. **Prompt 约束**：字段定义 + "片段中没有的信息一律返回 null，禁止编造" + quote 必须"逐字复制的连续片段"。
2. **Schema 契约**：LLM 输出过 `ClauseExtractOut`（Pydantic）校验，失败带错误信息重试（最多 2 次）——"schema 是契约，LLM 自己修"。
3. **Quote 原文校验**：归一化比对（去空白、全角￥→¥、去千分位逗号，兼容 OCR 噪声）；失败重试 1 次，再失败该字段置 null + 低置信。**编造的字段在闸门处被拦截，永远进不了规则引擎。**

### 2.2 归一化双通道（正则优先）

| 字段 | 正则通道 | LLM 兜底 |
|---|---|---|
| amount | `[¥￥]([\d,]+(?:\.\d+)?)`（覆盖 OCR 千分位丢失） | 数值化 LLM 返回值 |
| payment_days | `在(\d+)日内[^，。；]{0,10}支付` | 数值化（"7个工作日内"不会误匹配） |
| penalty_rate | `(\d+(?:\.\d+)?)\s*%`（与 LLM 值一致性核对） | 数值化 |
| 日期 | `(\d{4})年(\d{1,2})月(\d{1,2})日` → ISO | LLM 的 YYYY-MM-DD |

### 2.3 合并策略

条款按文档顺序并发抽取（限流：全局最小间隔 + 线程池），合并时**先出现且 quote 校验通过的胜出**——与人工阅读顺序一致，避免后文引用性表述覆盖正文。

## 三、规则引擎设计

```yaml
- id: R003
  name: 大额合同未会签
  conditions:                       # 条件 AND 组合
    - {field: amount.value, op: gt, value: 1000000}
    - {field: countersign.value, op: eq_str, value: "未会签"}
  severity: high
  message: "合同金额 {amount.value} 元超过 100 万元且会签记录为「未会签」..."
```

- **字段路径 + 操作符**通用比对器：新红线 = YAML 加一条，代码零改动。
- **severity 分层的业务语义**：违反红线（未会签）= 高危；信息缺失（会签情况未提及）= 警告——**信息缺失不误伤成高危**，减少人工复核噪音。
- 消息模板支持 `{field.path}` 占位符回填实际值。

## 四、报告生成：LLM 与模板的边界

- 模板负责**结构可靠区**：风险分级、命中规则表（含 id/级别/说明）、字段溯源表（quote + 置信度）、结论建议。
- LLM 负责**推理叙述区**：逐条命中风险的 CoT 分析（为什么命中、业务影响、整改建议）。
- LLM 失败 → 整体降级为纯模板报告，服务永远有产出（降级不阻断）。

## 五、可观测与运维落点

- 日志：`[时间戳] [级别] [模块] 消息`，`logs/` 下 10MB 轮转保留 5 份，覆盖解析/抽取/规则/存储/HTTP 全链路。
- HTTP 中间件记录每请求耗时；`/healthz` 返回服务状态 + 复核数据条数。
- Dockerfile + docker-compose（8020 端口，data/logs 卷挂载，healthcheck）。

## 六、评估体系

- 标注：30 份仿真合同的 ground truth（字段值 + 原文引用），由生成器直接产出（生成即标注，引用可溯源自检）。
- 指标：字段级 TP/FP/FN → 每字段 P/R/F1 → 宏平均 + 微平均；风险分级准确率（抽取结果跑规则引擎 vs 埋点预期）。
- 复现：`python scripts/run_extraction.py && python eval/eval.py`。

## 七、面试设计要点（Q&A 预案）

1. **为什么逐条款抽取而不是整篇塞给模型？** 上下文可控、quote 溯源粒度细、失败影响面小（单条款重试）；企业级长合同（几十页）必须分治。
2. **quote 校验为什么归一化而不是逐字比对？** OCR 会改写标点/丢千分位（实测 `¥620,000.00 → ￥620000.00`），逐字比对会把正确抽取误杀；归一化（空白/全角/逗号）在容忍 OCR 噪声与拦截幻觉之间取平衡。
3. **为什么规则引擎不上 LLM？** 红线判断是确定性逻辑，规则引擎毫秒级、可解释、可回归测试；LLM 判断不可复现且贵。"确定性归规则，语义归模型"。
4. **模型不支持 Structured Outputs 怎么办？** JSON mode + Pydantic 校验 + 带错误重试兜底（DeepSeek-V4-Flash 实测 JSON mode 稳定，重试是兜底而非常规路径）。
5. **复核数据怎么用？** `/contracts/feedback` 沉淀人工修正到 SQLite；分析错误聚集的字段类型，迭代 Few-shot 样例库；术语类字段错误集中时，走 LoRA 微调实验（概念级，详见 README 口径）。
6. **企业级演进路径**：SQLite → PG；本地文件 → MinIO 存原件；锚点切分 → PP-Structure 版面分析；单机 → 网关中台统一接入（与 P3 LLM 网关衔接）。
