# 访谈 Notes 智能提取系统开发文档

版本：v1.0  
基线代码：`v2t` 项目（FastAPI + 腾讯 ASR + Qwen + MySQL）

---

## 0. 目标与整体思路

在现有 v2t「音频转写 + 纠错 + 结构化入库」能力之上，构建一套 **可持续进化的 Notes 智能提取系统**：

- 支持 **按题目/意图维度的 Notes 自动生成**
- 内建 **人工审核与行为闭环**
- 通过 **自学习层** 持续优化：
  - few‑shot 样本池
  - intent 体系与提示词
- 保持与现有 v2t 代码高度复用：ASR、纠错、RAG 能力不重复造轮子

系统分四层：

1. 项目配置层：问题与意图配置、种子 Notes
2. Notes 生成层：预处理 → 并发提取（每题）→ JSON Schema 后处理
3. 人工审核层：卡片展示、原文/音频跳转、编辑行为记录
4. 自学习层：修改率统计、few‑shot 池更新、intent 优化建议

同时实现一套 **few‑shot 注入策略**，按“同项目/同题目/同题型/同阶段/冷启动”等优先级动态选择示例。

---

## 1. 现有系统基线能力（v2t）

### 1.1 已有能力梗概

- 音频转写：腾讯云长语音 ASR，启用说话人分离
- 文本纠错与结构化：
  - Qwen 模型 + 热词表驱动的 Medical CSC（`utils.csc`）
  - 输出 `_csc.json`：`[ { timestamp, speaker, text }, ... ]`
- 数据落库：
  - 表 A：`bh_parse_project_interview`
    - 每场访谈的元信息 + 整体 JSON 文本（`file_content`）
  - 表 B：`bh_parse_project_interview_summary`
    - 按时间戳拆开的逐句记录
- RAG 能力：
  - 从 `_csc.json` 构建 FAISS 索引（`build_index_service.py`）
  - 基于索引做问答（`rag_query_service.py`）

升级版系统在此基础上增加三大能力：

1. **按题目粒度的多模块 Notes 提取**
2. **人工审核工作流与行为记录**
3. **few‑shot + intent 驱动的自学习机制**

---

## 2. 升级后整体架构

### 2.1 四层结构

1. **项目配置层**
   - 项目信息填写以及问卷录入：，用户自己导入项目目标，研究阶段，导入项目问卷/题目定义
   - AI 自动判断 intent：按题目生成标准化意图标签
   - 种子 Notes 录入：为每个主题/题型提供 2–3 条人工编写的高质量样例，用于 few‑shot 冷启动

2. **Notes 生成层**
   - 预处理：
     - 使用 v2t 完成「音频 → `_csc.json` → DB」
     - 基于 summary 表构建“时间轴 + 主题映射”
     - 预处理层直接复用 v2t 代码

   - 并发提取（每题独立）：
     - 全文上下文 + 当前题目文本
     - 动态注入 few‑shot 样例 + 项目目标 + 研究阶段 + intent
     - 按题目并发调用 LLM（`asyncio.gather` 或线程池）

   - 后处理：
     - JSON Schema 校验（结构完整性）
     - 置信度检测与异常打标
     - 写入 Notes 结果表

3. **人工审核层**
   - 按题卡片展示：
     - 每题一个卡片，展示自动生成 Notes 及置信度
     - 低置信度优先标红
   - 原文引用 + 音频跳转：
     - 支持从 Notes 回溯到原文片段和音频时间段
   - 编辑行为记录：
     - 记录 approved / 增删改 / 重写 等行为
     - 为自学习层提供数据

4. **自学习层（每日异步）**
   - 修改率统计：按项目/题目/intent 汇总修改情况
   - few‑shot 池更新：从高质量人工 Notes 中抽样入池
   - intent 优化建议：针对高修改率的 intent 给出调整建议

### 2.2 few‑shot 注入逻辑（优先级）

触发条件：某题目生成 Notes 时需要 few‑shot（绝大多数情况都需要）。

每次最多选 2 条样本，质量分 ≥ 80 分，同时传入：

- 题目文案 / 元信息
- 对应 Notes 结果

优先级从高到低：

1. 同项目 + 同题目
2. 同项目 + 同题型
3. 跨项目 + 同题型 + 同研究阶段
4. 跨项目 + 同题型（兜底）
5. 冷启动种子样本（人工录入，覆盖主要题型）

TA 标签 / 行业标签不参与 few‑shot 甄选，只用于跨项目管理与分析。

---

## 3. 数据模型设计

### 3.1 新增核心表

#### 项目表：`project`

- `id`（主键，自增）
- `name`：项目名称（如“不良反应体验”）
- `target`：项目目标（如“分析不良反应体验”）
- `research_phase`：如 baseline / FU / 研究阶段
- `created_at` （项目的创建时间，可选）

#### 3.1.1 项目题目表：`project_question`

- `id`（主键，自增）
- `project_id`（外键，关联项目表的 `id` 字段）
- `question_order`：题目顺序（如 1、2、3 等），且同一场访谈中唯一，题目越靠前，越靠后，顺序越大
- `question_text`：题目原文
- `question_type`：枚举（开放问、封闭问、多选、打分等）
- `research_phase`：如 baseline / FU / 研究阶段
- `intent_id`（外键，关联意图表的 `id` 字段）
- `meta`：JSON（如模块、主题标签等）

#### 3.1.2 意图表：`intent_definition`

- `id`（主键，自增）
- `code`：如 `SAFETY_EXPERIENCE`
- `name`：中文名称（如“不良反应体验”）
- `description`
- `schema_name`：对应的 Notes JSON Schema 名称
- `status`：active / deprecated
- 初期考虑直接写死SQL插入，后续根据需求动态更新

#### 3.1.3 few‑shot 样本表：`fewshot_sample`

- `id`（主键，自增）
- `project_id`（外键，关联项目表的 `id` 字段）
- `question_id`（外键，关联项目题目表的 `id` 字段）
- `question_type`：即 `project_question` 中的 `question_type`
- `research_phase`：即 `project_question` 中的 `research_phase`
- `intent_id`（外键，关联意图表的 `id` 字段）
- `source_kind`：`seed` / `human_approved` / `auto_candidate`（种子样本、人工审批样本、自动候选样本）
- `question_text_snapshot`（题目原文的快照，用于 few‑shot 注入）
- `note_json`：符合该 intent 的 Notes JSON 结构
- `intent_id`（外键，关联意图表的 `id` 字段）
- `quality_score`：0–100（人工打分或自动评分）
- `created_at`（样本创建时间）

#### 3.1.4 Notes 结果表：`notes_result`

- `id`（主键，自增）
- `project_id`（外键，关联项目表的 `id` 字段）
- `interview_id`（对应 `bh_parse_project_interview.id`）
- `question_id`（外键，关联项目题目表的 `id` 字段）
- `note_json`：LLM 返回的结构化结果
- `confidence`：模型置信度（0–1）
- `status`：`auto_generated` / `approved` / `edited` / `rejected`（Notes状态）
- `created_at`（Notes 结果创建时间）

（可选）
<!-- #### 3.1.5 Notes 审核与编辑记录：`notes_edit_log`

- `id`
- `notes_result_id`
- `editor_id` / `editor_name`
- `action`：`approve` / `edit` / `reject` / `rewrite`
- `before_json`
- `after_json`
- `comment`
- `created_at` -->

<!-- #### 3.1.6 自学习统计 & intent 建议（可选）

- `notes_stats_daily`
  - `stat_date`
  - `project_id`
  - `question_id`
  - `intent_id`
  - `total_count`
  - `edited_count`
  - `rejected_count`
  - `avg_quality_score`
- `intent_optimization_suggestion`
  - `id`
  - `intent_id`
  - `reason`（如“该 intent 下 Notes 被频繁重写”）
  - `suggestion`
  - `created_at` / `resolved_at` -->

---

## 4. 模块设计与实现路线

### 4.1 项目配置层

#### 4.1.1 问卷录入 & 配置

**目标**：为每个项目配置结构化的题目与元信息，为后续 Notes 生成与 few‑shot 过滤提供基础。

**实现步骤：**

1. 新增 REST API：
   - `POST /projects/{project_id}/questions/import`
     - 请求体：题目列表（顺序、文本、题型、阶段等）
     - 逻辑：批量 upsert 到 `project_question`
   - `GET /projects/{project_id}/questions`
     - 用于前端展示和手工校对
2. 数据校验：
   - 使用 Pydantic 模型定义 `QuestionIn` / `QuestionOut`
   - 确保题型、阶段等字段符合枚举

#### 4.1.2 AI 自动判断 intent

**目标**：根据题目文本自动给题目打上一个或多个 intent 标签，减少人工配置量。

**实现步骤：**

1. 新增服务模块 `intent_classifier.py`：
   - 输入：`question_text`
   - 调用 Qwen：
     - 提示词中列出所有支持的 intent 及说明
     - 要求输出 JSON：`{ "intents": [ { "code": "...", "confidence": 0.92 }, ... ] }`
2. 业务策略：
   - 若最高置信度 ≥ 0.7 → 自动写入 `project_question.intent_id`
   - 否则标记为“待人工确认”，前端列表中高亮
3. API：
   - `POST /projects/{project_id}/questions/{question_id}/classify-intent`
   - `POST /projects/{project_id}/questions/classify-intent-batch`

#### 4.1.3 种子 Notes 录入（冷启动）

**目标**：在没有历史案例的情况下也能有稳定的 few‑shot 样本。

**实现步骤：**

1. 前端表单或后台脚本，允许为每个 `intent` / `question_type` 手工录入 2–3 条高质量 Notes。
2. 写入 `fewshot_sample`：
   - `source_kind = "seed"`
   - `quality_score` 默认 90+
3. 这些样本在 few‑shot 选择逻辑中作为第 5 级兜底。

---

### 4.2 Notes 生成层

#### 4.2.1 预处理：复用 v2t 流程

**目标**：依赖现有 v2t 产出 `_csc.json` 与 DB Summary，作为 Notes 生成的基础语料。

**实现要点：**

- 入口仍然是当前 `/process-audio`，完成：
  - ASR 转写 → `_tencent_transcript.txt`
  - CSC 纠错 + 说话人统一 → `_csc.json`
  - 写入 `bh_parse_project_interview_summary`
- 在此基础上新增一个“按题目切片视图”：
  - 根据问卷题目顺序和访谈脚本的结构，将 summary 表中若干 `timestamp` 段映射到题目：
    - 简单实现：按问卷顺序 + 关键提示词（如“第一个问题，我们聊一下…”）做粗切分。
    - 高级实现：训练一个“小模型/规则引擎”识别“题目开始/结束”句。
  - 写入中间表或缓存结构：
    - `interview_question_span`: `interview_id + question_id -> [summary_row_ids]`

这一步可以先用“按时间顺序粗分段 + 人工标注”完成 MVP，后续再优化。

#### 4.2.2 并发提取（每题独立）

**目标**：对每一题构造上下文 + few‑shot + intent Prompt，调用 LLM 生成结构化 Notes。

**实现方式：**

1. 新模块 `notes_extraction.py`，核心方法：

   ```text
   generate_notes_for_interview(interview_id: int, project_id: int) -> List[NotesResult]
   ```

   逻辑：

   1. 查询该项目题目列表 `project_question`。
   2. 对每个 `question`：
      - 取 `interview_question_span` 提供的原文片段（若还未实现，可直接用整场访谈作为上下文，先不做切分）。
      - 调用 `select_fewshot_samples(...)`（见 5 章）获取 few‑shot 列表。
      - 构造 Prompt：
        - 上半部分：任务说明 + 输出 JSON Schema 约束
        - 中间部分：few‑shot 示例（题目文本 + Notes JSON）
        - 下半部分：当前题目文本 + 原文片段
      - 提交给 LLM。
   3. 使用 `asyncio.gather` 或线程池进行并发：
      - 每个题目一个协程，限制并发数避免 Qwen API 限流。

2. Prompt 关键点（示意）：

   - 明确当前 `intent`，比如“请只提取与 ADR & Safety 相关的内容”
   - 明确输出 JSON Schema，例如：

     ```json
     {
       "topic": "string",
       "summary": "string",
       "evidence": [
         {
           "timestamp": "string",
           "speaker": "string",
           "quote": "string"
         }
       ]
     }
     ```

   - 注意控制“不要超出提供的原文内容”。

3. 返回结果：
   - 原始字符串 → 用 `json.loads` 解析
   - 若解析失败 → 标记为 `status = "parse_error"`，交由后处理处置

#### 4.2.3 后处理：Schema 校验与落库

**目标**：保证 Notes 结构合法、字段完整，写入 `notes_result`。

**实现步骤：**

1. 使用 Pydantic 定义多套 `NotesSchema`，按 `intent.schema_name` 选择对应模型进行验证。
2. 校验逻辑：
   - 必填字段不能为空
   - `evidence` 列表长度 ≥ 1
   - 文本长度、句子数不超过预设上限
3. 置信度与异常：
   - 可从 LLM 返回中解析 `confidence` 字段（如在 Prompt 中要求模型给出 0–1 的自评）。
   - 若 Schema 校验失败 / 置信度 < 阈值：
     - `status = "needs_review"`
   - 正常则 `status = "auto_generated"`
4. 写入 `notes_result` 表，并关联：
   - `interview_id`
   - `question_id`
   - `intent_id`

---

### 4.3 人工审核层

#### 4.3.1 卡片展示与排序

**目标**：让编辑能在一个页面看到某场访谈“按题目”的 Notes 情况，并优先处理高风险条目。

**API 设计：**

- `GET /projects/{project_id}/interviews/{interview_id}/notes`
  - 返回：
    - 每题的 `question_text`
    - 对应 `notes_result`（可能多条：不同 intent）
    - 置信度
    - 状态

前端可以：

- 默认按“置信度从低到高 + 状态为 needs_review 在前”排序
- 每个卡片支持展开/折叠

#### 4.3.2 原文引用 + 音频跳转

**目标**：从 Notes 直接跳回原文/音频，方便审稿。

**实现要点：**

1. 在 `note_json.evidence` 中要求模型尽量保留 `timestamp` 字段，格式沿用 `_csc.json` 里的时间范围。
2. 根据时间戳和 speaker，从 `bh_parse_project_interview_summary` 或 `_csc.json` 找回原文。
3. 若前端支持音频播放器：
   - 将时间戳转换为秒数，构造“从 x 秒开始播放”的 URL 或参数。

API 示例：

- `GET /interviews/{interview_id}/evidence-snippet?timestamp=...`

返回：

- 原文文本
- 上下文若干句
- 音频偏移量

#### 4.3.3 编辑行为记录

**目标**：为自学习层提供监督信号。

**API 设计：**

- `POST /notes/{notes_result_id}/review`
  - 请求体：
    - `action`: `approve` / `edit` / `reject` / `rewrite`
    - `after_json`（若有修改）
    - `quality_score`（0–100）
    - `comment`（可选）
- 服务端：
  - 将操作写入 `notes_edit_log`
  - 同步更新 `notes_result.status`、`note_json`、`updated_at`

---

### 4.4 自学习层（离线任务）

#### 4.4.1 修改率统计

**目标**：识别哪些题目/intent 问题最大，以便调优。

**实现方式：**

- 每天凌晨跑一次统计任务（可用 crontab + Python 脚本）：
  - 按 `stat_date`（当天）、`project_id`、`question_id`、`intent_id` 聚合：
    - `total_count`
    - `edited_count`（action in `["edit", "rewrite"]`）
    - `rejected_count`
    - `avg_quality_score`
  - 写入 `notes_stats_daily`

#### 4.4.2 few‑shot 池更新

**规则（可迭代优化）**：

- 入池条件：
  - `notes_result.status in ["approved", "edited"]`
  - `quality_score >= 80`
- 限制：
  - 每个 `(project_id, question_id)` 至多保留 N 条（例如 20 条），超出的按时间/质量淘汰。
- 写入 `fewshot_sample`：
  - `source_kind = "human_approved"`
  - `note_json` 即当前 Notes 最终版本

#### 4.4.3 intent 优化建议

**逻辑示例**：

- 若某 `intent_id` 在连续 7 天内：
  - `edited_count / total_count >= 0.5` 或 `rejected_count / total_count >= 0.2`
- 生成一条 `intent_optimization_suggestion`：
  - `reason`: 如“该 intent 下 Notes 被频繁重写”
  - `suggestion`: 台湾可读的文本（由 LLM 帮忙草拟）
- 这部分可以通过一个简单的脚本 + LLM 完成。

---

## 5. few‑shot 注入策略实现细节

### 5.1 核心选择函数

定义函数：

```text
select_fewshot_samples(
    project_id: int,
    question_id: int,
    question_type: str,
    research_phase: str,
    intent_id: int,
    limit: int = 2
) -> List[FewshotSample]
```

选择流程：

1. 查询 `project_question` 获取当前题目元信息。
2. 按优先级尝试查询 `fewshot_sample`：

   1. **同项目 + 同题目**：
      - `project_id = ? AND question_id = ?`
   2. **同项目 + 同题型**：
      - `project_id = ? AND question_type = ?`
   3. **跨项目 + 同题型 + 同研究阶段**：
      - `question_type = ? AND research_phase = ?`
   4. **跨项目 + 同题型（兜底）**：
      - `question_type = ?`
   5. **冷启动种子样本**：
      - `source_kind = "seed" AND intent_id = ?`

3. 每一层：
   - 只使用 `quality_score >= 80` 的样本
   - 按 `created_at DESC` 排序，取前 `limit` 条
   - 如果该层样本数量 < `limit`，则继续尝试下一层补足

### 5.2 Prompt 注入格式

对每个 few‑shot 样本，传给 Qwen 的信息至少包括：

- `example_question_text`
- `example_note_json`（直接作为 JSON 文本）
- 可选：在 Prompt 中简要说明这是“历史人工修订后的高质量示例”。

示意：

```text
下面是若干个历史示例。每个示例包含【题目】和【标准化的 Notes JSON】。

示例 1：
题目：
{{example_question_text_1}}

标准化 Notes（JSON）：
{{example_note_json_1}}

示例 2：
...

请参照上述示例的结构和书写风格，对当前题目生成 Notes。
```

---

## 6. 接口与服务编排

### 6.1 服务边界

- **v2t 服务（已有）**：
  - 负责：音频处理 + 纠错 + `_csc.json` + DB Summary
  - 入口：`/process-audio`
- **Notes 服务（新增）**：
  - 与 v2t 共享数据库
  - 可以同进程，也可以拆成独立 FastAPI 应用

### 6.2 关键 API 一览

1. 项目配置：
   - `POST /projects/{project_id}/questions/import`
   - `GET  /projects/{project_id}/questions`
   - `POST /projects/{project_id}/questions/{question_id}/classify-intent`
   - `POST /projects/{project_id}/questions/classify-intent-batch`

2. Notes 生成：
   - `POST /projects/{project_id}/interviews/{interview_id}/notes/generate`
     - 触发本场访谈的全题 Notes 生成
   - `GET  /projects/{project_id}/interviews/{interview_id}/notes`
     - 获取所有题目的 Notes 结果

3. 审核与编辑：
   - `POST /notes/{notes_result_id}/review`
   - `GET  /interviews/{interview_id}/evidence-snippet`

4. 自学习任务（内部/管理接口）：
   - `POST /admin/notes/stats/run-daily`
   - `POST /admin/notes/fewshot/rebuild`
   - `GET  /admin/intent/suggestions`

---

## 7. 分阶段实施路线建议

### 阶段 1：打通「按题目生成 Notes」主链路

- 新增 `project_question` / `intent_definition` / `notes_result` 基础表及相应 API。
- 在现有 v2t 后处理后，增加离线脚本：
  - 从某场访谈的 summary 表中读取全文（可以先不做题目切片，作为 MVP）。
  - 对每题调用 `notes_extraction.generate_notes_for_interview`。
- Notes 先只返回简单 JSON（如 `summary + evidence`），不做复杂模块拆分。

### 阶段 2：人工审核 & few‑shot 池

- 上线前端卡片视图和 `notes_edit_log`。
- 根据编辑操作写入 `fewshot_sample`。
- 实现 `select_fewshot_samples`，在 Notes 生成时注入 few‑shot。

### 阶段 3：完善题目切片与 intent 体系

- 引入基于规则/模型的“题目片段识别”，使每题 Notes 只用相关上下文。
- 优化 `intent_definition` 和 Schema：
  - 将 ADR、安全性、疗效、病例、引用、Quotes 等拆成独立 intent。
- 调整 Prompt，使每个 intent 的输出结构更加稳定。

### 阶段 4：自学习与分析

- 实现每日统计任务和 `notes_stats_daily`。
- 基于统计结果自动生成 `intent_optimization_suggestion`。
- 为运营/产品提供简单的监控报表（可视化可留给后续 BI 工具）。

---

## 8. 与现有代码的映射关系

- 语音转写 & CSC：继续使用 `main.py` + `workflow.py` + `tencent_code.py` + `utils.csc`，无需大改。
- Notes 生成层：
  - 新增模块与表，但复用 `_csc.json` 和 `bh_parse_project_interview_summary` 作为输入。
- RAG：
  - 现有 FAISS 能力可以与 Notes 结果结合，用于“智能补全”或“QA 辅助审稿”，属于后续增强。

---

> 这份文档定位为「开发侧设计说明」，适合作为后续迭代的统一蓝图：  
> - 后端同学按模块/接口拆解实现  
> - 数据/算法同学在 few‑shot 池、自学习统计、intent 优化上迭代  
> - 前端同学根据“卡片展示 + 原文跳转 + 行为记录”设计交互与页面