---
name: extract_key_points
description: 获取论文证据并按 key_points 或 terminology 模式提炼关键贡献、方法、结论或术语表。
parameters:
  type: object
  properties:
    paper_id:
      type: string
      description: 论文库中的论文 ID、标题或文件路径
    mode:
      type: string
      enum: [key_points, terminology]
      description: 输出关键要点或术语表
  required: [paper_id]
  additionalProperties: false
---

提供论文证据。
