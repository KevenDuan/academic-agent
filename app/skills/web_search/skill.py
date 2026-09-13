from __future__ import annotations

import json
import os


def run(args, context):
    query = str(args.get("query") or "").strip()
    if not query:
        return "搜索问题不能为空。"
    api_key = os.getenv("TVLY_API_KEY") or os.getenv("TAVILY_API_KEY")
    if not api_key:
        return "未配置 TVLY_API_KEY，无法进行实时网络搜索。"
    from tavily import TavilyClient

    response = TavilyClient(api_key=api_key).search(
        query=query,
        search_depth="advanced",
        max_results=5,
        include_answer=True,
    )
    return json.dumps(response, ensure_ascii=False)
