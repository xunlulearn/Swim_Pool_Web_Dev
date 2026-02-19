# NTU Pool 后端架构与核心逻辑总览（检索版）

更新时间：2026-02-19  
适用范围：NTU Pool 当前代码库（Flask + Supabase + LangGraph）

---

## 0. 文档目的

本文件将项目内 Markdown 文档中与后端相关的信息做统一整合，目标是：

1. 让 Chatbot 在“后端规则/架构/参数/排障”问题上有稳定可检索语料。
2. 提供一份可直接问答的后端知识底稿（包含规则、阈值、数据流、接口契约）。
3. 降低 FAQ 被切分后“只命中问题不命中答案”导致的答非所问风险。

---

## 1. 系统后端总览

### 1.1 后端技术栈

- Web 框架：Flask
- 向量检索：Supabase pgvector（`pool_documents` + `match_documents`）
- LLM 调用：OpenAI 兼容 API（可走 OpenRouter）
- Chatbot 编排：LangGraph + LangChain
- 关系数据：PostgreSQL（应用业务数据）

### 1.2 核心后端模块（按职责）

- 应用入口：`app/__init__.py`
- 配置源：`app/config.py` + `.env`
- 天气状态：`app/services/weather_engine.py` + `app/blueprints/weather.py`
- 实时上报接口：`app/blueprints/live_status.py`
- 社区业务：`app/blueprints/social.py`
- Chatbot API：`app/blueprints/chatbot.py`
- Chatbot 核心图：`app/services/chatbot/graph.py`
- 知识同步：`sync_knowledge_base.py`
- Supabase 初始化：`init_supabase.sql`

### 1.3 对外关键能力

- 泳池状态判定（天气 + 社区上报双源）
- 社区帖子/评论/点赞/收藏/私信
- 登录后 Chatbot 问答（意图路由 + RAG + DB 工具查询）
- 聊天会话持久化与五星反馈

---

## 2. 泳池状态引擎逻辑（Weather + Community）

### 2.1 数据来源

- NEA Lightning API（雷电）
- NEA Rainfall API（降雨）
- 用户手动上报（已登录且已验证用户）

### 2.2 状态优先级（从高到低）

1. 营业时间校验（不在营业时段直接 CLOSED）
2. 社区一致性共识（满足严格条件时可覆盖天气判断）
3. 雷电告警（<= 15km）
4. 暴雨告警（> 5mm/h）
5. 默认 OPEN

### 2.3 关键阈值与持续窗口

- 雷电关闭阈值：最近雷电距离 <= 15km
- 雷电冷却窗口：45 分钟（窗口内保持关闭）
- 降雨关闭阈值：雨强 > 5mm/h
- 降雨冷却窗口：30 分钟
- 社区共识窗口：30 分钟内最近 5 条、5 个不同用户、状态一致、且最新上报不超过 10 分钟

### 2.4 更新频率与延迟说明

- 前端轮询后端：约 60 秒
- 后端状态缓存：约 30 秒
- NEA 数据存在固有延迟：约 1–3 分钟
- 降雨数据额外延迟可约 10 分钟

### 2.5 安全兜底原则

- 现场救生员指令优先于系统状态。
- 系统状态用于参考，不替代现场安全决策。

---

## 3. 账号与权限（IAM）

### 3.1 角色

- Guest：未登录
- User：普通已登录用户
- Admin：管理员

### 3.2 关键权限点

- 仅登录且验证用户可发布帖子、评论、点赞、收藏、私信、手动上报
- 管理员可置顶、封禁、举报审核等
- 未登录用户可浏览公开信息，但不可提交受限操作

### 3.3 安全控制

- 邮箱 OTP 验证（6 位验证码）
- 密码修改需 OTP 校验
- CSRF 保护覆盖状态变更请求（POST/PUT/PATCH/DELETE）
- 上传类型约束：JPEG/PNG
- 上传大小遵循 `MAX_CONTENT_LENGTH`（默认约 2MB）

---

## 4. 社区后端逻辑（Social）

### 4.1 数据模型（核心）

- `User`
- `Post`
- `Comment`（支持楼中楼，最多两层）
- `Like` / `CommentLike` / `Collection`
- `ContentReport`
- `PrivateMessage`

### 4.2 业务规则

- 帖子与评论采用软删除（`is_deleted=True`）
- 默认列表过滤软删除内容
- 楼中楼回复：子回复统一挂到顶级评论，并用 `reply_to_user_id` 标识被回复对象
- 被封禁用户不可发送私信

### 4.3 常见路由族

- 社区主路径：`/social/*`
- 帖子：创建、编辑、删除、详情、置顶
- 评论：创建、回复、删除、点赞
- 举报：帖子举报、评论举报、管理员处理
- 私信：会话列表、会话消息、未读计数

---

## 5. Chatbot 后端架构

### 5.1 API 入口

- `POST /api/chat`：标准非流式问答
- `POST /api/chat/stream`：流式返回（SSE 样式）
- `POST /api/chat/feedback`：提交评分（1-5）

### 5.2 登录与会话约束

- Chatbot 发送消息需登录
- 每条成功问答会写入 `chatbot_conversations`
- 按用户累计消息计数（5/10/15...）触发反馈请求

### 5.3 意图路由

意图类型：

- `small_talk`：闲聊，直接 LLM
- `database`：数据库工具链（帖子/评论/上报查询）+ 总结
- `knowledge_base`：向量检索 + RAG
- `fallback`：超范围或不明确问题

### 5.4 当前问答主链路（简化）

1. 输入预处理：识别语言，必要时翻译为英文用于意图与检索
2. 意图分类：意图模型 + 启发式兜底
3. 检索阶段：
   - 小聊/数据库/fallback 走对应分支
   - 知识库问题走向量检索
4. 生成阶段：基于上下文回答；上下文不足时返回 I do not know 并给引导问题
5. 本地化阶段：按用户输入语言返回结果

### 5.5 检索稳健性策略（关键）

- 候选池扩大：避免 ANN 低 `k` 漏召回
- `min_score` 阈值过滤（环境可调）
- 低置信 fallback：只保留接近最佳分的小窗口，避免噪声上下文
- 薄上下文补齐：当只命中少量 chunk 时补充近阈值支持 chunk（优先同源）
- 关键词重排：在低分/补齐阶段按 query 词面重合增强排序稳定性
- 后端规则问题：保留 backend snapshot 作为兜底，但不跳过向量检索

---

## 6. 向量知识库与同步机制

### 6.1 向量表与检索函数

- 表：`pool_documents`
- 函数：`match_documents(query_embedding, match_count, filter)`

### 6.2 数据来源（同步脚本）

`sync_knowledge_base.py` 默认会同步：

- `ntupool.org` 页面（sitemap 或路由发现回退）
- 实时状态快照 + 手动上报摘要
- 社区帖子与评论（可配上限）
- 后端非敏感配置快照
- `knowledge_base/` 目录下本地 Markdown

### 6.3 增量策略

- 通过 `doc_key + doc_hash` 做增量
- 新文档：插入
- 文档变化：删旧 chunk、插新 chunk
- 删除文档：删对应 chunk
- 支持 `--full-rebuild` 全量重建

### 6.4 关键同步参数（默认）

- `chunk_size = 500`
- `chunk_overlap = 50`
- `top_k = 3`（调试预览参数）
- ingest namespace：`ntupool_kb_sync_v1`

---

## 7. Supabase 契约（Chatbot 相关）

### 7.1 `pool_documents`

- `id`（uuid）
- `content`（text）
- `metadata`（jsonb）
- `embedding`（vector(1536)）
- `created_at`（timestamptz）

### 7.2 `chatbot_conversations`

- 会话基础：`id`, `created_at`, `user_id`
- 问答内容：`user_message`, `assistant_message`, `sources`
- 反馈流程：`message_counter`, `feedback_requested`, `rating_score`, `rating_submitted_at`
- 请求元数据：`request_ip`, `user_agent`
- 唯一约束：`(user_id, message_counter)`

---

## 8. 部署与运行要点

### 8.1 必需环境变量

- `DATABASE_URL`
- `OPENAI_API_KEY`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

### 8.2 常用可调参数

- `OPENAI_CHAT_MODEL`
- `OPENAI_EMBED_MODEL`
- `CHATBOT_INTENT_MODEL`
- `CHATBOT_TOP_K`
- `CHATBOT_MIN_SCORE`
- `CHATBOT_MAX_CONTEXT_CHARS`
- `CHATBOT_DB_TOOL_MAX_CALLS`

### 8.3 本地运行

- `dev.bat run`（通常 5000）
- `dev.bat run-server`（当前项目常用 5001）

---

## 9. 后端问题排障速查（问答型）

### Q1. 为什么某些知识库问题会返回 I do not know？

A：常见原因是“召回不足或阈值后上下文过薄”。检查 `CHATBOT_MIN_SCORE`、候选召回、chunk 切分与文档是否已同步入库。

### Q2. 为什么同一个问题英文能答、中文答不好？

A：系统会走“翻译 -> 检索 -> 生成 -> 回译”。若翻译丢失关键实体或检索语料不足，会导致结果波动。

### Q3. 后端规则类问题为什么有时答成泛泛内容？

A：如果检索只命中 snapshot 或单一 chunk，可能缺少 FAQ 解释段。应确保向量检索优先命中高相关 KB chunk，并保留 backend snapshot 仅作兜底。

### Q4. 如何确认新 Markdown 已进入向量库？

A：执行 `dev.bat sync`，然后用 `--debug-query` 做检索预览，确认 `source=kb://<file>.md` 出现在结果中。

### Q5. 为什么数据库问题会被路由到知识库？

A：意图模型异常或限流时会回退启发式；应检查意图模型可用性和路由规则边界（策略类 vs 数据检索类）。

---

## 9.1 English Retrieval FAQ (for embedding recall)

### Q: How does knowledge sync incremental update work?

A: `sync_knowledge_base.py` uses incremental sync by `doc_key + doc_hash`. It inserts new docs/chunks, updates changed docs/chunks, and deletes removed docs/chunks in the ingest namespace.

### Q: Which Supabase tables are used by chatbot?

A: Main chatbot tables are `pool_documents` (vector knowledge) and `chatbot_conversations` (chat logs + feedback metadata).

### Q: What is backend rules retrieval strategy in chatbot?

A: For backend-rules questions, chatbot still performs vector retrieval first. Backend snapshot documents are kept as fallback context when vector context is empty or insufficient.

### Q: What are key retrieval stability strategies?

A: Larger candidate pool, score threshold filtering, low-confidence narrow fallback, near-threshold support chunks, and keyword-overlap reranking.

### Q: What models are used in chatbot runtime?

A: Runtime model names are controlled by environment variables: `OPENAI_CHAT_MODEL`, `OPENAI_EMBED_MODEL`, and `CHATBOT_INTENT_MODEL`.

---

## 10. 参考来源（整合基线）

本总结优先整合以下 Markdown 文档中的后端信息：

- `README.md`
- `FileSpec.md`
- `CHATBOT_DEPLOY.md`
- `product_docs/product_overview.md`
- `product_docs/product_realtime_weather_status_engine.md`
- `product_docs/product_community_live_status.md`
- `product_docs/product_identity_access_management.md`
- `product_docs/product_social_network.md`
- `product_docs/product_pool_operating_hours.md`
- `product_docs/product_ui_ux_requirements.md`
- `product_docs/product_chatbot.md`
- `knowledge_base/README.md`
- `knowledge_base/faq.md`

说明：临时日志/流程草稿类 Markdown（例如 `_tmp_*`、`logs/*`）不作为后端事实规则来源，以避免把会话噪声写入长期知识库。
