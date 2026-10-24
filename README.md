# English Reading Agent

英语阅读学习助手：提供分级英文书库、分页阅读器、基于 RAG 的章节问答、AI 翻译与英语水平测试，全部能力通过 Web 页面使用。

## 功能总览

| 模块 | 说明 |
| --- | --- |
| 认证 | 注册 / 登录，JWT Bearer token 校验，所有业务接口均需登录 |
| 书架 | 118 本公版英文书（16 个中文分类标签），分类 / 难度筛选与搜索，分页浏览，热门书籍角标，Open Library 真实封面，缺封面用树皮纹理占位 |
| 排行榜 | 热度榜单：浏览 / 读完章节 / 点赞 / 收藏加权 + 14 天半衰期衰减 + 贝叶斯收缩，计算 0-100 热度分，Redis 缓存 10 分钟 |
| 阅读器 | 章节目录、分页排版（固定阅读框 + 键盘翻页）、阅读进度自动保存续读、「我的书单」下拉（只列读过 / 点赞 / 收藏过的书）、点赞 / 收藏按钮 |
| AI 问答 | `/ask/reading`：基于当前章节的 RAG 检索问答，证据不足时明确拒答不编造 |
| AI 翻译 | 翻译本页 / 任意语言对互译，多翻译通道与付费通道预留 |
| 水平测试 | 24 题静态题库（A2~C1 × 词汇/语法/阅读），自动评分定级，按难度推荐书单并保存历史 |

## 技术栈

- **后端**：FastAPI + SQLAlchemy（async）+ pydantic-settings，同步第三方调用走线程池
- **数据库**：PostgreSQL 16 + pgvector（向量检索）、内置 ts_rank 全文检索、Redis（token 与热度榜单缓存）
- **AI**：BGE-M3 本地 embedding（1024 维）、DeepSeek chat API（问答 / 查询改写 / 翻译）
- **前端**：Vue 3 + Vite + Tailwind CSS（`frontend-app/`），组件化单页应用
- **测试**：pytest（单元测试 + 检索基准）

## 架构

严格分层：`app/api/routes`（HTTP 层）→ `app/services`（业务层）→ `app/repositories`（数据层）→ `app/models`（表结构），请求/响应模型在 `app/schemas`。

```
app/
├── api/routes/        # 路由：auth、book、reading、ask、level_test、translate
├── services/          # 业务：book、reading、chapter、hotness、level_test、translation、retrieval、llm、user
├── repositories/      # 数据访问
├── models/            # SQLAlchemy 模型
├── schemas/           # Pydantic 请求/响应模型
├── scripts/           # 数据准备脚本：爬虫、章节/分块入库、向量化、封面回填
├── crawler/           # Gutenberg 爬虫
├── chunking.py        # 递归字符分块（800/100，段落优先）
├── embedding.py       # BGE-M3 单例加载
└── level_bank.py      # 水平测试题库
frontend-app/           # Vue 3 + Vite + Tailwind 前端（登录、书库、阅读、水平测试、翻译）
tests/                  # pytest 测试与 25 题检索基准
data/books/             # 爬取的书籍内容（gitignore，不入库）
```

## 快速开始

> 本地开发约定端口：后端 `8002`、PostgreSQL `5435`、Redis `6380`（避开本机 8000/8001/6379 占用）。

```bash
# 1. 启动数据库
docker compose up -d

# 2. 配置环境变量（.env）
#    DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5435/reading
#    REDIS_URL=redis://127.0.0.1:6380/0
#    DEEPSEEK_API_KEY=sk-xxx

# 3. 安装依赖
pip install -r requirements.txt

# 4. 数据准备（首次运行）
python -m app.crawler                          # 爬取书籍到 data/books/
python -m app.scripts.crawl_easy_books --target 100   # 低难度分级书（可选补充）
python -m app.scripts.load_chapters            # 章节入库（自动切分）
python -m app.scripts.load_chunks              # 正文分块入库
python -m app.scripts.embed_chunks             # BGE-M3 向量化
python -m app.scripts.backfill_covers          # Open Library 封面回填

# 5. 启动
uvicorn app.main:app --host 127.0.0.1 --port 8002          # 后端（启动时自动建表/建索引/启用 pgvector）
cd frontend-app && npm install && npm run dev              # 前端开发服务器（http://localhost:5173）
```

访问 `http://localhost:5173` 注册登录后使用；接口文档在 `http://127.0.0.1:8002/docs`。生产部署执行 `npm run build` 后托管 `frontend-app/dist/` 静态产物。

## 主要接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | /auth/register · /auth/login | 注册 / 登录 |
| GET | /me | 当前用户信息 |
| GET | /books | 书籍列表（书架） |
| GET | /books/mine | 我的书单（读过 / 点赞 / 收藏过的书） |
| GET | /books/search?title= | 按书名查简介 |
| GET | /books/hot | 热门榜单（按热度分排序） |
| GET | /books/{book_id}/hot | 单本书热度详情（分项计数 + 排名 + 互动状态） |
| POST | /books/{book_id}/like · /favorite | 点赞 / 收藏切换 |
| POST | /books/{book_id}/events | 阅读行为上报（读完章节，同人同书每日限计 1 次） |
| GET | /books/{book_id}/chapters | 章节目录 |
| GET | /books/{book_id}/chapters/{chapter_index} | 章节正文 |
| GET/PUT | /reading/progress/{book_id} | 阅读进度读取 / 保存 |
| POST | /ask | 通用 LLM 问答 |
| POST | /ask/reading | 基于当前章节的 RAG 问答 |
| GET | /level-test/questions | 下发测试题（不含答案） |
| POST | /level-test/submit | 提交评分，返回等级 / 能力分析 / 推荐书目 |
| GET | /level-test/result | 最近一次测试结果 |
| POST | /translate | 文本翻译（支持多语言对） |

以上除注册/登录外均需 `Authorization: Bearer <token>`。

## 检索方案（RAG）

- 双路召回：pgvector 余弦相似度（BGE-M3）+ PostgreSQL `ts_rank` 全文检索（OR 词元组合）
- 多查询融合：查询改写（中文问题 → 英文检索式）后与原查询四列表 RRF 融合（k=60）
- 评测：固定 25 题基准（`tests/retrieval_cases.py`），当前 Recall@5 = 90.5%、MRR = 0.811，逐题明细见 `tests/benchmark_results.json`
- 原则：新增检索组件必须先在基准上验证可量化收益，不做无验证的复杂化

## 测试

```bash
pytest
```

单元测试不依赖外部环境；检索基准测试在数据库可用时自动运行（缺失环境自动 skip）。

## 已知限制

- 水平测试为「初步评估」（每等级每维度仅 2 题），非精确 CEFR 认证
- 应用启动时自动建表/建索引仅适用于开发环境，生产需迁移至 Alembic
- 书籍正文不入 Git（`data/` 已忽略），需本地运行爬虫生成
- 前端翻译历史存于浏览器 localStorage，未跨设备同步
