# 2.4 Social Network

* **Community Feed**: Reverse chronological order. Support for text and images.

# 游泳馆网站社交功能需求规范 (Social Features Specification)
## 1. 项目概述
本模块旨在为游泳馆网站构建一套完整的社交社区系统。系统需支持用户交流（发帖、评论）、互动（点赞、收藏）以及管理员的内容监管。

## 2. 用户角色定义 (User Roles)

系统需在 `User` 模型中通过字段（如 `role_id` 或 `role_name`）区分以下三种角色：

1.  **游客 (Guest):** 未登录用户。
2.  **普通用户 (User):** 已注册并登录的标准用户。
3.  **管理员 (Admin):** 拥有系统维护和监管权限的高级账户。

## 3. 权限矩阵 (Permission Matrix)

| 功能模块 | 动作 (Action) | 游客 (Guest) | 普通用户 (User) | 管理员 (Admin) | 备注/逻辑 |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **浏览** | 查看帖子列表 | ✅ | ✅ | ✅ | |
| | 查看帖子详情 | ✅ | ✅ | ✅ | 包含评论区可见 |
| | 搜索帖子 | ✅ | ✅ | ✅ | |
| **内容创作** | 发布帖子 (Post) | ❌ | ✅ | ✅ | 管理员通常发布公告 |
| | 发布评论 (Comment) | ❌ | ✅ | ✅ | |
| **编辑/修改** | 编辑帖子/评论 | ❌ | ✅ (仅限本人) | ✅ (任意) | |
| **删除** | 删除帖子/评论 | ❌ | ✅ (仅限本人) | ✅ (任意) | **必须执行软删除 (Soft Delete)** |
| **互动** | 点赞 (Like) | ❌ | ✅ | ✅ | 需防重复点赞 |
| | 收藏 (Save/Bookmark)| ❌ | ✅ | ✅ | |
| **管理/风控** | 置顶帖子 (Pin) | ❌ | ❌ | ✅ | |
| | 举报内容 (Report) | ❌ | ✅ | ✅ | |
| | 封禁用户 (Ban) | ❌ | ❌ | ✅ | 禁止用户登录或发帖 |
| | 查看举报列表 | ❌ | ❌ | ✅ | |

## 4. 数据库模型需求 (Schema Requirements)

请根据以下关键字段要求更新或创建 Data Model (ORM)：

### A. 用户表 (User) 扩充
* `role`: 枚举或整数，区分 User/Admin。
* `is_banned`: 布尔值，默认为 False。如果为 True，该用户的所有 POST 请求应被拦截。
* `nickname`: 字符串，用户昵称 (默认为邮箱前缀或随机生成)。
* `avatar`: 二进制数据 (BLOB)，直接存储图片文件 (支持 JPEG/PNG, 建议压缩至 200KB 以内)。
* `avatar_mimetype`: 字符串，记录图片类型 (如 image/jpeg)。

### B. 帖子表 (Post)
* `author_id`: 外键，关联 User。
* `title`: 字符串。
* `body`: 文本（支持 Markdown 或富文本）。
* `is_pinned`: 布尔值，默认为 False（仅管理员可改）。
* `is_deleted`: 布尔值，默认为 False（软删除标记）。
* `view_count`: 整数，浏览量计数。
* `created_at` / `updated_at`: 时间戳。

### C. 评论表 (Comment)
* `post_id`: 外键，关联 Post。
* `author_id`: 外键，关联 User。
* `body`: 文本。
* `is_deleted`: 布尔值，默认为 False。

### D. 互动表 (Interaction/Like/Save)
* *建议*: 创建多对多关系表或独立的 `Like` 和 `Collection` 表，记录 `user_id` 和 `post_id`，防止重复操作。

### E. 举报表 (Report) - *新增*
* `reporter_id`: 发起举报的用户 ID。
* `target_id`: 被举报的帖子或评论 ID。
* `reason`: 字符串（如：广告、辱骂、无关内容）。
* `status`: 枚举（Pending/Resolved/Rejected）。

## 5. 业务逻辑与约束 (Business Logic)

### 5.1 软删除机制 (Soft Delete)
* 当用户或管理员执行“删除”操作时，**严禁**执行 SQL `DELETE`。
* **操作**: 必须将目标记录的 `is_deleted` 字段更新为 `True`。
* **查询**: 所有前端可见的查询接口（Get Posts, Get Comments）必须默认过滤掉 `is_deleted=True` 的记录。

### 5.2 个人中心逻辑
* 用户可以在“个人中心”查看自己发布的帖子历史。
* 用户可以在“个人中心”查看自己“收藏”的帖子列表。
* **资料/安全设置**:
    * 用户可在此页面修改昵称和头像。
    * 用户可在此页面发起修改密码流程 (需 OTP 验证)。

### 5.3 管理员特权
* 管理员在前端应看到额外的操作按钮：【置顶】、【直接删除】、【封禁该作者】。
* 管理员应有一个专门的 Dashboard 页面查看 `Report` 表中的数据。

### 5.4 游泳馆特色分类 (可选建议)
在 Post 模型中建议增加 `category` 字段，预设以下分类：
* `General`: 一般讨论
* `Squad`: 约游/找搭子
* `LostFound`: 失物招领
* `Tutorial`: 游泳教学/装备讨论

## 6. API 响应标准 (API Response)

* **401 Unauthorized**: 游客尝试进行需要登录的操作（如发帖）。
* **403 Forbidden**: 普通用户尝试进行管理员操作（如置顶），或用户尝试删除非自己发布的帖子。
* **200 OK**: 操作成功，需返回更新后的数据对象。
