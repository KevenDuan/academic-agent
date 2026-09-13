from __future__ import annotations


def run(args, context):
    mode = str(args.get("mode") or "key_points")
    evidence = context.rag_engine.paper_evidence(str(args.get("paper_id") or ""), max_chars=24000)
    return f"提炼模式：{mode}\n请只依据以下论文证据生成结果：\n{evidence}"
