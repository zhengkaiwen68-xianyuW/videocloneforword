# 短视频人格深度重构与洗稿引擎 - 代码文档

> 项目核心模块的详细技术文档

---

## 一、项目概览

### 1.1 项目简介

本项目是一个**短视频人格深度重构与洗稿引擎**，其核心功能是：
1. 从 B站 视频提取 ASR 语音文本
2. 构建该 UP 主/视频的人格画像
3. 使用该人格风格重写新的文案

### 1.2 技术栈

| 层级 | 技术 |
|------|------|
| Web 框架 | FastAPI + Uvicorn |
| 数据库 | SQLite + SQLAlchemy ORM |
| 视频下载 | yt-dlp |
| 语音识别 | Whisper (本地) |
| 前端 | 原生 HTML/CSS/JS (嵌入式) |
| 配置管理 | PyYAML |

### 1.3 项目结构

```
videocloneforword/
├── main.py                      # 应用入口
├── config.yaml                  # 配置文件
├── requirements.txt             # 依赖
├── PRD.md                       # 产品需求文档
├── CODE_DOCUMENTATION.md        # 本文档
├── persona_engine/              # 核心引擎
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   └── types.py            # 核心类型定义
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── database.py         # 数据库模型
│   │   └── persona_repo.py     # 数据仓储层
│   ├── audit/
│   │   ├── __init__.py
│   │   └── scorer.py           # 一致性评分器
│   ├── rewrite/
│   │   ├── __init__.py
│   │   └── persona_injector.py # 人格注入引擎
│   └── asr/
│       ├── __init__.py
│       └── bilibili_downloader.py # B站视频下载器
└── web_ui.html                  # 前端界面
```

---

## 二、核心类型定义

**文件**: `persona_engine/core/types.py`

### 2.1 Persona (人格)

```python
@dataclass
class Persona:
    id: str                           # UUID
    name: str                         # 人格名称
    source_texts: list[str]           # 原始文本列表
    style_keywords: list[str]         # 风格关键词
    speaking_patterns: list[str]      # 说话模式
    tone_markers: list[str]           # 语调标记
    consistency_score: float          # 一致性评分
    status: PersonaStatus             # processing/completed/failed
    created_at: datetime
    updated_at: datetime
```

### 2.2 RewriteRequest (重写请求)

```python
@dataclass
class RewriteRequest:
    persona_id: str                   # 人格ID
    source_text: str                  # 待重写文本
    preservation_level: float          # 内容保留度 (0.0-1.0)
    style_intensity: float             # 风格强度 (0.0-1.0)
```

### 2.3 RewriteResult (重写结果)

```python
@dataclass
class RewriteResult:
    original_text: str                # 原文
    rewritten_text: str               # 重写后文本
    style_match_score: float          # 风格匹配度
    content_similarity: float         # 内容相似度
    processing_time: float            # 处理耗时(秒)
```

---

## 三、数据存储层

**文件**: `persona_engine/storage/database.py`

### 3.1 数据库模型

| 表名 | 用途 |
|------|------|
| `personas` | 存储人格画像数据 |
| `rewrite_tasks` | 存储文本重写任务记录 |
| `video_processing_tasks` | 存储视频 ASR 提取任务的实时进度与状态 |

### 3.2 PersonaModel

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | String(36) | 主键 |
| `name` | String(255) | 人格名称 |
| `source_texts` | Text | JSON 格式的原始文本列表 |
| `style_keywords` | Text | JSON 格式的风格关键词 |
| `speaking_patterns` | Text | JSON 格式的说话模式 |
| `tone_markers` | Text | JSON 格式的语调标记 |
| `consistency_score` | Float | 一致性评分 |
| `status` | String(20) | 状态 |
| `created_at` | DateTime | 创建时间 |
| `updated_at` | DateTime | 更新时间 |

### 3.3 RewriteHistoryModel

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | String(36) | 主键 |
| `persona_id` | String(36) | 外键 |
| `source_text` | Text | 原文 |
| `rewritten_text` | Text | 重写后文本 |
| `style_match_score` | Float | 风格匹配度 |
| `content_similarity` | Float | 内容相似度 |
| `processing_time` | Float | 处理耗时 |
| `created_at` | DateTime | 创建时间 |

### 3.4 VideoProcessingTaskModel

视频处理任务模型，记录人格创建过程中的视频 ASR 提取进度。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | String(36) | 主键 (Task ID) |
| `persona_id` | String(36) | 外键，关联的人格 ID |
| `video_urls` | Text | JSON 格式，原始视频链接列表 |
| `completed_urls` | Text | JSON 格式，已完成的视频链接列表 |
| `failed_urls` | Text | JSON 格式，处理失败的视频链接列表 |
| `current_index` | Integer | 当前处理到的视频索引 |
| `status` | String(20) | 状态 (pending/processing/completed/failed/cancelled) |
| `asr_texts` | Text | JSON 格式，已提取的 ASR 文本集合 |
| `error_message` | Text | 错误详情 |
| `created_at` | DateTime | 创建时间 |
| `updated_at` | DateTime | 更新时间 |

---

## 四、数据仓储层

**文件**: `persona_engine/storage/persona_repo.py`

### 4.1 PersonaRepository

人格数据的 CRUD 操作：

| 方法 | 说明 |
|------|------|
| `create(name)` | 创建新人格 |
| `get(id)` | 获取人格 |
| `get_all()` | 获取所有人格 |
| `update(persona)` | 更新人格 |
| `delete(id)` | 删除人格 |
| `update_status(id, status)` | 更新状态 |

### 4.2 RewriteHistoryRepository

重写历史管理：

| 方法 | 说明 |
|------|------|
| `create(record)` | 创建记录 |
| `get_by_persona(persona_id)` | 获取某人格的所有历史 |
| `get_recent(persona_id, limit)` | 获取最近 N 条记录 |

### 4.3 VideoTaskRepository

视频处理任务仓储层，负责视频 ASR 提取任务的持久化与状态管理。

| 方法 | 说明 |
|------|------|
| `create(persona_id, urls)` | 初始化新视频处理任务 |
| `get_task(task_id)` | 获取任务详情 |
| `update_progress(task_id, url, asr_text, next_index)` | 原子化更新单个视频的处理进度 |
| `mark_as_cancelled(task_id)` | 将任务状态标记为已取消 |
| `get_active_tasks()` | 获取所有正在运行或排队中的任务 |
| `get_tasks_by_persona(persona_id)` | 获取指定人格下的所有任务记录 |

---

## 五、审计评分器

**文件**: `persona_engine/audit/scorer.py`

### 5.1 ConsistencyScorer

一致性评分器，用于评估生成文本与原有人格风格的一致性。

#### 主要方法

| 方法 | 说明 |
|------|------|
| `calculate_score(text, persona)` | 计算文本与人格的一致性评分 |
| `analyze_patterns(texts)` | 分析文本集合的风格模式 |

#### 评分维度

1. **关键词匹配**: 检查文本是否包含人格的风格关键词
2. **说话模式**: 评估句式结构和表达习惯
3. **语调标记**: 检查感叹词、语气词的使用

---

## 六、人格注入引擎

**文件**: `persona_engine/rewrite/persona_injector.py`

### 6.1 PersonaInjector

人格注入引擎，将源文本重写为指定人格的风格。

#### 主要方法

| 方法 | 说明 |
|------|------|
| `inject_style(request)` | 执行人格风格注入 |
| `_build_prompt(request)` | 构建 Prompt |
| `_call_llm(prompt)` | 调用 LLM |
| `_post_process(text)` | 后处理 |

#### Prompt 构建策略

1. **系统提示词**: 包含人格的风格描述
2. **Few-shot 示例**: 提供 1-2 个风格示例
3. **参数控制**: 通过参数控制保留度和风格强度

#### 后处理规则

- 移除多余的空白字符
- 确保句子完整
- 保留必要的标点符号

---

## 七、B站视频下载器

**文件**: `persona_engine/asr/bilibili_downloader.py`

### 7.1 BilibiliDownloader

基于 yt-dlp 的 B站视频下载和 ASR 提取。

#### 主要方法

| 方法 | 说明 |
|------|------|
| `download_audio(url, output_dir)` | 下载视频并提取音频 |
| `get_video_info(url)` | 获取视频信息 |
| `extract_asr(audio_path)` | 从音频提取 ASR 文本 |

#### 支持的 URL 格式

| 格式 | 示例 |
|------|------|
| BV号 | `https://www.bilibili.com/video/BV1xx411c7mD` |
| AV号 | `https://www.bilibili.com/video/av170001` |
| B站短链 | `https://b23.tv/xxxxxx` |
| UP主空间 | `https://space.bilibili.com/UID` |

#### ASR 提取流程

1. 使用 yt-dlp 下载视频（仅音频流）
2. 调用 Whisper 模型进行语音识别
3. 返回时间戳文本

### 7.2 配置参数

```yaml
bilibili:
  cookie: ""           # B站登录Cookie
  access_token: ""      # TV/App接口Token
  min_interval: 3.0     # 请求间隔最小值(秒)
  max_interval: 10.0   # 请求间隔最大值(秒)
  max_retries: 5        # 最大重试次数
  user_agent: "..."     # User-Agent
```

---

## 八、API 路由

**文件**: `main.py` (内联)

### 8.1 人格管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/v1/personas` | 获取所有人格 |
| `POST` | `/v1/personas` | 创建新人格 |
| `GET` | `/v1/personas/{id}` | 获取指定人格 |
| `PUT` | `/v1/personas/{id}` | 更新人格 |
| `DELETE` | `/v1/personas/{id}` | 删除人格 |
| `GET` | `/v1/personas/{id}/profile` | 获取人格画像 |

### 8.2 重写服务

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/v1/rewrite` | 执行文本重写 |
| `GET` | `/v1/personas/{id}/history` | 获取重写历史 |

### 8.3 配置管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/v1/config` | 获取所有配置 |
| `GET` | `/v1/config/{section}` | 获取指定配置 |
| `PUT` | `/v1/config/{section}` | 更新指定配置 |

### 8.4 健康检查

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |

### 8.5 任务管理 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/v1/video-tasks` | 分页获取所有视频处理任务列表 |
| `GET` | `/v1/video-tasks/{id}` | 获取特定任务的实时进度 |
| `DELETE` | `/v1/video-tasks/{id}` | 取消任务（触发后台 Checkpoint 强杀逻辑） |
| `POST` | `/v1/video-tasks/{id}/resume` | 从断点处继续执行未完成的任务 |
| `POST` | `/v1/video-tasks/{id}/retry-failed` | 重试失败的视频 |

**取消任务触发流程：**
1. 将 `personas.raw_json.status` 置为 `"cancelled"`
2. 后台协程通过检查点 `_is_task_cancelled()` 检测到取消状态
3. `extract_asr_with_checkpoint()` 的 watcher 协程向 Whisper 子进程发送 `SIGTERM`
4. 临时音频文件自动清理

---

## 九、配置管理

**文件**: `config.yaml`

### 9.1 配置结构

```yaml
server:
  host: "0.0.0.0"
  port: 7860
  reload: false

bilibili:
  cookie: ""
  access_token: ""
  min_interval: 3.0
  max_interval: 10.0
  max_retries: 5

# ============================================================
# LLM 供应商：MiniMax
# 文本重写引擎使用 MiniMax 提供的大模型能力
# ============================================================
minimax:
  api_key: "用户的 API Key"
  base_url: "https://api.minimax.chat/v1"
  model: "abab6.5-chat"  # 或其他指定模型
  tokens_limit: 4096

whisper:
  model: "base"
  device: "auto"
  language: "zh"

audit:
  min_consistency_score: 0.9  # 一致性评分阈值
  scoring_weights:
    verbal_tic_match: 0.08     # 口头禅匹配权重
    grammar_prefs: 0.20        # 语法偏好权重
    term_preservation: 0.30    # 术语保留权重（硬约束，需 100%）
    rhythm_alignment: 0.42     # 节奏一致性权重
```

---

## 十、Web UI

**文件**: `web_ui.html`

### 10.1 功能模块

| 模块 | 说明 |
|------|------|
| 人格管理 | 创建、查看、删除人格 |
| 文本重写 | 输入文本，执行重写 |
| 配置面板 | 设置 B站 Cookie 等 |
| 重写历史 | 查看历史记录 |

### 10.2 交互流程

1. **创建人格**: 输入人格名称 → 添加视频URL → 点击创建
2. **执行重写**: 选择人格 → 输入文本 → 设置参数 → 点击重写
3. **查看结果**: 展示重写结果和风格评分

---

## 十一、启动与部署

### 11.1 本地启动

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
python main.py
```

### 11.2 Docker 部署 (可选)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

---

---

## 十二、系统特性

### 12.1 高并发支持

SQLite 采用 **WAL (Write-Ahead Logging)** 模式，支持 Web UI 高频轮询：

```python
# 开启 WAL 模式的 SQL 语句
cursor.execute("PRAGMA journal_mode=WAL")
cursor.execute("PRAGMA synchronous=NORMAL")
```

| 特性 | 说明 |
|------|------|
| 并发读写 | WAL 模式允许多个读事务与一个写事务并发执行 |
| 读写阻塞降低 | 写操作不会阻塞读操作，反之亦然 |
| 适用场景 | Web UI 每 3-5 秒轮询任务进度 |

### 12.2 资源保护机制

任务取消时会自动发送 **SIGTERM** 信号给 Whisper 子进程，确保本地显存立即释放：

```
用户点击"取消"
  → DELETE /v1/video-tasks/{id}
    → task_registry.cancel() 取消 asyncio 协程
    → persona_repo.update(raw_json.status="cancelled")
      → 后台任务检查点 _is_task_cancelled() 检测到 cancelled
        → extract_asr_with_checkpoint() 的 watcher 协程调用 process.terminate()
          → Whisper 子进程被 SIGTERM 强制终止 (2-3 秒内)
            → 临时音频文件被清理
```

### 12.3 断点续传

视频处理任务支持断点续传：

1. 每个视频处理完成后立即更新 `current_index` 到数据库
2. 服务器重启后，扫描 `status=processing` 的任务
3. 从 `current_index + 1` 继续处理未完成的视频

### 12.4 动态超时保护

| 配置项 | 说明 |
|------|------|
| `VIDEO_TIMEOUT_SECONDS` | 单个视频处理超时（默认 300 秒） |
| `whisper_config.timeout` | Whisper 转写超时 |
| `space_downloader` | 空间视频获取超时（60 秒） |

---

*文档版本: 2.0*
*最后更新: 2026-04-13*
