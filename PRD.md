# 短视频人格深度重构与洗稿引擎 - PRD

> 产品需求文档，用于持续迭代

---

## 一、项目概述

### 1.1 项目背景

在短视频内容创作领域，创作者常常面临两个痛点：
1. **风格难以复制**: 想要学习某个喜欢的 UP 主风格，但难以系统性地提取和学习
2. **内容洗稿效率低**: 需要将一篇内容改写成不同风格，纯人工操作耗时且效果不稳定

### 1.2 核心价值

本项目通过 AI 技术实现了**短视频人格深度重构**，可以：
- 从 B站 视频自动提取 UP 主的语音内容（ASR）
- 分析并构建该 UP 主的内容风格画像
- 使用学习到的风格，将任意文本改写成匹配该风格的文案

### 1.3 目标用户

| 用户类型 | 使用场景 |
|----------|----------|
| 短视频创作者 | 学习对标账号风格，快速生成同风格文案 |
| 内容运营 | 批量改写内容，适应不同平台风格 |
| MCN 机构 | 标准化内容生产流程，保持账号风格一致性 |

### 1.4 核心功能

| 功能 | 说明 | 优先级 |
|------|------|--------|
| B站视频人格提取 | 从视频 URL 或 UP 主空间自动提取人格风格 | P0 |
| 人格画像构建 | 分析文本风格，生成结构化风格描述 | P0 |
| 文本风格重写 | 使用指定人格风格重写新文本 | P0 |
| 一致性评分 | 评估重写结果与目标风格的一致性 | P1 |
| Web UI 管理 | 图形化界面管理人格和执行重写 | P1 |
| 配置管理 | 支持 B站 Cookie 等配置 | P1 |

### 1.5 系统架构图

```
+---------------------------------------------------------------------+
|                         Web UI                                      |
|  (人格管理 / 文本重写 / 配置面板 / 历史记录)                            |
+-----------------------------+---------------------------------------+
                              | HTTP API
+-----------------------------v---------------------------------------+
|                      FastAPI Server                                 |
|  +-------------+  +-------------+  +-------------+                  |
|  |  人格管理   |  |   重写服务   |  |   配置管理   |                  |
|  +------+------+  +------+------+  +-------------+                  |
|         |                |                                           |
|  +------v----------------v------+                                  |
|  |        Persona Engine         |                                  |
|  |  +---------+ +-------------+  |                                  |
|  |  |  评分器  | | 人格注入引擎 |  |                                  |
|  |  +---------+ +-------------+  |                                  |
|  +-------------------------------+                                  |
|         |                                                           |
|  +------v----------------------------------------------+           |
|  |              ASR 模块                                |           |
|  |  +-----------------+ +-----------------+            |           |
|  |  | B站视频下载器    | |  Whisper 语音识别|            |           |
|  |  +-----------------+ +-----------------+            |           |
|  +----------------------------------------------------+           |
+-----------------------------+---------------------------------------+
                              |
+-----------------------------v---------------------------------------+
|                   SQLite Database                                   |
|  +-------------+  +-----------------+  +----------------+          |
|  |  personas   |  | rewrite_history  |  |     config     |          |
|  +-------------+  +-----------------+  +----------------+          |
+---------------------------------------------------------------------+
```

---

## 二、问题记录

### 2.1 已知问题

| 日期 | 问题描述 | 状态 | 备注 |
|------|----------|------|------|
| 2026-04-11 | 后台任务挂死但数据库状态仍为 processing | 已修复 | 原因：任务崩溃但未更新状态 |
| 2026-04-11 | asyncio.create_task 任务在进程重启后丢失 | 已修复 | 改用启动时清理机制 |
| 2026-04-11 | 任务进度更新不及时（每3个视频才更新） | 已修复 | 改为每完成1个视频即更新 |
| 2026-04-11 | 服务器重启后任务无法断点续传 | 已修复 | 实现任务持久化，添加中断任务查询 |
| 2026-04-11 | 无法主动取消/删除正在处理的任务 | 已修复 | 添加 DELETE /v1/tasks/{id} 接口 |
| 2026-04-12 | B站下载触发412反爬限制 | 已修复 | 添加Cookie认证、指数退避重试、可配置请求间隔 |
| 2026-04-12 | 无法从B站UP主空间链接创建人格 | 已修复 | 支持 space.bilibili.com/UID，自动获取30个视频 |
| 2026-04-13 | SQLite 数据库在高频轮询进度时出现 database is locked | 已修复 | 增加 timeout 并开启 WAL(Write-Ahead Logging) 模式 |
| 2026-04-13 | 取消任务无法打断底层 Whisper 推理，导致资源持续占用 | 已修复 | 引入 Checkpoint 机制，通过协程实时监控状态并向子进程发送 SIGTERM 强制释放显卡资源 |

### 2.2 待确认问题

- **历史 processing 状态的人格清理后是否需要删除？**
  *结论：采用条件清理策略。若取消时未提取任何有效语料（asr_texts 为空），则触发物理删除清理脏数据；若已有部分成功语料，将其状态标记为 partial_completed 保留。*
- **任务超时阈值是否需要可配置？**
  *结论：废弃硬编码的 5 分钟限制。因视频时长差异极大，后续迭代将采用动态超时机制（如网络流中断超 60 秒或基于视频时长计算动态阈值）。*

---

## 三、核心需求

### 3.1 任务管理系统

**目标：** 实现完整的视频处理任务生命周期管理

| 功能 | 优先级 | 描述 |
|------|--------|------|
| 实时进度 | P0 | 每处理完1个视频立即更新到数据库 |
| 断点续传 | P0 | 服务器重启后能检测未完成任务并继续 |
| 任务取消 | P0 | 可主动删除/取消正在处理的任务 |
| 任务列表 | P1 | 独立的任务管理面板，显示所有任务状态 |
| 日志查看 | P2 | 在 UI 上查看任务实时日志 |

**技术方案：**

1. **新建 `VideoProcessingTask` 表**
   ```
   - id: 任务ID
   - persona_id: 关联的人格ID
   - video_urls: 视频链接列表（JSON）
   - completed_urls: 已完成的视频URL列表（JSON）
   - failed_urls: 失败的视频URL列表（JSON）
   - current_index: 当前处理到第几个视频
   - status: pending/processing/completed/failed/cancelled
   - asr_texts: 已提取的ASR文本列表（JSON）
   - error_message: 错误信息
   - created_at: 创建时间
   - updated_at: 更新时间
   ```

2. **修改任务逻辑**
   - 每完成1个视频立即写入数据库
   - 任务启动时检查是否有未完成的同类任务
   - 使用数据库事务确保一致性

3. **新增 API 端点**
   - `GET /v1/video-tasks` - 任务列表
   - `GET /v1/video-tasks/{id}` - 任务详情
   - `DELETE /v1/video-tasks/{id}` - 取消任务
   - `POST /v1/video-tasks/{id}/resume` - 继续任务
   - `POST /v1/video-tasks/{id}/retry-failed` - 重试失败的视频

### 3.2 Web UI 增强

**目标：** 提供完善的任务监控和管理界面

| 功能 | 优先级 |
|------|--------|
| 任务监控面板（实时进度条 + 百分比） | P0 |
| 任务列表（显示所有视频处理任务） | P1 |
| 取消/删除任务按钮 | P1 |
| 操作日志面板 | P2 |

### 3.3 B站UP主空间人格创建

**目标：** 支持从B站UP主个人空间链接自动创建人格

| 功能 | 优先级 | 描述 |
|------|--------|------|
| 空间链接解析 | P0 | 支持 https://space.bilibili.com/UID 格式 |
| 自动获取30个视频 | P0 | 获取该UP主最新发布的30个视频 |
| 进度追踪 | P0 | 详细显示每个视频的处理进度 |

**技术方案：**

1. **新增 `BilibiliSpaceDownloader` 类**
   - 使用 yt-dlp 的 `BilibiliSpaceVideoIE` 提取器
   - 获取UP主空间视频列表（不下载，只获取元信息）
   - 支持按发布时间排序

2. **扩展 `PersonaCreateRequest`**
   ```python
   @dataclass
   class PersonaCreateRequest:
       name: str
       source_texts: list[str] = None
       video_urls: list[str] = None
       space_url: str = None  # 新增
   ```

3. **增强进度追踪**
   ```json
   {
     "status": "processing",
     "total_videos": 30,
     "completed_videos": 5,
     "failed_videos": 1,
     "current_video": {
       "index": 6,
       "phase": "downloading",
       "progress": 45.2,
       "bv_id": "BVxxx"
     }
   }
   ```

### 3.4 B站反爬优化配置

**目标：** 通过配置提升B站下载成功率

| 功能 | 优先级 | 描述 |
|------|--------|------|
| Cookie认证 | P0 | 配置B站登录Cookie，提高请求稳定性 |
| 指数退避重试 | P0 | 失败后等待时间指数增长，避免频繁触发412 |
| 可配置请求间隔 | P0 | 从配置读取请求间隔范围 |
| 前端设置界面 | P0 | Web UI提供设置面板，无需手动修改配置文件 |

**参考项目：** [BBDown](https://github.com/nilaoda/BBDown) - 成熟的B站下载器

**配置项：**
```yaml
bilibili:
  cookie: ""           # B站登录Cookie
  access_token: ""      # TV/App接口Token
  min_interval: 3.0     # 请求间隔最小值(秒)
  max_interval: 10.0    # 请求间隔最大值(秒)
  delay_per_page: 5.0  # 页面间延迟(秒)
  max_retries: 5        # 最大重试次数
  retry_base_delay: 2.0# 指数退避基数(秒)
  user_agent: "..."     # User-Agent
  api_mode: "web"      # web/tv/app/intl
```

**API端点：**
- `GET /v1/config/bilibili` - 获取B站配置
- `PUT /v1/config/bilibili` - 更新B站配置

---

## 四、架构设计

### 4.1 当前架构问题

```
用户请求 -> API -> asyncio.create_task() -> 内存任务对象
                                      |
                               进程崩溃 -> 任务丢失
                                      |
                               DB 状态永远是 processing
```

### 4.2 目标架构

```
用户请求 -> API -> DB 持久化任务 -> 后台协程执行
              |                    |
         每完成1个视频        立即更新 DB
              |                    |
         服务器重启 <-> 检测未完成任务 -> 从断点继续
```

### 4.3 关键文件修改清单

| 文件 | 修改内容 |
|------|----------|
| `storage/database.py` | 新增 VideoProcessingTaskModel |
| `storage/persona_repo.py` | 新增 VideoTaskRepository |
| `api/routes.py` | 新增任务管理端点，修改后台任务逻辑 |
| `asr/bilibili_downloader.py` | 可能需要拆分下载和转写 |
| `web_ui.html` | 新增任务管理面板 |

---

## 五、API 设计

### 5.1 任务管理 API

#### GET /v1/video-tasks
获取所有视频处理任务

**响应：**
```json
{
  "tasks": [
    {
      "id": "task_xxx",
      "persona_id": "xxx",
      "persona_name": "聪聪测试",
      "status": "processing",
      "total_videos": 19,
      "completed_videos": 5,
      "failed_videos": 0,
      "progress_percent": 26,
      "created_at": "2026-04-11T21:00:00Z",
      "updated_at": "2026-04-11T21:05:00Z"
    }
  ],
  "total": 1
}
```

#### GET /v1/video-tasks/{task_id}
获取指定任务详情

**响应：**
```json
{
  "id": "task_xxx",
  "persona_id": "xxx",
  "persona_name": "聪聪测试",
  "status": "processing",
  "total_videos": 19,
  "completed_videos": 5,
  "failed_videos": 0,
  "progress_percent": 26,
  "video_urls": ["url1", "url2", ...],
  "completed_urls": ["url1", "url2", ...],
  "failed_urls": [],
  "asr_texts": ["text1", "text2", ...],
  "error_message": null,
  "created_at": "2026-04-11T21:00:00Z",
  "updated_at": "2026-04-11T21:05:00Z"
}
```

#### DELETE /v1/video-tasks/{task_id}
取消/删除任务

**响应：**
```json
{
  "task_id": "task_xxx",
  "status": "cancelled",
  "message": "任务已取消"
}
```

#### POST /v1/video-tasks/{task_id}/resume
继续执行被中断的任务

**响应：**
```json
{
  "task_id": "task_xxx",
  "status": "resumed",
  "message": "任务已从第6个视频继续"
}
```

---

## 六、数据流

### 6.1 任务创建流程

1. 用户提交视频链接创建人格
2. API 创建 `Persona`（状态=processing）
3. API 创建 `VideoProcessingTask`（status=pending）
4. 后台协程从第1个视频开始处理
5. 每完成1个视频：更新 `VideoProcessingTask.completed_urls` + `asr_texts` + `current_index`
6. 全部完成后：更新人格画像，标记任务 completed

### 6.2 任务恢复流程（服务器重启后）

1. 服务器启动时扫描所有 `processing` 状态的任务
2. 检查任务的 `current_index` vs `video_urls` 长度
3. 如果有未完成视频：从 `current_index + 1` 继续处理
4. 如果全部完成：标记任务 completed，更新人格

### 6.3 任务取消流程

1. 用户点击取消任务
2. API 标记任务 status=cancelled
3. 后台协程检测到 cancelled 状态，停止执行
4. 清理临时文件

---

## 七、非功能性需求

| 需求 | 描述 |
|------|------|
| 容错性 | 单个视频失败不影响其他视频 |
| 超时保护 | 单个视频处理超时（5分钟）自动跳过 |
| 资源清理 | 任务完成后清理临时音频文件 |
| 可观测性 | 详细的日志记录，方便排查问题 |

### 7.1 日志规范（可观测性要求）

**目标**：确保关键节点有日志记录，便于问题排查和系统监控。

#### 需要记录日志的关键节点

| 场景 | 日志级别 | 应记录内容 | 示例 |
|------|----------|------------|------|
| 任务开始 | INFO | task_id、视频URL数量 | `开始处理任务 {task_id}，共 {count} 个视频` |
| 任务成功 | INFO | 完成状态、耗时 | `任务 {task_id} 完成，耗时 {duration}s` |
| 任务失败 | ERROR | 错误信息、异常详情 | `任务 {task_id} 失败: {error}` |
| 条件判断分支 | WARNING | 判断依据、决策结果 | `is_cancelled=True（未注册任务），跳过处理` |
| 外部调用 | INFO | 调用目标、参数、结果 | `调用 MiniMax API，prompt长度={len}` |
| 状态转换 | INFO | 旧状态、新状态 | `任务状态从 pending -> processing` |
| 超时/重试 | WARNING | 超时时间、已等待 | `等待 {wait}s 后超时，开始重试` |

#### 日志规范

1. **必须包含 context**：每个日志必须有 task_id 或请求 ID，便于追踪
2. **静默失败必须记录**：返回 None/False 的分支要用 WARNING 记录
3. **"不应该发生"的分支**：用 assert 或 ERROR 记录
4. **避免日志污染**：不记录大对象（如完整音频数据、API 响应体）

#### 示例

```python
# 好的日志示例
logger.warning(
    f"[WhisperWorker][{task_id}] 任务被取消 "
    f"(cancelled_gen={gen}, task_gen={task_gen}, registered={is_registered})"
)

# 坏的日志示例
logger.debug("checking if cancelled")  # 缺少 context
logger.info("task completed")  # 缺少 task_id
```

#### 待补充日志清单

| 文件 | 当前状态 | 需要补充 |
|------|----------|----------|
| `whisper_worker.py` | 无 WARNING/ERROR 日志 | 取消判断、超时、异常 |
| `bilibili_downloader.py` | 基础日志 | 下载进度、JSON 解析失败 |
| `task_registry.py` | 无取消判断日志 | is_cancelled 的边界情况 |
| `routes.py` | 无详细错误日志 | 人格提取失败、视频处理异常 |

---

## 八、待办清单

### P0 (必须)
- [x] 设计 VideoProcessingTask 数据模型
- [x] 实现任务持久化（每完成1个视频即保存）
- [x] 实现任务断点续传
- [x] 实现任务取消功能
- [x] B站UP主空间链接创建人格
- [x] B站反爬优化配置（Cookie/指数退避）

### P1 (应该)
- [ ] 新增 GET /v1/video-tasks 端点
- [ ] 新增 DELETE /v1/video-tasks/{id} 端点
- [ ] 新增 POST /v1/video-tasks/{id}/resume 端点
- [ ] Web UI 任务监控面板
- [ ] Cookie自动刷新机制

### P2 (可以)
- [ ] 操作日志面板
- [ ] 失败视频重试功能
- [ ] 代理IP支持
- [ ] 多API模式切换（TV/App）
- [ ] 任务超时可配置

---

*最后更新：2026-04-14*
