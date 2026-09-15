# 科研Agent 技术文档

> **项目代号**:AcademicAgent
> **版本**:v0.3(设计稿)
> **日期**:2026-08-09
> **状态**:技术方案定稿,待开发

---

## 1. 项目概述

### 1.1 项目目标

构建一个**本地桌面版科研 Agent**,面向科研用户,核心能力:

1. **双语阅读**:打开 PDF 论文,左侧原样展示原文,右侧展示逐段中文译文,版式与公式不乱。
2. **对话问答**:右侧可与大模型对话,就当前论文提问;大模型具备工具调用能力,可自主检索。
3. **论文库 + RAG**:沉淀个人论文库,支持跨论文检索,让大模型理解用户的研究方向。
4. **自动总结**:agent 可对单篇论文生成摘要、关键要点、术语表等。
5. **精美 GUI**:界面参考 OpenAI Codex 风格(深色主题、停靠面板、流式输出),设置页可切换 DeepSeek / OpenAI 等大模型。
6. **Web 实时搜索**:agent 内置 `web_search` 能力,可获取最新论文动态/资讯,弥补静态论文库无法覆盖的实时信息。
7. **Skills 扩展体系**:可插拔的技能注册表,新增能力只需"丢一个技能文件夹",不改核心代码。
8. **会话持久化**:聊天记录本地保存,应用重启或隔天打开后可继续历史会话。

### 1.2 核心设计决策(务必先读)

| # | 决策 | 原因 |
|---|------|------|
| D1 | **GUI 双语展示不使用 pdf2zh 黑盒**,而是 PyMuPDF 抽块 + LLM 逐块翻译 | GUI 需要"原文块↔译文块"的结构化数据(含坐标),pdf2zh 公开 API 是"输入 PDF → 输出翻译后 PDF",不吐中间结构 |
| D2 | **不做划词翻译**,改为块级点击交互(点段落高亮 / 点击显示译文) | 划词需要词级坐标命中检测,复杂度高;块级交互用 `get_text("dict")` 已有的 bbox,简单一个量级 |
| D3 | **公式/排版不重建**。原文以渲染图片原样展示,译文以文本列表展示 | "公式会不会乱"只发生在重新排版 PDF 时;原文图片方案中公式永远原样显示 |
| D4 | **Agent 用 Python + OpenAI 原生 API 实现**,不引入 LangChain 等框架 | 学习阶段,原生 API(tools=[])能真正理解 agent 循环本质 |
| D5 | **一份块数据两用**:GUI 双语展示 与 RAG 论文库 共用同一套抽取分块结果 | 避免重复工作,架构简洁 |
| D6 | **pdf2zh 降级为可选导出功能**(最后期接入) | 仅当需要"生成整篇双语 PDF 文件"时才调用其库接口,不影响核心架构 |
| D7 | **v1 不支持扫描版 PDF(无文字层)**,不做 OCR | OCR 使难度翻倍;若需 OCR,后续用 MinerU 独立模块接入 |
| D8 | **Web 搜索 = 普通工具**:与本地 RAG 检索并列进入同一个 tools 循环,由模型自主选择"查本地论文库"还是"搜实时网络" | 实现成本仅"多一个工具定义 + 一个搜索封装",却让 agent 获得实时信息能力 |
| D9 | **Skills = 可插拔注册表**:技能以"文件夹 + 自描述(SKILL.md)"注册,启动时扫描加载即生成 tools | 扩展新能力零侵入核心代码;新增技能 = 丢一个文件夹 |
| D10 | **会话持久化 = SQLite + 本地用户数据目录**:保存会话元数据、消息和工具调用记录,应用启动时可恢复 | SQLite 无需独立服务;`platformdirs` 保证 Windows 下数据与源码/虚拟环境分离 |

### 1.3 明确不做的事(v1)

- ❌ 重新排版 / 保版式导出 PDF(由 pdf2zh 可选承担)
- ❌ 划词翻译(词级选区合并)
- ❌ 扫描版 PDF OCR
- ❌ 复杂 agent 框架 / 多 agent 编排
- ❌ 云端部署、多用户

---

## 2. 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                        PyQt6 GUI 桌面应用                     │
│                                                             │
│  ┌─────────────────┐  ┌──────────────────────────────────┐  │
│  │  左侧:PDF 阅读区  │  │  右侧:对话/译文面板 (QDockWidget)  │  │
│  │  · 渲染页面为图片  │  │  · 译文列表(双语对照)             │  │
│  │  · 块高亮交互      │  │  · Agent 对话(流式输出)           │  │
│  │  · 缩放/翻页       │  │  · 摘要/要点卡片                 │  │
│  └─────────┬─────────┘  └──────────────┬───────────────────┘  │
│            │                            │                     │
└────────────┼────────────────────────────┼─────────────────────┘
             │                            │
             ▼                            ▼
   ┌─────────────────────┐   ┌──────────────────────┐
   │   核心服务层         │   │   Agent 引擎           │
   │  PDFParser(抽块)    │   │  · 工具调用循环(tools)  │
   │  Translator(翻译)   │   │  · 工具:               │
   │  PaperRepo(论文库)  │   │    search_papers
   │  RAGEngine(检索)    │   │    get_paper_summary   │
   │  SessionStore(会话) │   │    extract_key_points  │
   │  (可选)PDFExporter  │   │    translate_text      │
   └─────────┬───────────┘   │    extract_key_points  │
             │               └──────────┬─────────────┘
             │                          │
             └──────────────┬───────────┘
                            ▼
              ┌─────────────────────────┐
              │   模型访问层 (统一接口)   │
              │  · openai SDK(DeepSeek) │
              │  · openai SDK(OpenAI)   │
              │  · 本地 embedding       │
              └─────────────────────────┘
```

### 2.1 分层职责

| 层 | 职责 | 关键依赖 |
|----|------|---------|
| **UI 层** | PyQt6 窗口、渲染、交互、样式 | PyQt6 |
| **核心服务层** | PDF 解析抽块、翻译编排、论文库管理、RAG 检索、会话持久化 | PyMuPDF, sentence-transformers, FAISS, `sqlite3`, `platformdirs` |
| **Agent 引擎** | 原生 tools 循环、技能注册表加载、会话上下文管理 | openai SDK |
| **模型访问层** | 统一封装多模型切换(base_url + api_key + model) | openai SDK |

### 2.2 模块划分(目录结构草案)

```
AcademicAgent/
├── app/
│   ├── main.py                 # 入口,启动 GUI
│   ├── config.py               # 全局配置(模型/路径/主题)
│   ├── settings_store.py       # 设置持久化(JSON)
│   ├── ui/
│   │   ├── main_window.py      # 主窗口,停靠面板布局
│   │   ├── pdf_viewer.py       # PDF 渲染 + 块高亮交互
│   │   ├── chat_panel.py       # 对话面板(流式输出)
│   │   ├── translation_panel.py# 译文列表
│   │   ├── settings_dialog.py  # 模型设置对话框
│   │   └── themes/             # QSS 深色主题
│   ├── core/
│   │   ├── pdf_parser.py       # 抽块:get_text("dict") + 栏排序
│   │   ├── translator.py       # 逐块翻译编排
│   │   ├── paper_repo.py       # 论文库:注册/删除/索引管理
│   │   ├── rag_engine.py       # embedding + FAISS 检索
│   │   └── session_store.py    # SQLite 会话/消息持久化
│   ├── agent/
│   │   ├── agent_loop.py       # 原生 tools 循环(ReAct)
│   │   ├── registry.py         # 技能注册表(扫描 skills/ 生成 tools)
│   │   ├── skills.py           # 默认技能目录定位
│   │   ├── web_search.py       # web_search 技能实现
│   │   └── prompts.py          # 系统提示词
│   ├── skills/                 # 技能目录(每个技能一个子文件夹)
│   │   ├── web_search/         # 例:Web 搜索
│   │   ├── paper_summary/      # 例:论文摘要
│   │   └── extract_key_points/ # 例:要点/术语表
│   └── exporter/
│       └── pdf_exporter.py     # (可选)调 pdf2zh 导出双语 PDF
├── data/                       # 本地数据(论文/向量库/缓存)
├── requirements.txt
└── TECHNICAL_DOC.md
```

> `data/` 用于论文、向量索引和缓存;聊天数据库不写入源码目录,默认放在操作系统用户数据目录。Windows 使用 `platformdirs.user_data_dir("AcademicAgent", appauthor=False)` 得到 `%LOCALAPPDATA%\\AcademicAgent\\sessions.db`。

---

## 3. 技术栈

### 3.1 核心依赖

| 用途 | 技术 | 说明 |
|------|------|------|
| GUI 框架 | **PyQt6** | 成熟、文档全;Qt 6.4+ 支持 markdown 渲染 |
| PDF 解析/渲染 | **PyMuPDF (fitz)** | 渲染页面为图片 + `get_text("dict")` 抽块,坐标天然同源对齐 |
| 大模型 API | **openai SDK** | DeepSeek / OpenAI 通用(仅 `base_url` 不同),兼容性最好 |
| 本地 Embedding | **BGE-M3 + sentence-transformers** | GPU 本地运行,适合中文问题检索英文论文;1024 维稠密向量 |
| 向量检索 | **FAISS + SQLite** | SQLite 保存论文/块/向量真值,FAISS 是可校验、可重建的检索缓存 |
| 会话持久化 | **SQLite + platformdirs** | 保存聊天记录;SQLite 使用 Python 标准库,platformdirs 定位用户数据目录 |
| UI 美化 | **QSS 样式表** | 深色主题;图标可用 QtAwesome(免费图标字体) |
| Web 搜索 | **Tavily API**(推荐)/ DuckDuckGo / SearXNG(自建) | Tavily 专为 LLM 设计、有免费额度、返回结构化摘要;DuckDuckGo 免费但稳定性/速率受限;SearXNG 无隐私依赖需自部署 |
| 可选导出 | **pdf2zh** | 仅在需要导出整篇双语 PDF 时调用 |

### 3.2 模型方案

| 用途 | 建议模型 | 理由 |
|------|---------|------|
| 划段翻译 | `deepseek-chat` | 便宜、速度快,翻译任务用不上顶级模型 |
| 对话/总结 | DeepSeek 或 `gpt-4o` | 质量优先,用户可切换 |
| Embedding | 本地 `BAAI/bge-m3` | 多语言长文本检索;当前 RTX 5060 Ti 使用 CUDA 加速 |

> **关键设计**:模型访问统一封装。配置只需 `base_url` / `api_key` / `model` 三个字段,DeepSeek 与 OpenAI 走同一套 SDK 代码。

### 3.3 Python 环境

- Python 3.11+(建议 3.11,与 PyQt6/PyMuPDF 兼容性最好)
- `uv` 或 `venv` 管理虚拟环境
- requirements.txt 固定依赖

---

## 4. 核心数据模型

**块(Block)是这个项目的心脏**,GUI 和 RAG 共用:

```python
@dataclass
class Block:
    page: int                 # 页码
    bbox: tuple[float, ...]   # (x0, y0, x1, y1) PDF 坐标系
    text: str                 # 原文
    translation: str | None   # 译文(翻译后填充)
    kind: str                 # 'text' | 'formula' | 'title' | 'figure' ...
    order: int                # 栏内阅读顺序
```

**论文(Paper)记录**:

```python
@dataclass
class Paper:
    paper_id: str             # 唯一 ID(uuid 或 哈希)
    file_path: str
    title: str
    added_at: datetime
    blocks: list[Block]       # 全文分块(持久化到本地缓存)
```

**双语阅读页面数据流**:

```
打开 PDF
  → PDFParser 抽块(get_text("dict") + 按栏排序)
  → 渲染每页为 pixmap → 显示于左侧图片
  → 用户点击某块 / 翻到某页
  → 该块 text 调 Translator → 填 translation
  → 右侧显示 (原文 → 译文) 列表,左侧画高亮框
```

---

## 5. 关键实现方案

### 5.1 双语展示(PyMuPDF 抽块 + 原文图片)

```
1. 渲染:page.get_pixmap(dpi=150) → QImage → QLabel/QGraphicsView
   (渲染像素坐标 与 get_text 的 bbox 出自同一坐标系,天然对齐)
2. 抽块:page.get_text("dict") → blocks(含 bbox + text)
3. 双栏处理:按块 bbox 的 x 中心分左右栏,栏内按 y 排序
4. 块交互:鼠标点击坐标 → 换算回 PDF 坐标 → 找到包含该点的块
   → 左侧在 bbox 处画高亮框 + 右侧显示该块译文
5. 公式块:kind='formula' 的块跳过翻译,右侧标注"公式(见原文)"
6. 阅读视图:支持适应页面、缩放按钮、Ctrl+滚轮缩放;放大后使用水平/垂直滚动条浏览
```

> **为什么公式不会乱**:原文以渲染图片原样显示,任何区块(公式/图表/双栏)都不被重新排版,只作为背景;右侧仅展示翻译后的文字。

### 5.2 RAG 论文库

```
注册论文
  → 复用 PDFParser 的分块结果(一份数据两用,D5)
  → BGE-M3 对每块文本生成 1024 维归一化 embedding
  → SQLite 保存论文/块/bbox/embedding
  → FAISS IndexIDMap2 + IndexFlatIP 保存可重建索引
检索
  → 用户问题 embedding → FAISS top-5 → 返回相关块(论文标题 + 页码)
  → 将 Top 5 段落发送给配置的 LLM,生成带 [来源N] 引用的回答
```

> 分块粒度:标题/段落级(沿用 GUI 的块),不做按字符硬切。论文由用户在文件菜单中手动加入;索引在后台线程建立,避免阻塞 GUI。FAISS 文件损坏或 ID 不一致时从 SQLite 自动重建。

### 5.3 Agent 引擎(原生 OpenAI tools)

```python
# 核心循环(ReAct 模式):
while True:
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=TOOL_SCHEMAS,          # 工具定义
    )
    msg = resp.choices[0].message
    if not msg.tool_calls:           # 模型不再调工具 → 对话结束
        break
    messages.append(msg)
    for call in msg.tool_calls:      # 执行每个工具
        result = execute_tool(call)  # 分发到 search_papers 等
        messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
```

**工具清单(v1)**:

| 工具 | 功能 | 输入 |
|------|------|------|
| `search_papers(query)` | 检索论文库,返回相关论文段落(带引用) | 查询串 |
| `get_paper_summary(paper_id)` | 生成指定论文的摘要 | 论文 ID |
| `extract_key_points(paper_id)` | 提炼要点 / 术语表 | 论文 ID |
| `translate_text(text)` | 划段翻译(对话内翻译) | 文本 |
| `web_search(query)` | 实时搜索互联网,返回带链接的结构化摘要 | 查询串 |

> 上述工具全部通过**技能注册表**加载(见 5.5),新增技能自动出现在 `tools=[]` 中,由模型按需调用。

### 5.4 Codex 风格 UI

- **布局**:`QMainWindow` + `QSplitter`,左侧 PDF 阅读区,右侧停靠 `QTextEdit/QTextBrowser`(对话)
- **深色主题**:全局 QSS(背景 `#1e1e1e` 系、卡片式容器、圆角、扁平按钮)
- **PDF 显示**:默认适合宽度，也支持适合整页和实际大小；依据画布尺寸与屏幕 DPR 动态渲染，缩放预览使用平滑插值并在 120 ms 防抖后重渲染；单页受 600 DPI 与 2,000 万像素双重限制
- **悬浮翻页**:阅读区左右边缘按需淡入圆形翻页按钮，首页/末页自动隐藏无效方向；悬浮按钮转发滚轮事件，避免打断页面滚动
- **译文滚动**:译文列表采用逐像素滚动；传统鼠标滚轮使用 150 ms 缓动并累计连续输入，触控板保持原生像素滚动
- **消息呈现**:`QTextBrowser` 使用 `markdown-it-py` 将 CommonMark 转为安全 HTML；用户气泡右对齐，助手气泡左对齐，支持标题、列表、引用、代码块和表格，禁用原始 HTML
- **设置页**:`QDialog` + `QFormLayout`,模型/base_url/api_key 持久化到本地 JSON

> ⚠️ **顺序提醒**:先功能骨架(默认样式),再打磨美观;避免过早陷入样式调整。

### 5.5 Skills 扩展体系

**核心思想**:技能 = 一个自描述的文件夹,启动时扫描即注册,新增能力不用改核心代码。

```python
# 技能目录结构
skills/
├── web_search/
│   ├── SKILL.md          # 自描述:name / description / 输入 schema
│   └── skill.py          # run(args) 实现
└── paper_summary/
    ├── SKILL.md
    └── skill.py

# 注册表加载逻辑(启动时执行一次)
def load_skills(skills_dir: Path) -> list[Skill]:
    skills = []
    for folder in skills_dir.iterdir():
        meta = parse_skill_md(folder / "SKILL.md")   # 读自描述
        impl = import_skill(folder / "skill.py")      # 加载实现
        skills.append(Skill(**meta, run=impl.run))
    return skills

# Agent 启动时:
tools = [s.to_tool_schema() for s in load_skills("skills/")]
```

**添加一个新技能的流程**:
1. 新建 `skills/<技能名>/` 文件夹
2. 写 `SKILL.md`(名字、描述、输入参数)——**描述写得好坏直接决定模型何时调用它**
3. 写 `skill.py` 实现 `run(args)`
4. 重启应用,自动注册进 tools

**两个层级**:

| 层级 | 说明 | 复杂度 |
|------|------|--------|
| **简单级(推荐先做)** | 技能 = 一个 tool,模型 function-calling 调用 | ★ |
| 进阶级(后续) | 技能 = 指令包 + 工具(把说明注入系统提示,如 Claude Code 风格) | ★★★ |

**Web 搜索服务商选择**:

| 服务 | 优点 | 缺点 |
|------|------|------|
| **Tavily** | 专为 LLM 设计,返回结构化摘要,有免费额度,接 API 5 分钟 | 免费额度有限 |
| DuckDuckGo | 免费无需 key | 不稳定、速率受限、返回非结构化 |
| SearXNG(自建) | 无第三方依赖、隐私好 | 需自己部署一个实例 |

### 5.6 会话持久化与记忆边界

#### 5.6.1 两种记忆

- **短期记忆**:当前会话的 `messages` 列表,用于本轮 Agent tools 循环。
- **持久化记忆**:`SessionStore` 写入 SQLite,保存会话列表和完整消息,应用重启后恢复短期上下文。

论文库/RAG 是论文知识检索,不等同于聊天记忆;第一版不自动提取用户画像或跨会话语义记忆。

#### 5.6.2 数据模型

```sql
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    paper_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE messages (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    role TEXT NOT NULL,          -- system/user/assistant/tool
    content TEXT,
    tool_calls_json TEXT,
    metadata_json TEXT,          -- 选中段落等消息附件
    created_at TEXT NOT NULL
);
```

`SessionStore` 启动时创建数据库和索引,并为旧数据库自动补充 `metadata_json`;每条用户、助手或工具消息成功写入后再更新 `updated_at`。恢复会话时按 `created_at` 排序加载,再交给 Agent 引擎做上下文裁剪。

#### 5.6.3 上下文裁剪

当历史消息超过模型上下文窗口时,保留系统提示、论文上下文和最近若干轮消息;更早消息压缩为一条会话摘要。摘要属于会话数据,同样持久化,不可替代原始消息记录。

#### 5.6.4 最小交互

采用三栏布局:最左侧固定显示最近会话,中间显示 PDF 原文,右侧在译文与对话间切换。会话栏不放置实体操作按钮,在该区域右键弹出新建/重命名/删除菜单。启动应用 → 点击左侧历史会话恢复 → 继续发送消息。删除会话只删除聊天记录,不删除论文库文件。

选中 PDF 或译文列表中的文本块时,继续触发原有逐块翻译,并在对话输入框上方生成可移除的段落附件。发送问题时先快照该段原文、已有译文、论文标题、页码和 bbox,保存到用户消息的 `metadata_json`;本轮只使用选中段落,跳过 Top 5 RAG 和当前论文 32000 字符回退上下文。历史消息重新加载后仍显示当时引用的段落。

---

### P4 实现说明

当前 P4 使用 `app/agent/agent_loop.py` 执行最多 6 轮原生 OpenAI-compatible tool calling，
`app/agent/registry.py` 自动扫描 `app/skills/<name>/SKILL.md` 与 `skill.py`。内置技能包括
`search_papers`、`get_paper_summary`、`extract_key_points`、`translate_text` 和 `web_search`。
工具异常会作为 tool 结果返回模型，工具名称、参数和结果写入会话的 `tool_calls_json`。
新增技能只需要添加一个自描述目录，不需要修改 Agent 核心代码。

### P5 实现说明

当前 P5 使用独立的 `app/ui/theme.py` 管理中性石墨色 QSS，并通过 QtAwesome
提供工具栏、页码控制、标签页和操作按钮图标；QtAwesome 字体不可用时自动回退到
Qt 原生图标。主界面保持会话 / PDF / 译文与对话三栏结构，左侧会话的新建、重命名
和删除仍只在右键菜单出现；工具栏按钮或 `Ctrl+B` 可折叠并恢复最近对话栏。对话输入
使用一体化 composer，将输入、响应状态和发送操作放在同一视觉区域。

`app/ui/settings_dialog.py` 支持 DeepSeek、OpenAI 和自定义 OpenAI-compatible
服务，可配置模型 ID、Base URL、API key、超时与 Tavily key。设置保存到
`%LOCALAPPDATA%\AcademicAgent\settings.json`，并立即重建翻译、问答和 Agent
客户端，不重新加载当前 PDF、论文数据库、BGE-M3 或 FAISS 索引。JSON 配置优先于
`.env`，配置损坏时自动回退到环境变量。

资源生命周期由主窗口统一收口：完成的 `QThread` 通过 `deleteLater()` 释放，退出时若
存在后台任务则等待其结束后自动关闭；随后关闭 LLM HTTP client、卸载 BGE-M3、清空
CUDA cache，并释放内存中的 FAISS 索引。删除会话或论文后执行 SQLite `VACUUM`（存在
空闲页时）与 WAL truncate，使数据库磁盘空间实际回收。Hugging Face 下载缓存不随退出
删除，避免每次启动重新下载模型。
## 6. 开发计划

| 阶段 | 内容 | 交付物 | 难度 | 预计周期 |
|------|------|--------|------|---------|
| **P0** | 环境搭建 + **验证核心**:打开 PDF → 渲染 → 抽块 → 点块高亮 | 原型可运行 | ★★ | 1~2 周 |
| **P1** | 双语展示:逐块翻译 + 右侧译文列表 | 基础阅读器 | ★ | 数天 |
| **P2（已完成）** | 对话面板:接入 LLM + SQLite 会话持久化,"问这篇论文"跑通(无工具) | 可跨天恢复的对话阅读器 | ★★ | 1~1.5 周 |
| **P3（已完成）** | 论文库 + RAG:BGE-M3 + SQLite + FAISS + 跨论文引用 | 论文库雏形 | ★★★ | 2~3 周 |
| **P3.5（已完成）** | Codex 式选中段落附件 + 翻译 + 局部问答 + 消息持久化 | 段落精读工作流 | ★★ | 数天 |
| **P4（已完成）** | 技能注册表 + Agent 工具循环:`web_search` / 总结 / 要点 / 术语表 | 完整 Agent | ★★ | 1~2 周 |
| **P5（已完成）** | Codex 风格 UI 打磨 + 设置页 + 配置持久化 | 可用成品 | ★★ | 1~2 周 |
| **P6(可选)** | 集成 pdf2zh 导出双语 PDF | 附加导出 | — | 1 周 |

**里程碑**:P3 完成 = 从"带 GUI 的翻译器"升级为"真正的文献 Agent"。

### 6.1 每个阶段的验证标准

- **P0**:打开任一数字版 PDF,能渲染显示;点击段落在原图对应位置出现高亮框。
- **P1**:右侧能看到逐段"原文→译文",翻译可配置模型。
- **P2**:右侧对话能回答"这篇论文主要讲什么";关闭并重启应用后可从历史会话继续对话。
- **P3**:跨论文检索能返回带引用的相关段落。
- **P3.5**:选中任一文本块后可翻译并作为附件提问;重启后消息仍保留段落来源。
- **P4**:agent 能自主决定调用本地检索、论文证据、翻译和实时搜索工具完成"总结我的方向相关论文"。
- **P5**:深色 Codex 风格界面 + 设置页可切换 DeepSeek/OpenAI。

---

## 7. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 扫描版 PDF 无法抽取文字 | 划块/翻译失效 | v1 明确不支持,UI 提示;后续独立 OCR 模块(MinerU) |
| 双栏/复杂排版抽块顺序乱 | 译文顺序错乱 | 按 bbox 的 x 坐标分栏排序;图表块按 kind 过滤 |
| 公式以杂乱文本形式抽到 | 译文含乱码公式 | 公式块跳过翻译,右侧标注"见原文" |
| Windows 高 DPI 下坐标偏移 | 高亮框错位 | 统一用 devicePixelRatio 换算;先在 100% 缩放调试 |
| embedding 模型体积大 | 首次加载慢 | 首启下载缓存;论文库规模小,本地模型足够 |
| 长文档翻译成本 | token 消耗 | 仅翻译用户查看/选中的块,不做全文一次翻译 |
| 聊天数据库损坏或误删 | 历史会话丢失 | SQLite 开启 WAL;定期复制数据库到 `data/backups/`;删除会话前二次确认 |
| 历史过长导致上下文超限 | 请求失败或成本升高 | 按 5.6.3 规则裁剪并持久化摘要;原始消息仍保留在数据库 |
| 本地聊天记录包含敏感研究内容 | 隐私泄露 | 默认仅本机存储;设置页提供数据目录和“清空会话”入口;不上传聊天数据库 |
| 外部 LLM 请求包含论文内容 | 未公开论文内容被发送到服务商 | 附加选中段落时只发送该段原文、已有译文、标题和页码;普通问答最多发送 Top 5 检索段落,当前论文未入库时可使用总计不超过 32000 字符的回退上下文;不上传原始 PDF、论文库数据库或 FAISS 索引 |

---

## 8. 学习路线对应关系(面向作者)

| 项目环节 | 对应学习目标 |
|---------|------------|
| 原生 tools 循环 | 理解 ReAct agent 本质(不依赖框架) |
| PDF 抽块 + bbox 坐标 | 掌握 PyMuPDF 与图像/坐标换算 |
| RAG(embedding + FAISS) | 掌握检索增强的核心机制 |
| PyQt6 布局 + QSS | 桌面 GUI 工程化 |
| 统一模型层封装 | 多厂商 API 抽象(开放 API 设计) |
| 技能注册表 + web_search | 可插拔工具系统设计与实时信息获取 |

---

## 9. 未来扩展(不在 v1)

- 扫描版 PDF OCR(MinerU / pix2tex 公式识别)
- 划词翻译(词级选区,UI 打磨后迭代)
- 术语库 / 用户笔记体系
- 导出双语 PDF(pdf2zh 集成)
- 多模型对比翻译 / 翻译记忆缓存
- 论文之间的关联图谱(引用关系)

---

## 10. 待定问题

- [x] 论文库存储位置:`%LOCALAPPDATA%/AcademicAgent/`
- [x] 向量库持久化(FAISS 索引存盘,校验失败时从 SQLite 重建)
- [ ] 翻译触发策略(点击块时翻译 / 预加载前几页 / 全文后台翻译)
- [x] embedding 模型选型:`BAAI/bge-m3` + CUDA
- [ ] Web 搜索服务商选型(Tavily 免费额度 / DuckDuckGo 免费不稳 / SearXNG 自部署)
- [ ] 会话保留策略(永久保存 / 按时间清理 / 用户手动清理)
- [ ] 会话数据库备份与导出格式(JSON/Markdown)
