# 钯盐系统

基于 Django 的钯盐管理系统（独立项目）。

## 技术栈

- 后端：Python 3.12 + Django 6.x
- 前端：Django Templates + 静态资源（自研 CSS/JS，无额外框架依赖）
- 数据库：SQLite（开发环境，可按需切换 MySQL/PostgreSQL）

## 目录结构

```
钯盐系统/
├── manage.py                 # 管理脚本
├── requirements.txt          # Python 依赖
├── db.sqlite3                # SQLite 数据库
├── palladium_system/         # 项目配置（settings / urls / wsgi）
├── palladium/                # 业务应用（models / views / urls）
├── templates/                # 全局模板
│   ├── base.html             # 基础布局（侧边栏 + 顶栏）
│   └── palladium/            # 应用页面模板
├── static/                   # 静态资源
│   ├── css/base.css
│   ├── js/base.js
│   └── img/
└── media/                    # 上传文件
```

## 本地运行

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

访问 http://127.0.0.1:8000/

默认管理员账号：`admin` / `admin123`（后台地址 http://127.0.0.1:8000/admin/ ）

## 说明

当前为系统骨架（可运行的占位首页），具体业务模块（页面布局、数据模型、
业务流程）将根据后续提供的系统截图与业务逻辑说明进行仿照开发。
