---
name: get_paper_summary
description: 获取指定论文的原文证据，供模型生成结构化摘要。paper_id 应来自论文库目录。
parameters:
  type: object
  properties:
    paper_id:
      type: string
      description: 论文库中的论文 ID、标题或文件路径
  required: [paper_id]
  additionalProperties: false
---

提供论文证据。
