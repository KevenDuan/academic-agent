# AcademicAgent

academic agent is a local desktop AI research assistant designed for researchers.

It combines bilingual PDF reading, block-level translation, paper library RAG,
persistent conversations, and tool-using LLM workflows in a PyQt6 desktop application.

## Features

- Bilingual PDF reading
- Block-level text extraction and translation
- Local paper library with FAISS-based RAG
- Persistent chat sessions
- OpenAI and DeepSeek compatible APIs
- Tool-calling agent loop
- Pluggable skills system
- Optional web search

## Current status

P0 through P3 are implemented: open a digital PDF, render pages, extract text
blocks with PDF coordinates, request block-level Chinese translations, and ask
an OpenAI-compatible model questions across a local paper library. Chat sessions
and paper metadata are stored locally in SQLite; BGE-M3 and FAISS provide
GPU-accelerated multilingual retrieval with title and page citations.
Selecting a PDF block also creates a removable chat attachment for focused
questions about that passage.

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
