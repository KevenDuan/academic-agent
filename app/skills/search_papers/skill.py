from __future__ import annotations


def run(args, context):
    query = str(args.get("query") or "").strip()
    if not query:
        return "检索问题不能为空。"
    results = context.rag_engine.search(query, top_k=5)
    return context.rag_engine.format_context(results) or "本地论文库没有找到相关段落。"
