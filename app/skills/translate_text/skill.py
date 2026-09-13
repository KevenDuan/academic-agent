from __future__ import annotations


def run(args, context):
    text = str(args.get("text") or "").strip()
    if not text:
        return "待翻译文本不能为空。"
    return context.translator.translate_text(text)
