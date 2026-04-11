# 短视频人格深度重构与洗稿引擎 - PRD

> 项目问题记录与需求文档，用于持续迭代

---

## 一、问题记录

### 1.1 已知问题

| 日期 | 问题描述 | 状态 | 备注 |
|------|----------|------|------|
| 2026-04-11 | 后台任务挂死但数据库状态仍为 processing | 已修复 | 原因：任务崩溃但未更新状态 |
| 2026-04-11 | asyncio.create_task 任务在进程重启后丢失 | 已修复 | 改用启动时清理机制 |
| 2026-04-11 | 任务进度更新不及时（每3个视频才更新） | 待修复 | 需改为每完成1个视频即更新 |
| 2026-04-11 | 服务器重启后任务无法断点续传 | 待修复 | 需实现任务持久化 |
| 2026-04-11 | 无法主动取消/删除正在处理的任务 | 待修复 | 需实现任务管理功能 |

### 1.2 待确认问题

- [ ] 历史 processing 状态的人格清理后是否需要删除？
- [ ] 任务超时阈值是否需要可配置？

---

## 二、核心需求

### 2.1 任务管理系统

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

### 2.2 Web UI 增强

**目标：** 提供完善的任务监控和管理界面

| 功能 | 优先级 |
|------|--------|
| 任务监控面板（实时进度条 + 百分比） | P0 |
| 任务列表（显示所有视频处理任务） | P1 |
| 取消/删除任务按钮 | P1 |
| 操作日志面板 | P2 |

---

## 三、架构设计

### 3.1 当前架构问题

```
用户请求 → API → asyncio.create_task() → 内存任务对象
                                      ↓
                               进程崩溃 → 任务丢失
                                      ↓
                               DB 状态永远是 processing
```

### 3.2 目标架构

```
用户请求 → API → DB 持久化任务 → 后台协程执行
              ↓                    ↓
         每完成1个视频        立即更新 DB
              ↓                    ↓
         服务器重启 ←→ 检测未完成任务 → 从断点继续
```

### 3.3 关键文件修改清单

| 文件 | 修改内容 |
|------|----------|
| `storage/database.py` | 新增 VideoProcessingTaskModel |
| `storage/persona_repo.py` | 新增 VideoTaskRepository |
| `api/routes.py` | 新增任务管理端点，修改后台任务逻辑 |
| `asr/bilibili_downloader.py` | 可能需要拆分下载和转写 |
| `web_ui.html` | 新增任务管理面板 |

---

## 四、API 设计

### 4.1 任务管理 API

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

## 五、数据流

### 5.1 任务创建流程

1. 用户提交视频链接创建人格
2. API 创建 `Persona`（状态=processing）
3. API 创建 `VideoProcessingTask`（status=pending）
4. 后台协程从第1个视频开始处理
5. 每完成1个视频：更新 `VideoProcessingTask.completed_urls` + `asr_texts` + `current_index`
6. 全部完成后：更新人格画像，标记任务 completed

### 5.2 任务恢复流程（服务器重启后）

1. 服务器启动时扫描所有 `processing` 状态的任务
2. 检查任务的 `current_index` vs `video_urls` 长度
3. 如果有未完成视频：从 `current_index + 1` 继续处理
4. 如果全部完成：标记任务 completed，更新人格

### 5.3 任务取消流程

1. 用户点击取消任务
2. API 标记任务 status=cancelled
3. 后台协程检测到 cancelled 状态，停止执行
4. 清理临时文件

---

## 六、非功能性需求

| 需求 | 描述 |
|------|------|
| 容错性 | 单个视频失败不影响其他视频 |
| 超时保护 | 单个视频处理超时（5分钟）自动跳过 |
| 资源清理 | 任务完成后清理临时音频文件 |
| 可观测性 | 详细的日志记录，方便排查问题 |

---

## 七、待办清单

### P0 (必须)
- [ ] 设计 VideoProcessingTask 数据模型
- [ ] 实现任务持久化（每完成1个视频即保存）
- [ ] 实现任务断点续传
- [ ] 实现任务取消功能

### P1 (应该)
- [ ] 新增 GET /v1/video-tasks 端点
- [ ] 新增 DELETE /v1/video-tasks/{id} 端点
- [ ] 新增 POST /v1/video-tasks/{id}/resume 端点
- [ ] Web UI 任务监控面板

### P2 (可以)
- [ ] 操作日志面板
- [ ] 失败视频重试功能
- [ ] 任务超时可配置

---

*最后更新：2026-04-11*
