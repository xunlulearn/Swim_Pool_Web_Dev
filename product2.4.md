# 2.4 Social Network

* **Community Feed**: Reverse chronological order. Support for text and images.

# 游泳馆网站社交功能需求规范 (Social Features Specification)

## 1. 项目概述
本模块旨在为游泳馆网站构建一套完整的社交社区系统。系统需支持用户交流（发帖、评论、私信）、互动（点赞、收藏）以及管理员的内容监管。

## 2. 用户角色定义 (User Roles)

系统需在 `User` 模型中通过字段区分以下三种角色：

1.  **游客 (Guest):** 未登录用户。
2.  **普通用户 (User):** 已注册并登录的标准用户。
3.  **管理员 (Admin):** 拥有系统维护和监管权限的高级账户。

## 3. 权限矩阵 (Permission Matrix)

| 功能模块 | 动作 (Action) | 游客 (Guest) | 普通用户 (User) | 管理员 (Admin) | 备注 |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **浏览** | 查看帖子列表/详情 | ✅ | ✅ | ✅ | |
| **内容创作** | 发布帖子 | ❌ | ✅ | ✅ | |
| | 发布评论 | ❌ | ✅ | ✅ | |
| | **回复评论 (楼中楼)** | ❌ | ✅ | ✅ | |
| **编辑/删除** | 编辑帖子/评论 | ❌ | ✅ (本人) | ✅ (任意) | |
| | 删除帖子/评论 | ❌ | ✅ (本人) | ✅ (任意) | **软删除** |
| **互动** | 点赞/收藏 | ❌ | ✅ | ✅ | 防重复 |
| **私信** | 查看会话列表 | ❌ | ✅ | ✅ | |
| | 发送私信 | ❌ | ✅ | ✅ | |
| | 查看聊天记录 | ❌ | ✅ (本人会话) | ✅ (本人会话) | |
| **管理** | 置顶帖子 | ❌ | ❌ | ✅ | |
| | 举报内容 | ❌ | ✅ | ✅ | |
| | 封禁用户 | ❌ | ❌ | ✅ | |

---

## 4. 数据库模型 (Schema)

### A. 用户表 (User)

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer, PK | |
| `email` | String(120), unique | |
| `username` | String(64), unique | |
| `password_hash` | String(255) | |
| `is_verified` | Boolean | 邮箱验证状态 |
| `role` | String(20) | `'user'` \| `'admin'` |
| `is_banned` | Boolean | 封禁状态 |
| `nickname` | String(64) | 用户昵称 |
| `avatar` | LargeBinary | BLOB 存储头像 |
| `avatar_mimetype` | String(32) | 如 `image/jpeg` |
| `otp_code` | String(6) | OTP 验证码 |
| `otp_expiry` | DateTime | OTP 过期时间 |

**关系**: `posts`, `comments`, `likes`, `collections`, `content_reports`

---

### B. 帖子表 (Post)

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer, PK | |
| `title` | String(200) | |
| `body` | Text | |
| `image_url` | String(255) | 可选图片 |
| `category` | String(20) | `general`/`squad`/`lostfound`/`tutorial` |
| `is_pinned` | Boolean | 置顶标记 |
| `is_deleted` | Boolean | 软删除标记 |
| `view_count` | Integer | 浏览量 |
| `author_id` | FK → User | |
| `created_at` / `updated_at` | DateTime | |

**关系**: `comments`, `likes`, `collections`

---

### C. 评论表 (Comment)

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer, PK | |
| `body` | Text | |
| `is_deleted` | Boolean | 软删除标记 |
| `author_id` | FK → User | |
| `post_id` | FK → Post | |
| `parent_id` | FK → Comment (可空) | **楼中楼**: 顶级评论为 NULL |
| `reply_to_user_id` | FK → User (可空) | **楼中楼**: 被回复用户 ID |
| `created_at` / `updated_at` | DateTime | |

---

### D. 互动表

**Like 表** (帖子点赞):
| 字段 | 类型 |
|------|------|
| `id` | Integer, PK |
| `user_id` | FK → User |
| `post_id` | FK → Post |
| `created_at` | DateTime |
| **UNIQUE** | (`user_id`, `post_id`) |

**CommentLike 表** (评论点赞):
| 字段 | 类型 |
|------|------|
| `id` | Integer, PK |
| `user_id` | FK → User |
| `comment_id` | FK → Comment |
| `created_at` | DateTime |
| **UNIQUE** | (`user_id`, `comment_id`) |

**Collection 表**: 同 Like 表结构

---

### E. 举报表 (ContentReport)

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer, PK | |
| `reporter_id` | FK → User | |
| `target_type` | String(20) | `'post'` \| `'comment'` |
| `target_id` | Integer | |
| `reason` | String(100) | 广告/辱骂/无关等 |
| `status` | String(20) | `pending`/`resolved`/`rejected` |
| `created_at` | DateTime | |

---

### F. 私信表 (PrivateMessage)

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer, PK | |
| `sender_id` | FK → User | 发送者 |
| `receiver_id` | FK → User | 接收者 |
| `body` | Text | 消息内容 |
| `is_read` | Boolean | 已读标记 |
| `created_at` | DateTime | |

---

## 5. 业务逻辑

### 5.1 软删除
- **严禁** SQL `DELETE`，必须设置 `is_deleted = True`
- 所有查询默认过滤 `is_deleted=True` 的记录

### 5.2 个人中心
- 查看我的帖子、收藏列表
- **查看私信会话列表** (点击进入与某用户的聊天详情)
- 修改昵称和头像
- 发起密码修改 (需 OTP 验证)

### 5.3 管理员特权
- 操作按钮: 置顶、删除任意帖子、封禁作者
- Dashboard 查看举报列表

### 5.4 分类
预设: `General` (一般) / `Squad` (约游) / `LostFound` (失物) / `Tutorial` (教学)

### 5.5 楼中楼回复 (Nested Comments)

**层级限制**: 最多 2 层
- **顶级评论**: `parent_id = NULL`
- **子评论**: `parent_id = 顶级评论ID`
- 回复子评论时，`parent_id` 仍指向顶级评论，通过 `reply_to_user_id` 记录被回复用户

**查询逻辑**:
1. 查询所有顶级评论 (`parent_id IS NULL`)
2. 对每条顶级评论查询子评论，按时间正序

**删除逻辑**: 顶级评论删除后显示「该评论已删除」，子评论仍可见

**前端展示**:
- 子评论缩进显示在父评论下方
- 回复按钮 + 回复表单
- 格式: `[用户A] replied to @[用户B]: 内容`

### 5.6 私聊功能 (Direct Message)

**入口**:
- 帖子作者头像 → 点击进入聊天页
- 评论区头像 → 点击进入聊天页
- 个人中心 → 「Messages」Tab

**逻辑**:
- 两用户间唯一会话 (动态生成)
- 被封禁用户无法发送私信
- 打开会话时自动标记所有消息已读
- 导航栏 Profile 及个人中心 Messages Tab 显示未读消息红色徽章

**前端**:
- 会话列表: 对方头像、昵称、最后消息摘要、时间、未读数
- 聊天详情: 自己消息靠右 (蓝色)，对方靠左 (白色)
- 返回按钮使用浏览器历史返回

---

## 6. API 路由

### 现有路由

| 路由 | 方法 | 权限 | 描述 |
|-----|------|------|------|
| `/social/` | GET | All | 社区首页 |
| `/social/post/<id>` | GET | All | 帖子详情 |
| `/social/post` | POST | User/Admin | 发布帖子 |
| `/social/post/<id>` | PUT | Owner/Admin | 编辑帖子 |
| `/social/post/<id>` | DELETE | Owner/Admin | 软删除帖子 |
| `/social/post/<id>/comment` | POST | User/Admin | 发布评论 |
| `/social/comment/<id>` | DELETE | Owner/Admin | 软删除评论 |
| `/social/post/<id>/like` | POST | User/Admin | 点赞/取消 |
| `/social/post/<id>/collect` | POST | User/Admin | 收藏/取消 |
| `/social/post/<id>/report` | POST | User/Admin | 举报帖子 |
| `/social/post/<id>/pin` | POST | Admin | 置顶帖子 |
| `/social/user/<id>/ban` | POST | Admin | 封禁用户 |
| `/social/profile` | GET | User/Admin | 个人中心 |
| `/social/admin/reports` | GET | Admin | 举报管理 |

### 新增路由

| 路由 | 方法 | 权限 | 描述 |
|-----|------|------|------|
| `/social/comment/<id>/reply` | POST | User/Admin | 回复评论 (楼中楼) |
| `/social/comment/<id>/like` | POST | User/Admin | 评论点赞/取消 |
| `/social/comment/<id>/report` | POST | User/Admin | 举报评论 |
| `/social/messages/` | GET | User/Admin | 会话列表 |
| `/social/messages/<user_id>` | GET/POST | User/Admin | 查看/发送私信 |
| `/social/messages/unread_count` | GET | User/Admin | 未读消息数 (AJAX) |

---

## 7. API 响应标准

- **401 Unauthorized**: 游客尝试需登录操作
- **403 Forbidden**: 权限不足
- **200 OK**: 操作成功，返回更新后数据
