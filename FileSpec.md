# NTU Swimming Pool Web 文件规格说明（FileSpec）

> 本文档描述仓库当前代码结构、关键文件职责、依赖关系与安全控制点。  
> 更新时间：2026-02-15

---

## 1. 目录结构（当前）

```text
Swim_Pool_Web_Dev/
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── extensions.py
│   ├── blueprints/
│   │   ├── auth.py
│   │   ├── social.py
│   │   ├── weather.py
│   │   ├── live_status.py
│   │   └── misc.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── utils.py
│   │   ├── user.py
│   │   ├── content.py
│   │   ├── interaction.py
│   │   ├── report.py
│   │   ├── content_report.py
│   │   └── private_message.py
│   ├── services/
│   │   └── weather_engine.py
│   ├── static/
│   │   ├── input.css
│   │   ├── img/logo.png
│   │   └── js/
│   │       ├── weather.js
│   │       ├── weather_v2.js
│   │       └── live_status.js
│   └── templates/
│       ├── base.html
│       ├── index.html
│       ├── auth/
│       │   ├── login.html
│       │   ├── register.html
│       │   ├── verify_otp.html
│       │   ├── unverified.html
│       │   ├── reset_request.html
│       │   └── reset_password.html
│       └── social/
│           ├── feed.html
│           ├── create_post.html
│           ├── edit_post.html
│           ├── post_detail.html
│           ├── profile.html
│           ├── profile_edit.html
│           ├── messages.html
│           ├── chat.html
│           └── admin_reports.html
├── tests/
│   ├── test_haversine.py
│   ├── test_profile_flow.py
│   ├── test_auth_security.py
│   ├── verify_rainfall.py
│   ├── sample_nea_lightning_data.json
│   └── sample_nea_rainfall_data.json
├── instance/
├── run_server.py
├── init_db.py
├── reset_db.py
├── deploy.bat
├── deploy_update.bat
├── deploy.ps1
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── README.md
└── FileSpec.md
```

---

## 2. 根目录文件职责

| 文件 | 职责 | 说明 |
|---|---|---|
| `run_server.py` | 本地开发启动入口 | 调用 `create_app()`，初始化数据库并启动服务 |
| `init_db.py` | 初始化数据库 | 执行 `db.create_all()` |
| `reset_db.py` | 重置数据库 | 开发环境危险脚本（DROP + CREATE） |
| `Dockerfile` | 生产镜像构建 | Cloud Run 使用，默认监听 `8080` |
| `docker-compose.yml` | 本地编排 | web + PostgreSQL |
| `deploy.bat` | 全量部署脚本 | Build + Deploy |
| `deploy_update.bat` | 更新部署脚本 | 已改为更稳健的 cmd 语法，自动检查 `gcloud`、注入生产 env |
| `deploy.ps1` | PowerShell 部署脚本 | 与 bat 版本用途一致 |
| `requirements.txt` | Python 依赖 | Flask/SQLAlchemy/Flask-Login/Flask-Mail 等 |
| `.env.example` | 环境变量模板 | 包含 `SECRET_KEY`、`DATABASE_URL`、`NEA_API_KEY` 等 |

---

## 3. 应用核心 (`app/`)

### 3.1 `app/__init__.py`

职责：
- 应用工厂 `create_app()`
- 扩展初始化（`db`, `mail`, `login_manager`）
- 蓝图注册
- 首页路由 `/`
- 全局未读私信计数注入
- CSRF 保护（自实现）
- 生产环境启动前配置校验

关键安全逻辑：
- 生产环境强制校验：
  - `SECRET_KEY` 不能是弱默认值
  - 必须配置数据库连接
- `before_request` 对 `POST/PUT/PATCH/DELETE` 进行 CSRF 校验
- 模板全局函数 `csrf_token()` 生成签名 token（`itsdangerous`）

### 3.2 `app/config.py`

职责：
- 统一配置类：`DevelopmentConfig` / `ProductionConfig` / `TestingConfig`
- 读取 `.env`
- Cookie 与上传大小等安全相关默认项

关键配置：
- `WTF_CSRF_TIME_LIMIT` 默认 `3600` 秒
- `MAX_CONTENT_LENGTH` 默认 `2 * 1024 * 1024`（2MB）
- 生产环境启用 `SESSION_COOKIE_SECURE=True`、`REMEMBER_COOKIE_SECURE=True`

### 3.3 `app/extensions.py`

职责：
- 创建扩展实例：`db`, `mail`, `login_manager`
- `user_loader` 从数据库加载当前用户

---

## 4. 蓝图与路由

### 4.1 `app/blueprints/auth.py`

职责：登录、注册、OTP 验证、重置密码、登出。

当前路由（前缀 `/auth`）：

| 路由 | 方法 | 用途 |
|---|---|---|
| `/register` | GET/POST | 注册并发送 OTP |
| `/login` | GET/POST | 登录 |
| `/logout` | POST | 登出（已从 GET 改为 POST） |
| `/verify` | GET/POST | 邮箱 OTP 验证 |
| `/resend` | POST | 重发 OTP（已从 GET 改为 POST） |
| `/password/reset-request` | GET/POST | 发起密码重置 |
| `/password/reset` | GET/POST | OTP + 新密码完成重置 |
| `/unverified` | GET | 重定向到 `/verify` |
| `/confirm/<token>` | GET | 旧 token 验证入口（已废弃，提示使用 OTP） |

安全实现：
- OTP 由 `secrets` 生成
- OTP 会话状态隔离：`verify` 与 `reset` 分开
- OTP 错误尝试上限 + 锁定窗口
- 密码最小长度校验
- 邮箱归一化防空值错误

### 4.2 `app/blueprints/social.py`

职责：社区帖子/评论/点赞/收藏/举报/私信/资料管理。

关键实现更新：
- 头像上传大小限制：读取 `MAX_CONTENT_LENGTH`（默认 2MB）
- 点赞/收藏/评论点赞并发冲突处理（`IntegrityError`）
- 浏览数原子更新
- 多处查询做了 N+1 优化

### 4.3 `app/blueprints/weather.py`

职责：提供 `GET /weather/status`，返回天气状态 JSON。

### 4.4 `app/blueprints/live_status.py`

职责：提供 `GET/POST /api/live-status/`，读取和上报泳池人工状态。

### 4.5 `app/blueprints/misc.py`

职责：杂项占位接口（如 `/locker`）。

---

## 5. 模型层 (`app/models/`)

| 文件 | 主要模型/职责 |
|---|---|
| `user.py` | 用户、密码哈希、OTP 字段、token 生成/验证（用途隔离 + 过期控制） |
| `content.py` | 帖子 `Post`、评论 `Comment` |
| `interaction.py` | 点赞、收藏、评论点赞 |
| `report.py` | 泳池状态上报 `PoolReport` |
| `content_report.py` | 内容举报 |
| `private_message.py` | 私信 |
| `utils.py` | `TimestampMixin` |
| `__init__.py` | 模型统一导出 |

`user.py` 重点：
- `generate_password_hash` / `check_password_hash`
- `generate_auth_token(purpose=...)`
- `verify_auth_token(..., purpose=..., max_age=...)`
- token salt 使用 `user-token:<purpose>`，避免不同用途 token 混用

---

## 6. 服务层 (`app/services/weather_engine.py`)

职责：聚合运营时间、社区共识、闪电、降雨，生成最终泳池状态。

关键更新：
- 外部 API 异常时不再 fail-open 为 GREEN
- 错误场景更倾向返回 AMBER
- 使用 logger 记录异常（替换 `print`）

---

## 7. 前端静态资源与模板

### 7.1 JS 文件

| 文件 | 作用 |
|---|---|
| `app/static/js/weather.js` | 轮询天气接口并更新首页状态 |
| `app/static/js/weather_v2.js` | 与 `weather.js` 逻辑一致，用于缓存绕过与版本切换 |
| `app/static/js/live_status.js` | 轮询并上报人工状态；前端渲染避免直接拼接不可信 HTML；POST 带 CSRF header |

### 7.2 模板

| 文件 | 关键点 |
|---|---|
| `app/templates/base.html` | 注入 CSRF meta、统一为 POST 表单补 `csrf_token`、登出改为 POST |
| `app/templates/index.html` | 当前加载 `weather_v2.js`（带版本参数）与 `live_status.js` |
| `app/templates/auth/*.html` | 登录/注册/重置/OTP 表单均包含 `csrf_token` |
| `app/templates/social/*.html` | 社区页面模板 |

---

## 8. 测试 (`tests/`)

| 文件 | 覆盖内容 |
|---|---|
| `test_haversine.py` | 地理距离计算 |
| `test_profile_flow.py` | 资料编辑与流程 |
| `test_auth_security.py` | 认证安全回归（OTP 锁定、token 用途/过期、无后门登录等） |
| `verify_rainfall.py` | 降雨解析验证脚本 |

当前已新增并通过的安全测试主要针对：
- 后门账户绕过
- 空邮箱输入健壮性
- token 用途隔离与过期
- OTP 连续失败锁定

---

## 9. 部署说明（与当前代码对齐）

`deploy_update.bat` 现行为：
1. 检查 `gcloud` 是否可用
2. 执行 `gcloud builds submit --tag <IMAGE>`
3. 执行 `gcloud run deploy`，并设置：
   - `FLASK_ENV=production`
   - `FLASK_CONFIG=production`
   - `SECRET_KEY=<当前环境或临时生成>`
4. 输出 Cloud Run 服务 URL

---

## 10. 关键环境变量

| 变量 | 用途 |
|---|---|
| `SECRET_KEY` | 会话签名、CSRF 签名、token 签名 |
| `DATABASE_URL` / `SQLALCHEMY_DATABASE_URI` | 数据库连接 |
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_USE_TLS` | OTP 邮件发送 |
| `NEA_API_KEY` | 新加坡 NEA 天气接口鉴权 |
| `FLASK_CONFIG` | `development` / `production` / `testing` |
| `MAX_CONTENT_LENGTH` | 上传体积上限（默认 2MB） |
| `WTF_CSRF_TIME_LIMIT` | CSRF token 有效期 |

---

## 11. 近期变更摘要（便于 commit 对照）

- 新增：`app/static/js/weather_v2.js`
- 新增：`tests/test_auth_security.py`
- 更新：`app/__init__.py`（CSRF + 生产配置 fail-fast）
- 更新：`app/blueprints/auth.py`（OTP 流程隔离、锁定、POST 化）
- 更新：`app/blueprints/social.py`（并发一致性、头像上传限制）
- 更新：`app/models/user.py`（token 目的隔离 + 过期）
- 更新：`app/services/weather_engine.py`（异常回退策略、日志）
- 更新：`app/static/js/live_status.js`（更安全渲染 + CSRF header）
- 更新：`app/templates/base.html` 与 `app/templates/auth/*`（CSRF）
- 更新：`app/templates/index.html`（切换 `weather_v2.js`）
- 更新：`deploy_update.bat`（脚本健壮性与生产 env 注入）
