"""Actual native ONNX embeddings feeding version-filtered project knowledge search."""
import argparse
import json
from pathlib import Path

from edge_ai_sdk.embedding import NativeEmbedder
from telecom_incident_agent.knowledge import KnowledgeIndex


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--tokenizer", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    embedder = NativeEmbedder(args.model, args.tokenizer)
    index = KnowledgeIndex.from_runbooks(embedder=embedder)
    queries = ["BGP邻居会话断开", "光模块接收功率过低", "设备CPU负载持续过高"]
    results = [{"query": q, "retrieval": index.search(q, mode="hybrid")} for q in queries]
    report = {"mode": "native_onnx_retrieval", "model": "BAAI/bge-small-zh-v1.5",
              "corpus": "project_authored_runbooks", "results": results,
              "live_llm": False, "independent_accuracy_benchmark": False}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"queries": len(results), "output": args.output}))


if __name__ == "__main__":
    main()
