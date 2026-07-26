# 2.4 Social Network

* **Community Feed**: Reverse chronological order (pinned first), supports text and optional images.

# 游泳馆网站社交功能需求规范 (Social Features Specification)

## 1. 项目概述
本模块为泳池网站提供社交社区能力：发帖、评论、楼中楼回复、点赞、收藏、举报、私信，以及管理员审核与管控。

## 2. 用户角色定义 (User Roles)

系统在 `User` 模型中区分三类角色：

1. **游客 (Guest)**: 未登录用户。
2. **普通用户 (User)**: 已注册并登录的用户。
3. **管理员 (Admin)**: 拥有置顶、封禁、举报审核等权限。

## 3. 权限矩阵 (Permission Matrix)

| 功能模块 | 动作 (Action) | 游客 (Guest) | 普通用户 (User) | 管理员 (Admin) | 备注 |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **浏览** | 查看帖子列表/详情 | ✅ | ✅ | ✅ | |
| **内容创作** | 发布帖子 | ❌ | ✅ (已验证) | ✅ | |
| | 发布评论 | ❌ | ✅ (已验证) | ✅ | |
| | 回复评论 (楼中楼) | ❌ | ✅ (已验证) | ✅ | |
| **编辑** | 编辑帖子 | ❌ | ✅ (本人) | ✅ (任意) | |
| **删除** | 删除帖子/评论 | ❌ | ✅ (本人) | ✅ (任意) | 软删除 |
| **互动** | 点赞/收藏 | ❌ | ✅ (已验证) | ✅ | 防重复 |
| **私信** | 查看会话列表 | ❌ | ✅ (已验证) | ✅ | |
| | 发送私信 | ❌ | ✅ (已验证，未封禁) | ✅ | |
| | 查看聊天记录 | ❌ | ✅ (本人会话) | ✅ (本人会话) | |
| **管理** | 置顶帖子 | ❌ | ❌ | ✅ | |
| | 举报内容 | ❌ | ✅ (已验证) | ✅ | |
| | 封禁用户 | ❌ | ❌ | ✅ | 不可封禁管理员 |

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
| `image` | LargeBinary, nullable | 上传图片二进制 |
| `image_mimetype` | String(32), nullable | 如 `image/jpeg` |
| `image_url` | String(255), nullable | 兼容历史 URL 字段 |
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
| `body` | Text | 评论正文 |
| `image` | LargeBinary, nullable | 评论图片 |
| `image_mimetype` | String(32), nullable | 如 `image/png` |
| `is_deleted` | Boolean | 软删除标记 |
| `author_id` | FK → User | |
| `post_id` | FK → Post | |
| `parent_id` | FK → Comment (可空) | 顶级评论为 NULL |
| `reply_to_user_id` | FK → User (可空) | 被回复用户 ID |
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

**Collection 表**: 同 Like 表结构，UNIQUE(`user_id`, `post_id`)。

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
- 严禁物理删除业务内容；帖子/评论使用 `is_deleted = True`。
- 默认列表查询过滤软删除内容。

### 5.2 个人中心
- 查看我的帖子、收藏列表。
- 查看私信会话列表。
- 修改昵称和头像。
- 发起密码修改（需 OTP 验证）。

### 5.3 管理员特权
- 操作按钮：置顶、删除任意帖子、封禁作者。
- Dashboard 查看举报并可标记 resolved/rejected。

### 5.4 分类
预设分类：`General` / `Squad` / `LostFound` / `Tutorial`。

### 5.5 楼中楼回复 (Nested Comments)

**层级限制**：最多 2 层
- 顶级评论：`parent_id = NULL`
- 子评论：`parent_id = 顶级评论ID`
- 回复子评论时，`parent_id` 仍指向顶级评论，通过 `reply_to_user_id` 标记被回复用户。

**查询逻辑**：
1. 先取顶级评论。
2. 子评论按父级分组并按时间展示。

**删除展示逻辑（与代码一致）**：
- 顶级评论被删除后，如果仍有可见子评论，顶级评论位置显示占位文本：`This comment has been deleted.`
- 占位文本使用区别样式（斜体/特殊字体）以明确这是已删除内容。
- 子评论保留展示。

### 5.6 私聊功能 (Direct Message)

**入口**：
- 帖子作者头像 → 聊天页
- 评论作者头像 → 聊天页
- 个人中心 Messages Tab

**逻辑**：
- 两用户间消息按时间排序展示。
- 被封禁用户不可发送私信。
- 打开会话时自动标记对方发来的未读消息为已读。
- 导航栏 Profile 与个人中心展示未读消息数。

### 5.7 图片上传规则
- 帖子支持可选图片上传。
- 评论与回复支持可选图片上传。
- 允许类型：`image/jpeg`、`image/png`。
- 大小限制：遵循服务端 `MAX_CONTENT_LENGTH`（默认 2MB）。

---

## 6. 路由清单（按当前实现）

| 路由 | 方法 | 权限 | 描述 |
|-----|------|------|------|
| `/social/` | GET | All | 社区首页 |
| `/social/post/<post_id>` | GET | All | 帖子详情 |
| `/social/post` | GET/POST | Verified User/Admin | 创建帖子 |
| `/social/post/<post_id>/edit` | GET/POST | Owner/Admin | 编辑帖子 |
| `/social/post/<post_id>/delete` | POST | Owner/Admin | 软删除帖子 |
| `/social/post/<post_id>/comment` | POST | Verified User/Admin | 发表评论 |
| `/social/comment/<comment_id>/delete` | POST | Owner/Admin | 软删除评论 |
| `/social/comment/<comment_id>/reply` | POST | Verified User/Admin | 回复评论 |
| `/social/post/<post_id>/like` | POST | Verified User/Admin | 点赞/取消 |
| `/social/post/<post_id>/collect` | POST | Verified User/Admin | 收藏/取消 |
| `/social/comment/<comment_id>/like` | POST | Verified User/Admin | 评论点赞/取消 |
| `/social/post/<post_id>/report` | POST | Verified User/Admin | 举报帖子 |
| `/social/comment/<comment_id>/report` | POST | Verified User/Admin | 举报评论 |
| `/social/post/<post_id>/pin` | POST | Admin | 置顶/取消置顶 |
| `/social/user/<user_id>/ban` | POST | Admin | 封禁/解封用户 |
| `/social/profile` | GET | Login | 个人中心 |
| `/social/profile/edit` | GET/POST | Login | 编辑个人资料 |
| `/social/admin/reports` | GET | Admin | 举报列表 |
| `/social/admin/report/<report_id>/resolve` | POST | Admin | 标记举报 resolved |
| `/social/admin/report/<report_id>/reject` | POST | Admin | 标记举报 rejected |
| `/social/messages/` | GET | Verified User/Admin | 会话列表 |
| `/social/messages/<user_id>` | GET/POST | Verified User/Admin | 查看/发送私信 |
| `/social/messages/unread_count` | GET | Login | 未读消息数 |

---

## 7. 响应行为说明（按当前实现）

- **页面型路由（多数 `/social/*`）**：
  - 权限不足/参数异常通常通过 `flash + redirect (302)` 处理。
- **JSON 路由**：
  - `messages/unread_count` 返回 JSON。
  - 部分点赞/收藏在 AJAX 请求头下返回 JSON。
- **状态码语义**：
  - 页面流不强制使用 `401/403`，以用户可见跳转为主。
  - API 场景按接口约定返回 `200/400/403` 等。

## Feed Keyword Search
* Search box at the top of the community feed matches keywords in post titles and bodies (case-insensitive, `%`/`_` wildcards escaped, max 80 chars).
* Combines with category tabs and pagination; pinned-first ordering is suspended while searching (pure recency instead).
* Soft-deleted posts never appear in results.
