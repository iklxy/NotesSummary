# NotesSummary

一个面向访谈音频处理的端到端项目。系统会完成音频上传、ASR 转录、纠错清洗、trans 落库、向量检索、Notes/Minutes/KBQ/Cards/CA 生成，以及前端展示、编辑与导出。

## 文档入口

- 交接说明：[项目交接文档.md](/项目交接文档.md)
- 部署说明：[项目部署文档.md](/项目部署文档.md)
- 数据库结构：[schema.sql](/schema.sql)
- 统一启动脚本：[start_all.sh](/start_all.sh)

## 系统结构

项目由三部分组成：

1. Engine：根目录 Python FastAPI 服务，负责 ASR、纠错清洗、trans、RAG、Notes、Minutes、KBQ、Cards、CA 等核心工作流。
2. BFF：`summarynotes-be/` 下的 FastAPI 服务，负责对前端提供业务 API、文件上传、权限和导出。
3. FE：`summarynotes-fe/` 下的 Next.js 前端，负责项目、问卷、访谈、纪要、卡片、CA 的页面展示和编辑。

默认端口：

- Engine：`8000`
- BFF：`9000`
- FE：`3000`

## 技术栈

- 后端：Python 3.13、FastAPI、Uvicorn、PyMySQL
- 前端：Next.js 16、React 19、TypeScript、Ant Design、React Query
- 数据库：MySQL
- 向量库：Qdrant
- Embedding：Ollama
- ASR：火山/豆包录音识别
- 对象存储：字节 TOS
- 大模型：OpenAI 兼容接口、Anthropic 兼容接口
- 环境管理：Conda + npm

## 外部依赖

启动前需要先准备：

- MySQL
- Qdrant
- Ollama，并拉起 embedding 模型
- 可访问的 LLM API
- 火山 ASR 账号与密钥
- TOS 账号、Bucket 与密钥
- Node.js + npm
- Conda

## 目录说明

- `summarynotes-be/`：对外业务 API 服务
- `summarynotes-fe/`：前端页面
- 根目录 Python 文件：Engine 层，负责 ASR、纠错、summary、Notes、Minutes、KBQ、Cards、CA 等核心流程
- `data/`：问卷、访谈备份、热词、导出中间文件等数据目录
- `audio/`：本地音频备份目录
- `runtime/`：日志、PID、运行时数据目录

## 环境配置

### Conda 环境

项目当前环境名固定为 `vol`，定义文件为 [environment.yml](/home/lixinyang/NotesSummary/environment.yml)。

创建环境：

```bash
conda env create -f environment.yml
conda activate vol
```

同步已有环境：

```bash
conda env update -n vol -f environment.yml --prune
```

### 前端依赖

建议使用 `nvm` 管理 Node.js，统一使用 Node 22 LTS。

```bash
nvm install 22
nvm use 22
```

安装前端依赖：

```bash
cd summarynotes-fe
npm ci
```

## `.env` 配置

Engine 和 BFF 都依赖项目根目录 `.env`。配置读取入口在 [config.py](/home/lixinyang/NotesSummary/config.py)。

最少需要配置：

```env
# 数据库
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=summarynotes

# 通用大模型
LLM_PROVIDER=openai
LLM_API_KEY=your_llm_api_key
LLM_BASE_URL=https://your-llm-endpoint
LLM_MODEL_NAME=your_model_name

# Transcript / 转录纠错模型
TRANSCRIPT_LLM_PROVIDER=openai
TRANSCRIPT_LLM_API_KEY=your_transcript_llm_api_key
TRANSCRIPT_LLM_BASE_URL=https://your-transcript-llm-endpoint
TRANSCRIPT_LLM_MODEL_NAME=your_transcript_model

# Notes / Minutes / KBQ / CA 模型
NOTES_LLM_PROVIDER=openai
NOTES_LLM_API_KEY=your_notes_llm_api_key
NOTES_LLM_BASE_URL=https://your-notes-llm-endpoint
NOTES_LLM_MODEL_NAME=your_notes_model

# Ollama
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL_NAME=bge-m3:latest

# ASR
ASR_APP_KEY=your_asr_app_key
ASR_ACCESS_KEY=your_asr_access_key
VOLCANO_CLUSTER=volc_auc_common
VOLCANO_SERVICE_URL=https://openspeech.bytedance.com/api/v1/auc

# TOS
TOS_ACCESS_KEY=your_tos_access_key
TOS_SECRET_KEY=your_tos_secret_key
TOS_ENDPOINT=https://tos-cn-shanghai.volces.com
TOS_REGION=cn-shanghai
TOS_BUCKET_NAME=benhealth
LOCAL_AUDIO_ROOT=.
TOS_AUDIO_PREFIX=audio
TOS_URL_EXPIRE_SECONDS=3600

# Qdrant
QDRANT_HOST=127.0.0.1
QDRANT_PORT=6333
QDRANT_COLLECTION_SUMMARY=interview_summary

# 内部服务
INTERNAL_SERVICE_BASE=http://127.0.0.1:8000

# 可选：统一启动脚本使用的 conda 环境名
APP_CONDA_ENV=vol
```

说明：

- `DB_NAME` 请使用 `summarynotes`；这与 [schema.sql](/home/lixinyang/NotesSummary/schema.sql) 保持一致。
- `OLLAMA_HOST` 必须填写完整地址，例如 `http://127.0.0.1:11434`。
- `APP_CONDA_ENV=vol` 能让统一启动脚本自动用 Conda 环境启动 Engine 和 BFF。

## 快速部署

完整部署流程请看 [项目部署文档.md](/home/lixinyang/NotesSummary/项目部署文档.md)。最短路径如下。

### 1. 数据库迁移

```bash
mysql -uroot -p < schema.sql
```

或：

```bash
mysql -uroot -p summarynotes < schema.sql
```

### 2. Docker 启动 Qdrant

```bash
docker run -d \
  --name qdrant \
  -p 6333:6333 \
  -p 6334:6334 \
  -v $(pwd)/runtime/qdrant_storage:/qdrant/storage \
  qdrant/qdrant
```

### 3. 本地部署 Ollama

安装并启动：

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve
```

拉取模型：

```bash
ollama pull bge-m3:latest
```

## 启动方式

### 推荐方式：统一脚本

```bash
conda activate vol
bash start_all.sh start
```

脚本支持：

```bash
bash start_all.sh start
bash start_all.sh stop
bash start_all.sh restart
bash start_all.sh status
```

### 手动启动

Engine：

```bash
cd /home/lixinyang/NotesSummary
uvicorn Api:app --host 0.0.0.0 --port 8000
```

BFF：

```bash
cd /home/lixinyang/NotesSummary/summarynotes-be
uvicorn main:app --host 0.0.0.0 --port 9000
```

FE：

```bash
cd /home/lixinyang/NotesSummary/summarynotes-fe
npm run build
npm run start -- --hostname 0.0.0.0 --port 3000
```

## 工作流概览

### 项目级工作流

1. 创建项目
2. 上传项目指南文件
3. BFF 后台触发项目指南学习
4. 提取文本/OCR 兜底
5. LLM 总结指南，回写项目背景与 guide 表
6. 创建项目角色、问卷、Key BQ

### 访谈级工作流

1. 在项目下创建访谈并上传音频
2. BFF 保存音频到本地 `audio/` 和 `data/` 备份目录
3. BFF 调用 Engine 内部接口触发转录工作流
4. Engine 上传音频到 TOS 或复用已有对象
5. Engine 调火山 ASR，支持异步轮询与断点恢复
6. Engine 对 ASR 结果清洗和纠错
7. 将清洗后的段落写入 `bh_project_interview_summary`
8. 基于 summary 建立向量索引
9. 按需生成 Notes
10. 基于 summary 全文生成 Minutes
11. 基于 Minutes 生成 Cards
12. 基于 Key BQ + Minutes 生成 KBQ Notes
13. 前端查看、编辑、导出 transcript / overall notes / cards / CA

## 当前已完成能力

- 用户登录、Cookie 登录态维护
- 项目创建、编辑、删除、查询
- 项目指南上传与自动学习总结
- 问卷上传、docx 转 md/json、热词审核
- 项目级 Key BQ 管理
- 项目下创建访谈并上传音频
- 转录工作流后台异步执行与断点恢复
- summary 查询、逐条编辑、纠错学习记录
- 问题管理与按题生成 Notes
- Minutes 生成与手工保存
- KBQ Notes 刷新
- 全文 Cards 生成、增删改、审核保存
- Few-shot 样本管理
- Transcript / Overall Notes / CA 导出 Word、XLSX
- CA 表生成、框架保存、结果导出

## 重要注意事项

1. `schema.sql` 的实际数据库名是 `summarynotes`，不要使用旧文档里的 `notes_summary`。
2. 当前主工作流里，RAG 没有完全废弃，但主要服务于 Notes 子流程；Minutes、Cards、KBQ、CA 主要基于 summary/minutes 直接生成。
3. 如果修改前端端口，需要同步检查 CORS 放行配置：
   文件在 [summarynotes-be/middleware/cors.py](/home/lixinyang/NotesSummary/summarynotes-be/middleware/cors.py)
4. 当前认证接口使用简单 Cookie 登录态，密码校验不是标准哈希校验；如果要上生产，需要补安全改造。
5. `summarynotes-be/api/health.py` 虽然存在健康检查路由定义，但当前 `summarynotes-be/main.py` 没有注册该 router。

## 日志与排障

日志目录：

- 系统日志：`runtime/logs/system.log`
- 服务日志：`runtime/logs/engine.log` `runtime/logs/bff.log` `runtime/logs/fe.log`
- 访谈日志：`runtime/logs/interviews/interview_{id}.log`
- 项目日志：`runtime/logs/projects/project_{id}.log`

启动失败时优先检查这些日志。

## 进一步阅读

- 交接说明：[项目交接文档.md](/home/lixinyang/NotesSummary/项目交接文档.md)
- 部署说明：[项目部署文档.md](/home/lixinyang/NotesSummary/项目部署文档.md)
