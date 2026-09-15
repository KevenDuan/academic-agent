# AcademicAgent

academic agent is a local desktop AI research assistant designed for researchers.

It combines bilingual PDF reading, block-level translation, paper library RAG,
persistent conversations, and tool-using LLM workflows in a PyQt6 desktop application.

## Features

- Bilingual PDF reading
- Block-level text extraction and translation
- Local paper library with FAISS-based RAG
- Persistent chat sessions
- Markdown chat with distinct user and assistant bubbles
- OpenAI and DeepSeek compatible APIs
- Tool-calling agent loop
- Pluggable skills system
- Optional web search

## Current status

P0 through P5 are implemented: open a digital PDF, render pages, extract text
blocks with PDF coordinates, request block-level Chinese translations, ask
focused questions about a selected passage, and use an OpenAI-compatible agent
to call local-paper and web-search tools. Chat sessions, tool calls, and paper
metadata are stored locally in SQLite; BGE-M3 and FAISS provide GPU-accelerated
multilingual retrieval with title and page citations.
Selecting a PDF block also creates a removable chat attachment for focused
questions about that passage.

## Model settings

Open `应用 → 设置` to switch between DeepSeek, OpenAI, or another
OpenAI-compatible endpoint. Model ID, Base URL, API key, request timeout, and
Tavily key can be edited without restarting the application. The saved values
take precedence over `.env` on the next launch and are stored locally in
`%LOCALAPPDATA%\AcademicAgent\settings.json`.

The API keys in this file are local plaintext credentials. Keep the file out of
version control and restrict access to your Windows account.

When a conversation or indexed paper is deleted, AcademicAgent compacts its
SQLite database and truncates the WAL so the released disk space is returned to
the operating system. Closing the application waits for active workers, closes
LLM connections, and releases the in-memory FAISS index and BGE-M3 model. The
downloaded Hugging Face model cache is intentionally retained for reuse.

## Run locally

```powershell
conda activate academic_agent
python -m pip install -r requirements.txt
python -m pip install --force-reinstall --no-deps -r requirements-cuda.txt
python -m app.main data/Unet.pdf
```

Without a model key, PDF reading, block extraction, page navigation, and block
highlighting still work. To enable translation, copy `.env.example` to `.env`
and configure `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_ID`, and `LLM_TIMEOUT`.
The equivalent `OPENAI_*` variable names remain supported as fallbacks.

The interface uses three columns: recent conversations on the left, the PDF in
the center, and translation/chat tabs on the right. Right-click the conversation
sidebar to create, rename, or delete a session. The local database is stored
in the operating system's AcademicAgent user data directory; deleting a
conversation never deletes its PDF file.

The PDF reader defaults to fit-width mode and also provides fit-page and actual-
size modes. Pages are rendered for the current display size and device pixel
ratio, then refreshed after zooming or resizing. Smooth preview scaling keeps
interaction responsive while a DPI and pixel cap limits peak memory use.
Moving the pointer to either side of the PDF reveals compact circular page
controls. Unavailable directions stay hidden on the first and last pages, and
the mouse wheel continues scrolling while the pointer is over a control.

Chat messages render CommonMark Markdown, including headings, emphasis, lists,
quotes, fenced code blocks, tables, and links. User turns appear on the right
and Academic Agent turns on the left. Raw HTML in messages is displayed as text
instead of being interpreted by the interface.

## Selected-passage questions

Select a text block in the PDF or translation list to translate it and attach
it to the chat composer. The next question sends the selected original text,
its available Chinese translation, paper title, and page number to the LLM.
For that turn, AcademicAgent skips whole-paper fallback context and paper-library
retrieval so the answer stays focused on the selected passage. The attachment is
stored with the user message and remains visible after reopening the session.

## Paper library and RAG

Open a PDF and select `文件 → 将当前论文加入论文库`. Indexing runs in the
background. The first use downloads `BAAI/bge-m3`; later runs use the local
Hugging Face cache. `文件 → 管理论文库` opens or removes indexed papers without
deleting the original PDF.

For each question, AcademicAgent retrieves at most five relevant blocks across
the library and sends their text, paper title, and page number to the configured
LLM. Answers are prompted to retain `[来源N]` citations. Paper metadata and
embeddings are stored in `%LOCALAPPDATA%/AcademicAgent/papers.db`; the rebuildable
FAISS cache is `%LOCALAPPDATA%/AcademicAgent/papers.faiss`.

## Agent tools (P4)

The native tool loop loads skills from `app/skills/<name>/SKILL.md` and
`skill.py` at startup. The bundled tools are `search_papers`,
`get_paper_summary`, `extract_key_points`, `translate_text`, and `web_search`.
The model can call several tools in one request, with a six-round safety limit;
tool results are saved in the local session database. `web_search` requires
`TVLY_API_KEY` (or `TAVILY_API_KEY`) in `.env`.

## Desktop interface (P5)

The production interface uses a neutral graphite theme, a compact icon toolbar,
and a stable three-column workspace inspired by Codex. PDF controls, paper
library actions, model settings, selected-passage context, and conversation
states share one visual system. Conversation management remains available only
from the left sidebar context menu. Use the first toolbar button or `Ctrl+B` to
collapse and restore the recent-conversation sidebar.

Run the local checks with:

```powershell
python -m unittest discover -s tests -v
```

## PDF view controls

- `+` / `−`: zoom in or out
- `适应`: fit the page to the reading area
- `Ctrl + mouse wheel`: zoom around the cursor
- Mouse wheel: scroll vertically; `Shift + mouse wheel`: scroll horizontally
- The zoomed page uses the right and bottom scrollbars for navigation
