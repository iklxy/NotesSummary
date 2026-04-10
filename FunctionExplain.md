## VolcUpload.py

### make_response(success: bool, code: int, message: str, data: dict | None = None) -> dict
- 参数  
  - success: 是否调用成功，True 表示成功，False 表示失败  
  - code: 业务错误码，0 表示成功，非 0 表示具体错误类型  
  - message: 简短提示文本，方便日志和排查  
  - data: 业务数据或错误上下文信息，默认为空字典  
- 功能  
  - 统一封装上传相关接口的返回 JSON 结构，保证顶层包含 success/code/message/data 四个字段  
- 返回值  
  - dict: 标准化的 JSON 字典，用于 HTTP 返回或日志记录

### get_tos_client() -> tos.TosClientV2
- 参数  
  - 无（使用模块级别的 ak/sk/endpoint/region 配置）  
- 功能  
  - 校验 TOS 配置是否完整（AK/SK、endpoint、region），并创建 TosClientV2 客户端实例  
- 返回值  
  - TosClientV2: 已初始化的 TOS 客户端对象

### build_local_file_path(project_id: int, interview_id: int, file_name: str) -> str
- 参数  
  - project_id: 项目 ID，对应 bh_project.id  
  - interview_id: 访谈 ID，对应 bh_project_interview.id  
  - file_name: 音频文件名，例如 "1.wav"  
- 功能  
  - 按约定规则拼接本地音频文件路径：  
    LOCAL_AUDIO_ROOT/project_{project_id}/interview_{interview_id}/{file_name}  
- 返回值  
  - str: 本地音频文件完整路径

### build_object_key(project_id: int, interview_id: int, file_name: str) -> str
- 参数  
  - project_id: 项目 ID，对应 bh_project.id  
  - interview_id: 访谈 ID，对应 bh_project_interview.id  
  - file_name: 音频文件名，用作对象 key 最后一段  
- 功能  
  - 构造 TOS 中的对象 key，例如：  
    audio/project_{project_id}/interview_{interview_id}/{file_name}  
- 返回值  
  - str: TOS 对象 key 字符串

### upload_local_file(local_file_path: str, object_key: str) -> dict
- 参数  
  - local_file_path: 本地音频文件绝对或相对路径  
  - object_key: 上传到 TOS 的对象 key（不含 bucket 名）  
- 功能  
  - 校验本地文件存在且可读  
  - 校验 TOS 配置（bucket、AK/SK 等）  
  - 调用 TOS SDK 将本地文件上传到指定 bucket/object_key  
  - 生成预签名 URL，供后续 ASR 使用  
  - 将结果封装为标准 JSON 返回  
- 返回值  
  - dict: 标准返回结构  
    - success/code/message/data  
    - data 中包含 project_id/interview_id/file_name/object_key/bucket_name/audio_url/status 等信息


## VolcengineConversion.py

### submit_task(audio_url: str)
- 参数  
  - audio_url: 已上传到 TOS 的音频预签名 URL，ASR 服务通过此 URL 拉取音频  
- 功能  
  - 按火山 ASR AUC 接口协议构造 /submit 请求体，提交异步识别任务  
  - 解析返回的 JSON，从 resp.id 中取出任务 ID  
- 返回值  
  - str: ASR 任务 ID，用于后续查询任务状态  

### query_task(task_id)
- 参数  
  - task_id: 提交任务时返回的任务 ID  
- 功能  
  - 构造 /query 请求体，查询指定任务的当前状态与识别结果  
  - 将响应解析为 JSON 并原样返回  
- 返回值  
  - dict: ASR 查询接口返回的完整 JSON 字典

### run_asr(audio_url: str)
- 参数  
  - audio_url: 已上传到 TOS 的音频预签名 URL  
- 功能  
  - 提交 ASR 任务并轮询查询状态，直到成功、失败或超时  
  - 在成功时抽取整场文本 `full_text`：  
    - 优先使用 resp.text；若为空则聚合 utterances 文本  
  - 根据带说话人信息的 utterances，将连续同一说话人的发言聚合成轮次段：  
    - 每段包含 id、speaker_id、speaker_content  
- 返回值  
  - dict:  
    - 成功时：  
      - full_text: str，整场转写文本  
      - speakers: List[{"id": int, "speaker_id": str, "speaker_content": str}]  
    - 失败/超时时：  
      - full_text 为空字符串，speakers 为空列表


## Model.py

### class ModelClient
- 作用  
  - 封装 Anthropic Claude 的调用逻辑，并提供“清洗 speaker 文本”的任务级接口  
- 初始化参数（从环境变量读取）  
  - LLM_API_KEY: 模型 API Key  
  - LLM_BASE_URL: 模型 API 基础 URL  
  - LLM_MODEL_NAME: 模型名称，例如 claude-sonnet-4-6  

#### generate(system_prompt: str, user_prompt: str) -> str
- 参数  
  - system_prompt: 系统提示，约束角色和输出规范  
  - user_prompt: 用户输入，描述当前具体任务和数据  
- 功能  
  - 调用 Claude 的 messages.create 接口，发送 system + user 两段文本  
  - 从返回的第一个 text 类型块中取出文本内容  
- 返回值  
  - str: Claude 返回的文本内容；非 text 类型时退化为整个响应的 JSON 字符串

#### clean_speaker_utterance(speaker_text: str, speaker_role: Optional[str] = None, term_hints: Optional[List[str]] = None) -> Dict[str, Any]
- 参数  
  - speaker_text: 单个 speaker 轮次的原始转写文本  
  - speaker_role: 说话人角色（如 "interviewer" / "interviewee"），可选  
  - term_hints: 专业热词提示列表（字符串列表），用于统一和纠正术语  
- 功能  
  - 通过系统与用户 prompt 向 Claude 提示清洗规则：  
    - 删除语气词和口头禅  
    - 保持事实不变  
    - 优先使用 term_hints 中的标准术语  
    - 输出符合指定 JSON 结构的结果  
  - 处理 Claude 返回的结果：  
    - 去掉 ```json 代码块外壳  
    - 从文本中截取核心 JSON 并解析  
    - 解析失败时回退为原文  
- 返回值  
  - dict，结构至少包含：  
    - clean_text: str，清洗后的文本  
    - term_corrections: List[{"from": str, "to": str}]，术语纠错记录  
    - 解析失败时还会包含 llm_raw_output 原始文本


## CleanConversion.py

### clean_speakers(speakers: List[Dict[str, Any]], speaker_roles: Optional[Dict[str, str]] = None, term_hints: Optional[List[str]] = None) -> List[Dict[str, Any]]
- 参数  
  - speakers: 说话轮次列表，每个元素通常包含：  
    - id: 轮次 ID  
    - speaker_id: 说话人 ID  
    - speaker_content: 原始文本  
  - speaker_roles: 可选，将 speaker_id 映射为角色标签的字典，例如 {"1": "interviewer"}  
  - term_hints: 可选，专业热词提示列表  
- 功能  
  - 为每个轮次调用 ModelClient.clean_speaker_utterance 完成纠错与清洗  
  - 打印清洗进度（当前段序号、总段数、id 与 speaker_id）  
- 返回值  
  - List[dict]：与输入一一对应的清洗结果列表，每个元素包含：  
    - id: 轮次 ID  
    - speaker_id: 说话人 ID  
    - speaker_content_clean: 清洗后的文本  
    - term_corrections: 术语纠错记录

### clean_file_content_json(file_content_json: str, speaker_roles: Optional[Dict[str, str]] = None, term_hints: Optional[List[str]] = None) -> str
- 参数  
  - file_content_json: bh_project_interview.file_content 字段中的 JSON 字符串  
  - speaker_roles: 可选，speaker_id 到角色的映射  
  - term_hints: 可选，专业术语提示列表  
- 功能  
  - 解析 file_content JSON，取出 result.speakers  
  - 调用 clean_speakers 对所有轮次进行清洗  
  - 在 speakers 中增加/更新字段：  
    - speaker_content_clean  
    - term_corrections  
  - 重新序列化为 JSON 字符串返回  
- 返回值  
  - str: 更新后的 file_content JSON 字符串，结构仍为 {"audio": ..., "result": {...}}


## DbAccess.py

### get_connection() -> pymysql.connections.Connection
- 参数  
  - 无（从环境变量读取 DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME）  
- 功能  
  - 创建并返回一个 MySQL 连接，使用 DictCursor，autocommit=False  
- 返回值  
  - Connection: pymysql 的连接对象，由调用方负责关闭

### get_interview_by_id(interview_id: int) -> Optional[Dict[str, Any]]
- 参数  
  - interview_id: 访谈主键 ID，对应 bh_project_interview.id  
- 功能  
  - 根据访谈 ID 查询 bh_project_interview 单条记录，返回部分关键字段（id/parse_project_id/file_name/file_content/file_path/status）  
- 返回值  
  - dict: 访谈记录字典；不存在时返回 None

### update_interview_after_upload(interview_id: int, object_key: str, status: int, file_id: Optional[str] = None, audio_url: Optional[str] = None) -> None
- 参数  
  - interview_id: 访谈主键 ID  
  - object_key: 上传到 TOS 的对象 key，写入 file_path  
  - status: 访谈处理状态（如 1=已上传待 ASR）  
  - file_id: 可选，写入 file_id，可与 object_key 对应  
  - audio_url: 预留，可选存储预签名 URL（当前注释掉）  
- 功能  
  - 更新 bh_project_interview 中与文件相关的字段：file_path、status（以及可选的 file_id）  
- 返回值  
  - 无；失败时抛出异常

### update_interview_file_content(interview_id: int, file_content_json: str) -> None
- 参数  
  - interview_id: 访谈主键 ID  
  - file_content_json: 转写结果 JSON 字符串  
- 功能  
  - 将 JSON 文本写入 bh_project_interview.file_content 字段，用于存储整场 ASR 结果快照  
- 返回值  
  - 无；失败时抛出异常

### insert_summary_from_cleaned_speakers(interview_id: int, speakers: list[dict]) -> int
- 参数  
  - interview_id: 访谈主键 ID，对应 bh_project_interview.id  
  - speakers: 清洗后的说话轮次列表，每个元素至少包含：  
    - speaker_id: 说话人 ID  
    - speaker_content_clean: 清洗后的文本  
- 功能  
  - 将每个轮次写入 bh_project_interview_summary，字段映射为：  
    - project_interview_id = interview_id  
    - timestamp = ""（留空）  
    - speaker = speaker_id  
    - text = speaker_content_clean  
    - modify = 0  
- 返回值  
  - int: 实际插入的记录条数


## Workflow.py

### step_upload_interview_audio(interview_id: int) -> Dict[str, Any]
- 参数  
  - interview_id: 访谈主键 ID  
- 功能  
  - 若 bh_project_interview.file_path 为空：  
    - 使用 build_local_file_path / build_object_key 构造本地路径和 object_key  
    - 调用 upload_local_file 完成本地上云  
    - 更新 bh_project_interview 的 file_path/status/file_id  
  - 若 file_path 已存在：  
    - 基于已有 object_key 生成新的预签名 URL  
- 返回值  
  - dict:  
    - success: 是否成功  
    - object_key: TOS 对象 key  
    - audio_url: 预签名 URL（成功时）

### step_transcribe(audio_url: str) -> Dict[str, Any]
- 参数  
  - audio_url: TOS 预签名音频 URL  
- 功能  
  - 调用 run_asr 进行异步识别，获取 full_text 和 speakers 轮次结构  
- 返回值  
  - dict:  
    - success: 是否成功  
    - asr_result: run_asr 返回的结果字典

### step_store_file_content(interview_id: int, object_key: str, audio_url: str, asr_result: Dict[str, Any]) -> Dict[str, Any]
- 参数  
  - interview_id: 访谈主键 ID  
  - object_key: TOS 对象 key  
  - audio_url: 预签名 URL  
  - asr_result: ASR 结果字典（包含 full_text 和 speakers）  
- 功能  
  - 构造标准的 file_content JSON（audio + result），并写入 bh_project_interview.file_content  
- 返回值  
  - dict:  
    - success: 是否成功  
    - file_content: Python 对象形式的 JSON 内容（便于后续复用）

### step_clean_with_llm(file_content_json: str) -> Dict[str, Any]
- 参数  
  - file_content_json: 当前存储在 DB 中的 file_content JSON 字符串  
- 功能  
  - 调用 clean_file_content_json，对所有 speakers 轮次进行模型清洗，并返回更新后的 JSON 文本  
- 返回值  
  - dict:  
    - success: 是否成功  
    - cleaned_json: 清洗后的 file_content JSON 字符串

### step_write_summary(interview_id: int, cleaned_json: str) -> Dict[str, Any]
- 参数  
  - interview_id: 访谈主键 ID  
  - cleaned_json: 已经过 LLM 清洗的 file_content JSON 字符串  
- 功能  
  - 从 cleaned_json 中解析 result.speakers  
  - 调用 insert_summary_from_cleaned_speakers，将清洗后的文本批量写入 bh_project_interview_summary  
- 返回值  
  - dict:  
    - success: 是否成功  
    - inserted: 插入的记录条数

### run_workflow(interview_id: int) -> Dict[str, Any]
- 参数  
  - interview_id: 访谈主键 ID  
- 功能  
  - 串联整个工作流：  
    1) step_upload_interview_audio：本地上云或生成预签名 URL  
    2) step_transcribe：云上音频转文字（ASR）  
    3) step_store_file_content：写入 file_content  
    4) step_clean_with_llm：调用 LLM 进行清洗  
    5) step_write_summary：将清洗后的结果写入 bh_project_interview_summary  
- 返回值  
  - dict:  
    - success: 是否成功  
    - object_key: TOS 对象 key  
    - audio_url: 预签名 URL  
    - asr_result_preview: 包含 full_text_len 和 speakers_count 的简要信息  
    - summary_inserted: 写入 summary 表的记录条数
