---
name: search_papers
description: 在本地论文库中检索与问题最相关的论文段落，返回带论文标题、页码和来源编号的证据。
parameters:
  type: object
  properties:
    query:
      type: string
      description: 要检索的科研问题或关键词
  required: [query]
  additionalProperties: false
---

检索本地论文库。
