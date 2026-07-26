# NTU Pool Chatbot 修复报告

**日期**：2026-07-26
**范围**：ntupool.org 智能助手（chatbot）准确率与可用性
**测试方式**：管理员已登录会话，通过 `/api/chat` 走**线上生产链路**实测（真实向量检索 + 真实 LLM），非本地模拟
**结论**：12 题实测发现 2 个错误答案 + 1 个体验瑕疵，追溯出 **6 类系统性根因**，全部修复；测试数从 191 增至 **267 全绿**

---

## 目录

1. [执行摘要](#1-执行摘要)
2. [测试方法与完整结果](#2-测试方法与完整结果)
3. [根因分析](#3-根因分析)
4. [修复详情](#4-修复详情)
5. [验证证据](#5-验证证据)
6. [回归防护体系](#6-回归防护体系)
7. [变更文件清单](#7-变更文件清单)
8. [部署步骤](#8-部署步骤)
9. [遗留事项与建议](#9-遗留事项与建议)

---

## 1. 执行摘要

### 1.1 表面现象

用户反馈 chatbot「很难用，准确率也很低」。线上 12 题实测复现：2 题答"我不知道"，而这两题的答案**明确写在知识库文件里**。

### 1.2 关键发现

表面看是 2 个孤立的"答不出"问题，深挖后发现是 6 类互不相同的系统性缺陷。其中最严重的一条：

> **五道检索质量补救机制自上线以来从未执行过一次。**

代码里写好了「问答被切开时自动配对」「低置信度兜底」「后端快照兜底」「中文翻译重检索」等补救逻辑，但它们的触发条件全部失效——因为判断信号被首页实时状态数据污染了。这解释了为什么整体准确率长期偏低：本该自动修复的检索问题，修复代码是死的。

### 1.3 修复概览

| # | 根因 | 层级 | 影响面 |
|---|------|------|--------|
| A | 检索补救机制全部失效 | 检索层 | **全局**，影响所有知识类问题 |
| B | 切分把问题和答案切成两块 | 数据层 | 全部 Q&A 型知识条目 |
| C | 使用方法问题被路由到数据库 | 路由层 | 所有含实体名词的 how-to 问题 |
| D | 关键词匹配无词边界 | 路由层 | **全局**，任意无关问题可能被误判 |
| E | 判断关键词表大量单语（仅英文） | 路由层 | 全部中文问句 |
| F | 规则问句与计数查询混淆 | 路由层 | 上报规则类问题 |
| G | 数据库回答暴露内部账号名 | 展示层 | 体验瑕疵 |

### 1.4 量化结果

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| 路由准确率（64 题中英文审计） | 57/64（89%，7 处错误） | **64/64（100%）** |
| 知识库中被切开的问答对 | 存在（website_guide.md 至少 2 处） | **0（全库 32 块）** |
| 生效的检索补救机制 | 0 / 5 | **5 / 5** |
| 自动化测试总数 | 191 | **267（+76）** |
| 自测题库规模 | 14 题 | **21 题** |

---

## 2. 测试方法与完整结果

### 2.1 测试通道

由于安全策略不允许 AI 使用账号密码登录，采用合规方案：用户在自己的 Chrome 中登录网站，通过浏览器扩展驱动**已登录会话**调用生产接口，凭据全程不经过 AI。

```javascript
// 取 CSRF token 后逐题调用生产 /api/chat，记录耗时与来源
const r = await fetch('/api/chat', {
  method: 'POST',
  headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
  credentials: 'same-origin',
  body: JSON.stringify({message})
});
```

### 2.2 完整测试结果（12 题）

| # | 问题 | 结果 | 耗时 | 引用来源 |
|---|------|------|------|----------|
| 1 | 现在适合去游泳吗？ | ✅ 正确判为关闭（非营业时间），并给出离水建议 | 7.6s | homepage/live-status |
| 2 | 工作日泳池几点开放？ | ✅ 7:00–21:30 | 1.7s | operating_hours_and_holidays.md |
| 3 | 需要多少条上报才能覆盖天气状态？ | ❌ **"我不知道"** | 1.7s | 仅 live-status |
| 4 | 怎么注册账号？NTU 邮箱收不到验证码？ | ✅ 完整答出原因与建议 | 2.2s | website_guide.md |
| 5 | 列出最新的社区帖子 | ✅ 返回真实帖子 | 6.4s | community/post |
| 6 | What are the pool opening hours on weekends and public holidays? | ✅ 8:00–20:00 | 4.7s | operating_hours_and_holidays.md |
| 7 | How long is the lightning cooldown before reopening? | ✅ 45 分钟，含重置规则 | 2.4s | faq.md |
| 8 | How do I search for posts in the community? | ❌ **"cannot find any information"** | 1.8s | 无 |
| 9 | Show me the latest manual pool reports | ⚠️ 数据正确，但暴露 `bot_xavier_tempo` 等内部账号名 | 7.6s | pool-report |
| 10 | 闪电在多少公里内泳池会关闭？ | ✅ 15 公里 | 1.8s | homepage/live-status |
| 11 | 你能做什么？ | ✅ 中文能力介绍 | 0.5s | 静态 |
| 12 | 帮我写一个 Python 爬虫程序 | ✅ 正确拒答并引导 | 8.1s | 静态 |

**附带验证**：连续快速提问触发了 HTTP 429 限流（8 条/分钟），证明限流功能正常工作。

### 2.3 语言与性能观察

- 中文问中文答、英文问英文答，语言路由 12/12 正确
- 静态/缓存路径 0.4–2.4 秒；完整 RAG + LLM 路径 4–8 秒
- 相比重构前的「翻译→意图→生成→翻译」四段式链路有明显改善

---

## 3. 根因分析

### 3.1 一次被推翻的错误判断（过程记录）

初次分析时，我判断根因是「新知识库文件从未同步进向量库」。**这个判断被测试数据本身否定**：第 2 题引用了 `kb://operating_hours_and_holidays.md`、第 4 题引用了 `kb://website_guide.md`，两者都是新增文件——同步是成功的。

推翻后重新用实验定位，才找到真正的根因。此处记录，是因为「只修表象」与「找到真因」的差别，正体现在这一步。

---

### 3.2 根因 A：五道检索补救机制全部失效 🔴 最严重

**病灶代码**（`app/services/chatbot/graph.py` · `retrieve_node`）：

```python
context: list[str] = list(page_context)   # ← 首页实时状态先塞进来（6–12 条）

# ... 检索知识块，append 到同一个 context ...

if context and len(context) < min(2, top_k):     # 问答配对补救
if not context and matched:                      # 低置信度兜底
if not context and backend_priority_docs:        # 后端快照兜底
if input_language != "en" and not context:       # 中文翻译重检索
```

**失效机制**：`_build_homepage_context()` 在生产环境**永远**返回 6–12 条首页状态数据，因此 `context` 一进入判断就已非空且长度 ≥ 6。上述所有条件恒为假。

**后果**：这五道机制**从代码上线至今一次都没有运行过**。它们本是检索失败时的安全网，而安全网是虚设的。这是"chatbot 准确率低"的最主要系统性原因。

**本质**：一个变量混淆了两种语义完全不同的数据——「实时页面上下文」（永远存在，与检索质量无关）和「检索到的知识块」（真正的质量信号）。

---

### 3.3 根因 B：切分把问题和答案切成两块

**实验复现**（用生产同参数 chunk_size=500 重跑切分）：

```
chunk 5 结尾: "### Q: How many reports are needed to override weather status?"
chunk 6 开头: "**A:** The community consensus rule needs the latest 5 reports..."

chunk 7 结尾: "### Q: How do I search for posts in the community?"
chunk 8 开头: "**A:** Use the search box at the top of the Community page..."
```

**两道失败题的问题句，恰好都落在某个 chunk 的末尾，答案在下一个 chunk。**

**失效机制**：用户提问 → 向量检索精准命中"含有这个问题"的 chunk（相似度极高，因为文字几乎一致）→ 但该 chunk 里**只有问题没有答案** → 模型看到一段"提出了问题却没回答"的文本 → 如实回答"找不到相关信息"。

**关键判断：模型行为完全正确。** 它严格遵守了"检索不到就说不知道、不要编造"的指令。问题出在喂给它的资料被切坏了。这也说明系统的抗幻觉设计是有效的——宁可说不知道，也不瞎编。

**隐藏陷阱**：`doc_hash` 是按**切分前的整份文件内容**计算的。因此仅修改切分逻辑不会改变哈希，增量同步会认为"文件没变"而跳过，**坏 chunk 将永久留在向量库中**。

---

### 3.4 根因 C：使用方法问题被路由到数据库

`_looks_like_database_question()` 的逻辑是：只要问句中出现 `post`/`posts`/`comment`/`上报`/`社区` 等实体名词，就判定为数据库查询。

于是 "How do I search for posts in the community?" 因为含 `posts` 被送去查**真实帖子记录**——用数据库里的帖子内容，当然回答不了"怎么使用搜索功能"这个使用方法问题。

**本质**：混淆了「关于某实体的文档」与「查询某实体的记录」。提到 posts 不等于要查 posts。

---

### 3.5 根因 D：关键词匹配无词边界 🔴 全局隐患

所有关键词判断都是裸子串匹配：

```python
any(token in lowered for token in KNOWLEDGE_BASE_HINTS)
```

**实测触发**：`What is the capital of France?` 被判为**站内知识问题**——因为知识库关键词表里有 `api`，而它匹配了 c-**api**-tal 中间的三个字母。

同类隐患：`dev` 命中 development/device、`help` 命中 helpful、`open` 命中 opening/opened、`red` 命中 required/predicted……**任意无关问题都可能被误判为站内知识**，进而给出牵强附会的答案而非正确拒答。

---

### 3.6 根因 E：判断关键词表大量单语（仅英文）

审计发现多个决策用关键词表**只有英文条目**：

| 关键词表 | 问题 |
|---|---|
| `POLICY_QUESTION_HINTS` | 全英文 → `谁可以上报泳池状态？` 拿不到策略问句护栏，被误判为数据库查询 |
| `DATABASE_LOOKUP_HINTS` | 全英文 → `今天有多少条上报？` 中的"今天"未被识别为时间范围 |
| `KNOWLEDGE_BASE_HINTS` | 有 `status` 无「状态」、有 `community` 相关但中英不对称 |
| `DATABASE_HINTS` | 有「上报」无英文 `report`/`reports` |

**后果**：中文用户和英文用户走在两套宽严不同的判断路径上，中文问句系统性地更容易被误判。

---

### 3.7 根因 F：规则问句与计数查询混淆

两类问句在词面上高度相似，语义完全不同：

- `需要多少条上报才能覆盖天气状态？` → 问**规则要求**（应查知识库）
- `今天有多少条上报？` → 问**实际记录数**（应查数据库）

原逻辑仅凭"上报 + 多少条"就判为规则问句，导致后者被错误送往知识库。

---

### 3.8 根因 G：数据库回答暴露内部账号名

`_db_get_recent_pool_reports` 等工具直接读取 `user.username`，于是回答里出现：

```
Report ID 237: Status Open, User bot_xavier_tempo, Created at 2026-07-26T11:07
```

既暴露了机器人账号的内部命名，也不美观（应显示昵称 "Xavier Yeo"）。

---

## 4. 修复详情

### 4.1 修复 A：检索上下文分离

```python
# 修复后：检索到的知识块单独存放，所有质量判断只看它
kb_context: list[str] = []
sources: list[str] = ["app://homepage/live-status"] if page_context else []
min_kb_chunks = min(2, max(1, top_k))

# ... 所有补救判断改为基于 kb_context ...
if kb_context and len(kb_context) < min_kb_chunks:   # 问答配对补救 ✓ 复活
if not kb_context and matched:                       # 低置信度兜底 ✓ 复活
if not kb_context and backend_priority_docs:         # 后端快照兜底 ✓ 复活

# 最终提示词 = 实时上下文 + 知识块
context = list(page_context) + kb_context
```

同时新增返回字段 `kb_chunks`（实际检索到的知识块数量），用于自测诊断。

**顺带的性能护栏**：中文翻译重检索对「实时决策类问题」跳过——这类问题的答案本来就来自首页上下文，多花一次翻译调用是浪费。注意这个护栏是**按问题类型**判断，而非"页面上下文是否存在"（后者正是根因 A 的错误做法）。

### 4.2 修复 B：Q&A 感知切分 + 运行时兜底

**双保险设计**：

**① 切分层**（`sync_knowledge_base.py`）：

```python
DEFAULT_CHUNK_SIZE = 1200      # 500 → 1200，一个 Q&A 条目完整放得下
DEFAULT_CHUNK_OVERLAP = 150
CHUNK_SEPARATORS = [           # 优先在 Q&A / 章节边界切分
    "\n---\n", "\n## ", "\n### ", "\n#### ", "\n\n", "\n", " ", "",
]
CHUNK_STRATEGY_VERSION = "qa-aware-v2"   # 参与 doc_hash，破解重建陷阱
```

`chunk_strategy` 被写入文档元数据并参与哈希计算，因此**切分策略变更会自动触发增量同步重建索引**，无需 `--full-rebuild`。

**② 运行时层**（`graph.py`）：新增 `_select_answer_completion_docs()`——当选中的知识块以问句结尾且不含答案时，自动从候选中拉取以答案标记（`**A:**` / `答：`）开头的同源块。这道防线不依赖切分配置，即使将来切分参数被改动也能兜住。

### 4.3 修复 C：使用方法问题识别

```python
def _looks_like_site_usage_question(question: str) -> bool:
    """how-to 句式 + 站内功能名词 = 文档类问题，不是记录查询。"""
    if not _looks_like_howto_question(question):
        return False
    return _contains_hint(question.lower(), SITE_USAGE_DOMAIN_HINTS)
```

- how-to 句式：`how do/can/could/would/should I`、`how to`、`where do/can I`、`is there a way to`，中文「怎么/如何/怎样/在哪里/哪里可以」
- 仅**强查询信号**（时间窗、列举动词）才否决 how-to 判定——弱动词如 `search`/`find`/`show` 本身就是 how-to 的常见措辞，用它们否决会把问题推回错误路径
- 判定顺序置于数据库判定之前

### 4.4 修复 D：词边界匹配

```python
@lru_cache(maxsize=4096)
def _hint_pattern(hint: str):
    escaped = re.escape(hint)
    prefix = r"\b" if hint[:1].isalnum() else ""
    if hint[-1:].isalpha():
        suffix = r"(?:s|es)?\b"    # 兼容复数：report → reports
    elif hint[-1:].isalnum():
        suffix = r"\b"
    else:
        suffix = ""
    return re.compile(prefix + escaped + suffix)

def _contains_hint(text: str, hints) -> bool:
    """英文按词边界匹配，中文保持子串语义（中文无词边界）。"""
```

全文件 **20 处**关键词判断统一改用此函数。

> **过程记录**：加上词边界后出现回归——`report` 不再匹配复数 `reports`，导致一道原本正确的题失败。因此补充了可选复数后缀 `(?:s|es)?`，既保住复数匹配，又不会让 `api` 命中 `capital`。

### 4.5 修复 E：关键词表双语对齐

| 关键词表 | 修复前 | 修复后 |
|---|---|---|
| `KNOWLEDGE_BASE_HINTS` | 缺中文「状态/泳道/储物柜/会员/游客/注册/登录/验证/账号/假期」等，英文缺 `community/account/profile/guest/amber/lane/locker` | **80 条**，中英对齐 |
| `DATABASE_HINTS` | 缺英文 `report`/`reports`/`feed` | **20 条** |
| `DATABASE_LOOKUP_HINTS` | 全英文 | 增加「最新/最近/今天/昨天/本周/本月/列出/显示/有哪些」 |
| `POLICY_QUESTION_HINTS` | 全英文 | **39 条**，增加「谁可以/谁能/允许/可不可以/能不能/必须/要求/条件/权限/可以」等 |
| `POLICY_DOMAIN_HINTS` | 全英文 | 增加「泳池/游泳/天气/闪电/上报/帖子/评论/社区」 |

另外把 `community` 从数据库关键词中移除——它是版块名而非记录类型，查询记录会说 "community posts"，仍能通过 `post` 命中。

### 4.6 修复 F：规则 vs 计数

新增 `RECORD_SCOPE_HINTS`（**只含时间窗与列举动词，刻意不含计数词**）：

```python
RECORD_SCOPE_HINTS = (
    "latest", "newest", "recent", "today", "yesterday", "this week",
    "this month", "list ", "show me",
    "最新", "最近", "今天", "昨天", "本周", "这周", "本月", "列出", "有哪些",
)
```

规则问句判定改为：命中规则信号**且不含记录范围信号**才算规则问句。

- `需要多少条上报才能覆盖天气状态？` → 无记录范围 → 规则问句 → 知识库 ✓
- `今天有多少条上报？` → 含「今天」→ 记录查询 → 数据库 ✓

「多少条 / how many」被刻意排除在外，因为它在两类问句中都会出现，用它区分会误伤规则问句。

同一护栏也应用于策略问句判定，避免「可以给我看最新的帖子吗？」这类礼貌措辞被误判为策略问题。

### 4.7 修复 G：显示昵称

```python
def _display_name(user) -> str:
    """对外一律用昵称，内部用户名（bot_*）永不直接暴露。"""
    nickname = str(getattr(user, "nickname", "") or "").strip()
    if nickname:
        return nickname
    username = str(getattr(user, "username", "") or "").strip()
    if username.startswith("bot_"):
        return username[4:].replace("_", " ").title()
    return username or "Unknown"
```

应用于全部 3 处数据库工具（帖子作者 ×2、上报用户 ×1）。

### 4.8 知识库内容补全

审计发现「头像/昵称」相关问题在知识库中**完全无覆盖**。新增 5 组中英双语问答：

- 怎么修改昵称 / 上传头像
- 怎么删除自己的帖子或评论（含软删除说明）
- 在哪里查看收藏的帖子
- 怎么按分类筛选帖子
- 游客不登录能做什么

---

## 5. 验证证据

### 5.1 切分修复验证

修复前后用生产同参数重跑全知识库切分：

```
README.md                                 1 块, 被切开的问答: NONE
backend_architecture_logic_overview.md    8 块, 被切开的问答: NONE
faq.md                                   13 块, 被切开的问答: NONE
operating_hours_and_holidays.md           3 块, 被切开的问答: NONE
website_guide.md                          7 块, 被切开的问答: NONE

全库被切开的问答对总数: 0
```

两道失败题的定点复查：

```
[OK] 'How many reports are needed to override weather status?' → chunk 2，答案同块: True
[OK] 'How do I search for posts in the community?'             → chunk 2，答案同块: True
```

### 5.2 路由修复验证（64 题主动审计）

不止修复发现的 2 个问题，而是构造 64 题中英文矩阵扫描同类隐患：

| 轮次 | 错误数 | 新发现的问题 |
|------|--------|-------------|
| 第 1 轮 | 7 | 中文策略问句、中英不对称、`api`↔`capital`、规则/计数混淆、英文 `report` 缺失、后续追问未识别 |
| 第 2 轮 | 2 | `community` 误入数据库关键词、查询意图表缺中文 |
| 第 3 轮 | 1 | 词边界导致复数失配 |
| **最终** | **0** | **64/64 全对** |

覆盖类别：使用方法（17）、策略权限（6）、规则与开放时间（10）、实时决策（4）、数据库查询（13）、闲聊（5）、能力介绍（3）、超范围拒答（6）。

### 5.3 检索补救机制验证

新增专项测试，**每道补救机制都在"页面上下文存在"的前提下**验证其仍然生效（这正是原先失效的场景）：

- 问答被切开 → 自动拉取答案块 ✓
- 全部低于阈值 → 低置信度兜底生效 ✓
- 向量检索为空 → 后端快照兜底生效 ✓
- 中文知识问题 → 翻译重检索生效（两次检索，命中英文块）✓
- 中文实时问题 → 跳过翻译（性能护栏）✓
- 页面上下文与知识块**同时**进入最终提示词 ✓

### 5.4 全量回归

```
267 passed in 18.49s
```

---

## 6. 回归防护体系

### 6.1 新增测试

| 文件 | 行数 | 作用 |
|---|---|---|
| `tests/test_chatbot_routing_matrix.py` | 188 | 64 题中英文路由矩阵 + 关键词匹配语义（含"任一关键词表不得单语"的断言） |
| `tests/test_chatbot_retrieval_recovery.py` | 291 | 每道检索补救机制必须在页面上下文存在时依然生效 |
| `tests/test_chatbot_selftest.py` | 143 | 自测系统的端点、累积、公开报告 |

其中「双语对齐」测试尤其关键——它会在任何一张决策表退化为单语时直接失败，从机制上防止根因 E 重现。

### 6.2 线上自测系统

新增一套可一键运行的生产环境回归工具：

- **触发**：GitHub Actions → `Chatbot Selftest` → Run workflow（一次点击）
- **执行**：21 道精选题（中英文，覆盖全部 5 种路由）逐题走**真实生产链路**，每题一个独立请求（避免 serverless 超时）
- **诊断记录**：解析出的意图 vs 预期路由、检索块数、来源、翻译后的检索词、答案与答案语言、耗时、错误
- **报告**：公开只读端点 `/api/chatbot-selftest/latest`（仅含测试题内容，无用户数据）
- **自适应**：题库规模由应用侧提供，工作流不会因增题而失配

题库已覆盖本次全部新发现的失败类型（使用方法、规则 vs 计数、超范围拒答、双语等）。

---

## 7. 变更文件清单

### 核心修复

| 文件 | 变更 |
|---|---|
| `app/services/chatbot/graph.py` | 检索上下文分离、答案补全机制、词边界匹配、使用方法路由、双语关键词、规则/计数区分、昵称显示 |
| `sync_knowledge_base.py` | Q&A 感知切分（1200/150 + 边界分隔符）、切分策略版本参与哈希 |
| `knowledge_base/website_guide.md` | 新增 5 组双语问答，补全覆盖缺口 |

### 自测系统

| 文件 | 说明 |
|---|---|
| `app/models/selftest.py` | 自测结果表（新增） |
| `app/services/chatbot/selftest.py` | 21 题题库与执行/报告逻辑（新增） |
| `app/blueprints/cron.py` | 鉴权自测端点 |
| `app/blueprints/misc.py` | 公开只读报告端点 |
| `app/__init__.py` | 自测表自动建表 |
| `_workflow_updates/chatbot-selftest.yml` | 一键回归工作流（新增） |

### 测试与文档

| 文件 | 说明 |
|---|---|
| `tests/test_chatbot_routing_matrix.py` | 新增 |
| `tests/test_chatbot_retrieval_recovery.py` | 新增 |
| `tests/test_chatbot_selftest.py` | 新增 |
| `tests/test_chatbot_graph.py` | 更新 1 处断言（反映实时问题不再花费翻译调用） |
| `product_docs/product_chatbot.md` | 新增第 13 节：本次根因与修复 |
| `push_fix.bat` | 增加知识库重新同步步骤 |

---

## 8. 部署步骤

### 8.1 操作

1. 双击 `push_fix.bat`
   - 自动安装 `_workflow_updates/` 中的工作流文件
   - 运行完整测试（失败即中止，不会推送）
   - 提交并推送
   - **重新同步知识库**（切分策略已变更，必须重建向量索引）
2. 打开脚本打印的 PR 链接 → Create pull request → Merge
3. 部署完成后（约 2 分钟），Actions → `Chatbot Selftest` → Run workflow

### 8.2 关键提醒

> ⚠️ **知识库重新同步是本次修复生效的必要条件。**
> 切分策略从 500 改为 1200 后，向量库中仍是旧的、被切坏的 chunk。`CHUNK_STRATEGY_VERSION` 参与哈希后，增量同步会自动识别并重建，但**同步这一步必须成功执行**。若 `dev.bat sync` 报错，修复 B 不会生效。

### 8.3 验收标准

部署且同步完成后，以下两题应给出正确答案（对照本报告 2.2 节的失败记录）：

- `需要多少条上报才能覆盖天气状态？` → 应答"30 分钟内 5 位不同真人用户的最近 5 条上报完全一致，且最新一条在 10 分钟内"
- `How do I search for posts in the community?` → 应答"社区页顶部搜索框，支持标题与正文关键词，可与分类标签组合"

或直接运行 Chatbot Selftest 工作流，查看 `/api/chatbot-selftest/latest` 报告中的 `route_mismatches` 是否为空。

---

## 9. 遗留事项与建议

### 9.1 需要用户处理

| 事项 | 优先级 | 说明 |
|---|---|---|
| **修改管理员密码** | 🔴 高 | 密码曾在对话中传输，按泄露处理 |
| 清理重复的 Vercel 项目 | 中 | 同一仓库连了 3 个项目，每次部署三倍排队时间；保留绑定 ntupool.org 域名的那个 |

### 9.2 后续可优化方向

**监控**：目前失败会写入 Supabase 的 `chatbot_intent_model_failures` / `chatbot_qa_model_failures` 两张表，但没有告警。可考虑定期跑自测工作流并在 `route_mismatches` 非空时通知。

**检索评测**：当前自测验证的是"路由是否正确 + 是否答出来"，尚未量化"答案是否准确"。若要进一步提升，可为每题标注期望关键事实，自动校验答案是否包含。

**知识库覆盖**：本次补齐了头像/昵称、删帖、收藏、分类筛选、游客权限。建议每次新增功能时同步补充知识库条目——现在有了自测题库，加一道题即可持续验证。

**意图模型**：外部意图模型（`liquid/lfm-2.5-1.2b-thinking:free`）现在只处理少数模糊问题，且有 10 秒超时兜底。若追求更稳，可换成非免费档的小模型。

---

## 附录：核心代码位置

| 修复 | 文件 | 关键符号 |
|---|---|---|
| A 检索上下文分离 | `graph.py` | `retrieve_node` 中的 `kb_context` |
| B 答案补全 | `graph.py` | `_select_answer_completion_docs` / `_chunk_ends_on_question` |
| B 切分策略 | `sync_knowledge_base.py` | `CHUNK_SEPARATORS` / `CHUNK_STRATEGY_VERSION` |
| C 使用方法路由 | `graph.py` | `_looks_like_site_usage_question` / `_looks_like_howto_question` |
| D 词边界匹配 | `graph.py` | `_contains_hint` / `_hint_pattern` |
| E 双语对齐 | `graph.py` | 各 `*_HINTS` 常量 |
| F 规则/计数 | `graph.py` | `RECORD_SCOPE_HINTS` / `_looks_like_report_rule_question` |
| G 昵称显示 | `graph.py` | `_display_name` |

---

*报告生成时间：2026-07-26 · 测试环境：ntupool.org 生产环境 · 测试数：267 全绿*
