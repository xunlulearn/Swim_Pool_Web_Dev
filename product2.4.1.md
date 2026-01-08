# 社交功能重构实施计划

根据 `product2.4.md` 规范，重构现有社交功能系统，支持完整的帖子、评论、互动、举报及管理员监管功能。

## User Review Required

> [!IMPORTANT]
> **破坏性变更**: 本次重构将删除以下现有功能：
> - `Group` 模型及群组成员功能 (新规范中无此功能)
> - `friendships` 好友关系表 (新规范中无此功能)
> - 现有的简单 `Post/Comment` 模型将被完全重写

> [!WARNING]
> **数据库迁移**: 执行此变更后，现有的 `posts`、`comments`、`groups`、`friendships` 表数据将丢失。如需保留数据，请先备份。

---

## Proposed Changes

### 1. 模型层 (Models)

#### [DELETE] [group.py](file:///d:/Swim_Pool_Web_Dev/app/models/group.py)
删除 Groups 功能，新规范中不需要。

---

#### [MODIFY] [user.py](file:///d:/Swim_Pool_Web_Dev/app/models/user.py)

**需删除的内容:**
- `friendships` 关联表
- `friends` 关系定义

**需新增的字段:**
```python
role = db.Column(db.String(20), default='user')  # 'user' | 'admin'
is_banned = db.Column(db.Boolean, default=False)
```

**需新增的关系:**
```python
likes = db.relationship('Like', backref='user', lazy='dynamic')
collections = db.relationship('Collection', backref='user', lazy='dynamic')
content_reports = db.relationship('ContentReport', backref='reporter', lazy='dynamic', foreign_keys='ContentReport.reporter_id')
```

---

#### [MODIFY] [content.py](file:///d:/Swim_Pool_Web_Dev/app/models/content.py)

**完全重写 Post 模型:**
```python
class Post(TimestampMixin, db.Model):
    __tablename__ = 'posts'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(255))
    category = db.Column(db.String(20), default='general')  # general, squad, lostfound, tutorial
    is_pinned = db.Column(db.Boolean, default=False)
    is_deleted = db.Column(db.Boolean, default=False)  # 软删除
    view_count = db.Column(db.Integer, default=0)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Relationships
    comments = db.relationship('Comment', backref='post', lazy='dynamic')
    likes = db.relationship('Like', backref='post', lazy='dynamic')
    collections = db.relationship('Collection', backref='post', lazy='dynamic')
```

**完全重写 Comment 模型:**
```python
class Comment(TimestampMixin, db.Model):
    __tablename__ = 'comments'

    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False)  # 软删除
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False)
```

---

#### [NEW] [interaction.py](file:///d:/Swim_Pool_Web_Dev/app/models/interaction.py)

```python
class Like(db.Model):
    __tablename__ = 'likes'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())
    
    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='unique_like'),)


class Collection(db.Model):
    __tablename__ = 'collections'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())
    
    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='unique_collection'),)
```

---

#### [NEW] [content_report.py](file:///d:/Swim_Pool_Web_Dev/app/models/content_report.py)

```python
class ContentReport(db.Model):
    __tablename__ = 'content_reports'
    
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    target_type = db.Column(db.String(20), nullable=False)  # 'post' | 'comment'
    target_id = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, resolved, rejected
    created_at = db.Column(db.DateTime, default=db.func.now())
```

---

#### [MODIFY] [\_\_init\_\_.py](file:///d:/Swim_Pool_Web_Dev/app/models/__init__.py)

更新导出列表:
```python
from .user import User
from .content import Post, Comment
from .interaction import Like, Collection
from .content_report import ContentReport
from .report import PoolReport
```

---

### 2. Blueprint 层 (Routes/API)

#### [MODIFY] [social.py](file:///d:/Swim_Pool_Web_Dev/app/blueprints/social.py)

**完全重写，包含以下路由:**

| 路由 | 方法 | 权限 | 描述 |
|-----|------|------|------|
| `/social/` | GET | All | 社区首页（帖子列表） |
| `/social/post/<id>` | GET | All | 帖子详情 |
| `/social/post` | POST | User/Admin | 发布帖子 |
| `/social/post/<id>` | PUT | Owner/Admin | 编辑帖子 |
| `/social/post/<id>` | DELETE | Owner/Admin | 软删除帖子 |
| `/social/post/<id>/comment` | POST | User/Admin | 发布评论 |
| `/social/comment/<id>` | DELETE | Owner/Admin | 软删除评论 |
| `/social/post/<id>/like` | POST | User/Admin | 点赞/取消点赞 |
| `/social/post/<id>/collect` | POST | User/Admin | 收藏/取消收藏 |
| `/social/post/<id>/report` | POST | User/Admin | 举报帖子 |
| `/social/post/<id>/pin` | POST | Admin only | 置顶帖子 |
| `/social/user/<id>/ban` | POST | Admin only | 封禁用户 |
| `/social/profile` | GET | User/Admin | 个人中心 |
| `/social/admin/reports` | GET | Admin only | 举报管理 |

**权限装饰器设计:**
```python
def login_required_or_guest(view_func):
    """允许游客访问，但提供 current_user 信息"""
    ...

def admin_required(view_func):
    """仅管理员可访问"""
    ...

def check_banned(view_func):
    """拦截被封禁用户的所有 POST 请求"""
    ...
```

---

### 3. 模板层 (Templates)

#### [MODIFY] [feed.html](file:///d:/Swim_Pool_Web_Dev/app/templates/social/feed.html)

重写为社区首页，包含：
- 分类筛选 Tab (全部 / 约游 / 失物招领 / 教学)
- 置顶帖子优先显示
- 帖子卡片（含标题、摘要、作者、点赞/评论数）
- 游客可浏览，登录用户可发帖

---

#### [NEW] [post_detail.html](file:///d:/Swim_Pool_Web_Dev/app/templates/social/post_detail.html)

帖子详情页：
- 完整帖子内容
- 评论列表
- 点赞/收藏按钮
- 管理员操作按钮（置顶、删除、封禁作者）

---

#### [NEW] [profile.html](file:///d:/Swim_Pool_Web_Dev/app/templates/social/profile.html)

个人中心页：
- 我的帖子列表
- 我的收藏列表

---

#### [NEW] [admin_reports.html](file:///d:/Swim_Pool_Web_Dev/app/templates/social/admin_reports.html)

管理员举报管理页：
- 待处理举报列表
- 操作按钮（解决/拒绝）

---

## Verification Plan

### Automated Tests
```bash
# 重建数据库后验证模型
python init_db.py

# 启动服务器
python run_server.py
```

### Manual Verification
1. **游客测试**: 访问 `/social/`，验证可浏览帖子列表但无法发帖
2. **普通用户测试**: 登录后发帖、评论、点赞、收藏、举报
3. **管理员测试**: 验证置顶、删除任意帖子、封禁用户功能
4. **软删除测试**: 删除帖子后验证前端不显示，但数据库仍保留记录
5. **权限矩阵验证**: 按 `product2.4.md` 中的权限矩阵逐项验证
