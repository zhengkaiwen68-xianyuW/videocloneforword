# 深度审查标准检查清单 (CODE_REVIEW_CHECKLIST.md)

> AI 助手读取指引：当你接收到本项目相关的代码编写、修改或审查任务时，必须首选加载并阅读本清单。持续维护：如果在后续开发中发现了新的 Bug 或架构缺陷，必须将该 Bug 的特征、原因及预防措施总结并追加到本清单的"历史故障库"中。强制自检：在输出任何代码方案前，请对照以下准则逐一排查，并在回复中声明已通过自检。

---

## 一、 语法与依赖规范 (Syntax & Imports)

- [ ] SQLAlchemy 导入对齐：在使用 `desc()`, `func()`, `update()`, `select()` 等 ORM 函数时，必须确认文件顶部已从 `sqlalchemy` 正确导入。
- [ ] 死代码清理：严禁保留未使用的 `import`（如残留的 `aiohttp` 或 `os`），保持代码库纯净。
- [ ] 类型声明：所有 Repository 和 Service 层的方法必须标注类型注解，确保静态分析工具能捕捉类型不匹配。

---

## 二、 异步与并发安全 (Async & Concurrency)

- [ ] Await 完整性：所有被定义为 `async def` 的方法，在调用时必须使用 `await`。特别注意 LLM 接口和数据库 IO 接口。
- [ ] 非阻塞隔离：严禁在 FastAPI 的 async 事件循环中直接执行 CPU 密集型（如模型计算）或 IO 阻塞型（如 yt-dlp 下载）操作。必须使用 `asyncio.to_thread()` 或 `ProcessPoolExecutor`。
- [ ] 闭包变量捕获：在 for 循环中定义 lambda 或 `add_done_callback` 时，必须使用默认参数绑定（如 `tid=task_id`），严禁直接捕获循环变量名。
- [ ] Utility 函数边界测试：所有公共 utility 函数（如 `is_cancelled()`、`get()`）必须测试边界条件：空字符串、None、未注册的 ID。
- [ ] 集成测试覆盖：核心业务流程（下载→ASR→人格提取、重写→审计）必须有集成测试串烧验证，不能仅靠单元测试。

---

## 三、 数据完整性与持久化 (Data & Storage)

- [ ] 全链路字段对齐：修改数据库 Model 时，必须同步更新 PersonaRepository 的转换逻辑、`core/types.py` 中的数据类以及 API 的 Response 模型。
- [ ] 序列化无损还原：对于存储在 `raw_json` 中的嵌套对象（如 `deep_psychology`），在读取时必须有显式的解析与实例化逻辑，严禁返回空对象或丢失深度特征。
- [ ] 高效聚合查询：统计记录总数严禁使用 `len(result.all())`（会加载全表数据），必须使用 `select(func.count()).select_from(...)`。

---

## 四、 基础设施专项 (Infrastructure)

### 4.1 B 站下载器 (Bilibili Downloader)

- [ ] Cookie 存活预检：批量任务开始前必须调用鉴权接口检查 Cookie 有效性，失效时立即熔断并通知用户，防止封禁 IP。
- [ ] 多模式切换：优先支持 `api_mode: "app"` 或 `"tv"` 绕过 Web 端严格的 WBI 签名风控。
- [ ] 指数退避重试：捕获 412 Precondition Failed 后必须执行指数退避逻辑。
- [ ] JSON 输出隔离：subprocess 执行 yt-dlp 时必须添加 `quiet=True`，并实现 JSON 正则提取兜底，防止进度条污染 stdout。

### 4.2 Whisper ASR 模块

- [ ] 显存彻底释放：Whisper 推理必须在独立子进程中运行。当任务取消时，必须通过 SIGTERM 或重启进程池来物理回收显存。
- [ ] VAD 时间轴校准：使用 `vad_filter` 时，需确保 VoiceAnalyzer 计算停顿时考虑了 VAD 导致的静音切除偏移。

---

## 五、 历史故障库 (Historical Bug Database)

| ID | 故障现象 | 根本原因 | 预防措施 |
|---|---|---|---|
| #001 | `desc` NameError，导致视频任务列表接口崩溃 | `persona_repo.py` 漏导 `desc` from sqlalchemy | 强制执行"语法与依赖规范"检查 |
| #002 | 任务取消不掉 Whisper，协程阻塞且未销毁进程 | 取消标志轮询间隔过长且子进程未强杀 | 使用多进程模式并轮询取消标志 |
| #003 | 重写版本数据丢失 | Model 与 Profile 转换逻辑未覆盖 `deep_psychology` | 执行"数据完整性"交叉检查 |
| #004 | 任务进度更新 TypeError，导致视频处理崩溃 | 业务函数参数定义与 Repository 不匹配（`failed_urls` 遗漏） | 强制检查函数签名的一致性 |
| #005 | 内存注册表注销错误，batch 任务 callback 指向错误 task_id | 循环中 lambda 捕获了错误的 `task_id`（闭包变量延迟绑定） | 循环内回调必须使用默认参数绑定 |
| #006 | `server.py --reload` 模式启动必崩，NameError: `os` is not defined | `os.system()` 被调用但文件头未 `import os` | 每次新增系统调用后必须检查对应 import |
| #007 | Whisper 推理期间整个 API 服务无响应（所有请求超时） | `transcriber.transcribe()` 是同步阻塞调用，直接在 async 协程中调用会阻塞整个事件循环 | 所有同步 IO/CPU 密集调用必须包裹在 `asyncio.to_thread()` 中 |
| #008 | `GET /v1/personas` 等接口返回的人格数据中 `deep_psychology` 字段丢失 | `PersonaResponse` Pydantic 模型定义中漏加 `deep_psychology` 字段，导致 FastAPI 序列化时直接忽略该字段 | 修改数据类后必须同步更新对应的 API Response Model，执行"全链路字段对齐"检查 |
| #009 | 任务取消或超时后 Whisper 仍占用 VRAM，下次转写 OOM | `asyncio.to_thread` + CLI subprocess 两条路径均无法物理终止 CUDA 进程，显存不释放 | 所有 Whisper 推理必须通过 `WhisperWorker` 进程池单例，取消时调用 `_restart_executor()` 物理回收 |
| #010 | 30 个视频任务重复加载 Whisper large-v3，每视频额外耗时 5-10 秒，VRAM 反复分配 | 每次 `WhisperTranscriber()` 实例化或启动 CLI subprocess 都会从磁盘重新加载模型 | 使用 `WhisperWorker` ProcessPoolExecutor 单例：模型常驻子进程，仅取消/故障时重建 |
| #011 | `excitement_curve` 停顿归属计算错误（语速不均匀时某段停顿会被算入错误片段） | `sum(1 for w in words if w.end <= p.start)` 用词数量索引代替时间戳比较，O(n²) 且逻辑错误 | 改用 `seg_start_time <= p.start < seg_end_time` 时间戳区间比较，O(n) 且语义正确 |
| #012 | 视频处理"卡死"，所有 ASR 转写返回 None，但无错误日志 | `task_registry.is_cancelled()` 对从未注册的任务返回 True（默认值 0 == 0） | 对未注册任务应返回 False；utility 函数必须测试边界条件（空、None、未注册） |
| #013 | 断点续传启动时，失败的任务被错误标记为 completed | `remaining_urls` 计算时排除了 `failed_urls`，导致"所有视频都处理完"的错误判断 | 失败的视频不应参与 remaining 计算；断点续传只恢复 pending 状态任务 |
| #014 | 人格提取成功但更新失败，`NOT NULL constraint failed: personas.name` | `author_name=None` 传入人格提取器，生成的人格 name 为 None | 注释"保持原有名称"应传入原 persona.name，而非 None |
| #015 | B站视频下载后 JSON 解析失败，错误信息包含 yt-dlp 进度输出 | yt-dlp 默认输出进度条到 stdout，混入 JSON 导致解析失败 | 添加 `quiet=True` 抑制输出；添加 JSON 正则提取兜底 |
| #016 | 服务重启后端口冲突，旧进程未完全终止导致新服务启动失败 | `taskkill` 命令执行时机不当，进程未完全释放端口即启动新服务 | 使用 `wait=True` 确保进程完全终止；启动前检查端口可用性 |
