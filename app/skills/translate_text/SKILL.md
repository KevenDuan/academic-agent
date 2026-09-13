---
name: translate_text
description: 将一段科研文本翻译成简体中文，只返回译文。
parameters:
  type: object
  properties:
    text:
      type: string
      description: 待翻译文本
  required: [text]
  additionalProperties: false
---

翻译短文本。
