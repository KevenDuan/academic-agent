---
name: web_search
description: 使用 Tavily 搜索互联网中的最新论文、方法和科研资讯，返回标题、摘要和链接。
parameters:
  type: object
  properties:
    query:
      type: string
      description: 要搜索的互联网问题或关键词
  required: [query]
  additionalProperties: false
---

实时网络搜索。
