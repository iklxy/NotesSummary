# NotesSummary

一个面向访谈音频的端到端处理项目。系统会完成音频上传、ASR 转录、纠错与再纠错、summary 落库、RAG 检索、Notes 生成，以及前端展示与编辑。

## 技术栈

- 后端引擎：Python 3.11、FastAPI、PyMySQL、Requests、python-dotenv
- ASR：火山/豆包录音识别接口
- 大模型：OpenAI 兼容接口、Anthropic 兼容接口
- 向量检索：Ollama + Qdrant
- 数据库：MySQL
- 音频存储：字节系 TOS
- 前端：Next.js、React、TypeScript、Ant Design
- 环境管理：Conda

## 1. Conda 环境配置

项目根目录已经提供 `environment.yml`，可以直接创建运行环境。

```bash
conda env create -f environment.yml
conda activate vol
```

如果环境已经存在，只想同步依赖，可以使用：

```bash
conda env update -n vol -f environment.yml --prune
```

## 2. 环境变量设置

项目根目录下的 `.env` 文件用于配置运行时参数。  
后端 engine 会从 `.env` 中读取配置，修改后需要重启对应服务或重新加载环境变量。

建议按照下面格式填写：

```env
# 数据库
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=notes_summary

# 大模型
LLM_PROVIDER=openai
LLM_API_KEY=your_llm_api_key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL_NAME=deepseek-chat

# Embedding / Ollama
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL_NAME=bge-m3:latest

# 热词兜底文件
TERM_HINTS_FILE=data/keywords.txt

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
```

说明：

- `OLLAMA_HOST` 需要填写完整地址，格式必须是 `http://IP:PORT`。
- `TERM_HINTS_FILE` 是可选的全局兜底热词文件。
- `INTERNAL_SERVICE_BASE` 是前端 BFF 调用内部 engine 的地址。
- 如果你修改了 `.env`，需要重新启动相关进程才能生效。

## 3. 项目总述

这个项目的核心目标，是把访谈音频处理成可以检索、可以编辑、可以生成 Notes 的结构化数据。

整体流程如下：

1. 上传访谈音频
2. 调用 ASR 得到转录结果
3. 对 ASR 文本做主纠错
4. 做再纠错兜底
5. 将再纠错后的文本写入 summary 表
6. 基于 summary 构建向量索引
7. 按问题检索相关片段
8. 生成 Notes
9. 前端展示原文、summary、Notes，并支持编辑与导出

当前项目里，summary 表展示的是原始 ASR 经过纠错和再纠错后的最终文本，不再直接展示原文。

## 4. 目录说明

- `summarynotes-be/`：对外业务 API 服务
- `summarynotes-fe/`：前端页面
- 根目录 Python 文件：engine 层，负责 ASR、纠错、summary、Notes、RAG 等核心流程
- `data/`：热词文件、兜底纠错文件等配置资源
- `test/`：测试脚本与导出结果

## 5. 启动说明

本仓库的启动方式由你当前的脚本和部署方式决定。通常需要：

1. 启动 MySQL、Qdrant、Ollama
2. 配置好根目录 `.env`
3. 激活 Conda 环境
4. 脚本启动

脚本支持参数 start stop restart

## 6.端口说明

1.转录引擎服务默认 8000
2.后端服务 9000
3.前端服务 3000

如有端口占用情况，进入bash脚本进行改写
