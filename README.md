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

P0 and P1 are implemented: open a digital PDF, render pages, extract text blocks
with PDF coordinates, click a block to highlight it, and request a block-level
Chinese translation through an OpenAI-compatible API.

## Run locally

```powershell
conda activate academic_agent
python -m pip install -r requirements.txt
python -m app.main data/Unet.pdf
```

Without a model key, PDF reading, block extraction, page navigation, and block
highlighting still work. To enable translation, copy `.env.example` to `.env`
and configure `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_ID`, and `LLM_TIMEOUT`.
The equivalent `OPENAI_*` variable names remain supported as fallbacks.

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
