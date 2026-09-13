from __future__ import annotations


def run(args, context):
    return context.rag_engine.paper_evidence(str(args.get("paper_id") or ""), max_chars=24000)
