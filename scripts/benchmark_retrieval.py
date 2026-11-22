"""Development comparison, not an independent production benchmark."""
import argparse
import hashlib
import json
import platform
import statistics
import time
from pathlib import Path

from telecom_incident_agent.knowledge import HTTPEmbedder, KnowledgeIndex

CASES = [
    ("设备端口显示down，怎样区分管理关闭与链路异常", "rb-interface-001"),
    ("接收光信号太弱，需要检查连接器和收发模块", "rb-optical-001"),
    ("传输错误大量增加，BER与CRC怎样关联", "rb-ber-001"),
    ("业务数据包丢失，哪里开始出现丢弃", "rb-loss-001"),
    ("业务访问忽快忽慢，逐跳定位延迟", "rb-latency-001"),
    ("带宽持续接近满载，该如何排查", "rb-util-001"),
    ("BGP对等体无法建立会话", "rb-bgp-001"),
    ("OSPF停留在邻接协商阶段，检查MTU和Hello", "rb-ospf-001"),
    ("同一前缀频繁撤销和重新发布", "rb-flap-001"),
    ("域名解析失败，上游服务连接不通", "rb-upstream-001"),
    ("CPU与内存占用持续异常", "rb-resource-001"),
    ("许多下游节点同时告警，先查共享上游", "rb-storm-001"),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--embedding-url")
    parser.add_argument("--output", default="docs/evidence/retrieval-development.json")
    args = parser.parse_args()
    index = KnowledgeIndex.from_runbooks(embedder=HTTPEmbedder(args.embedding_url) if args.embedding_url else None)
    report = {"scope": "12 project-authored development queries; synthetic runbook corpus; not held-out field data",
              "platform": platform.platform(), "query_sha256": hashlib.sha256(json.dumps(CASES).encode()).hexdigest(),
              "corpus_sha256": hashlib.sha256(json.dumps(index.chunks, sort_keys=True).encode()).hexdigest(),
              "modes": {}}
    for mode, rerank in [("bm25", False), ("dense", False), ("hybrid", False), ("hybrid", True)]:
        rows = []
        for query, expected in CASES:
            start = time.perf_counter()
            result = index.search(query, mode=mode, rerank=rerank)
            rows.append({"query": query, "expected": expected,
                         "retrieved": [r["document_id"] for r in result["results"]],
                         "latency_ms": round((time.perf_counter() - start) * 1000, 3),
                         "dense_status": result["dense_status"]})
        ranked = [row["retrieved"] for row in rows]
        report["modes"][mode + ("_rerank" if rerank else "")] = {
            "queries": len(rows), "hit_at_1": sum(bool(r) and r[0] == c[1] for r, c in zip(ranked, CASES)) / len(rows),
            "hit_at_5": sum(c[1] in r for r, c in zip(ranked, CASES)) / len(rows),
            "median_latency_ms": statistics.median(row["latency_ms"] for row in rows),
            "cold_first_query_ms": rows[0]["latency_ms"], "rows": rows,
        }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: {key: value for key, value in v.items() if key != "rows"}
                      for k, v in report["modes"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
