"""Version-filtered BM25/dense retrieval with stable, line-addressable citations.

Dense search is opt-in. An unavailable embedding service is reported, never
silently presented as successful semantic retrieval.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Protocol
from functools import lru_cache
from urllib.request import Request, build_opener

from .shelf_adapter import NoRedirect


def tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9_./-]+|[\u4e00-\u9fff]+", text.lower())
    result = []
    for word in words:
        if re.fullmatch(r"[\u4e00-\u9fff]+", word):
            result.extend(word)
            result.extend(word[i:i + 2] for i in range(len(word) - 1))
        else:
            result.append(word)
    return result


class Embedder(Protocol):
    def encode(self, texts: list[str]) -> list[list[float]]: ...


class HTTPEmbedder:
    """Uses a server-configured local/managed embedding endpoint, not user URLs."""
    def __init__(self, url: str, *, timeout: float = 15):
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            raise ValueError("invalid embedding endpoint")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("unencrypted embedding endpoint must be loopback")
        self.url, self.timeout = url, timeout

    def encode(self, texts):
        request = Request(self.url, json.dumps({"texts": texts}).encode(),
                          {"Content-Type": "application/json"})
        with build_opener(NoRedirect()).open(request, timeout=self.timeout) as response:
            data = json.loads(response.read(4_000_001))
        vectors = data["vectors"]
        if len(vectors) != len(texts) or not vectors:
            raise ValueError("embedding count mismatch")
        dimensions = len(vectors[0])
        if not dimensions or any(len(v) != dimensions for v in vectors):
            raise ValueError("embedding dimension mismatch")
        if any(not isinstance(x, (int, float)) or not math.isfinite(x) for v in vectors for x in v):
            raise ValueError("non-finite embedding")
        return vectors


def cosine(a, b):
    if len(a) != len(b):
        raise ValueError("embedding dimension mismatch")
    denominator = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
    return sum(x*y for x, y in zip(a, b)) / denominator if denominator else 0.0


class KnowledgeIndex:
    def __init__(self, documents: list[dict], *, embedder: Embedder | None = None,
                 chunk_lines: int = 6, overlap_lines: int = 1):
        if chunk_lines <= overlap_lines or overlap_lines < 0:
            raise ValueError("invalid chunk overlap")
        self.embedder = embedder
        self.chunks = []
        ids = set()
        for doc in documents:
            identity = (doc["document_id"], doc["version"], doc["device_family"])
            if identity in ids:
                raise ValueError("duplicate document revision")
            ids.add(identity)
            lines = doc["text"].splitlines()
            digest = hashlib.sha256(doc["text"].encode()).hexdigest()
            for start in range(0, len(lines), chunk_lines - overlap_lines):
                text = "\n".join(lines[start:start + chunk_lines]).strip()
                if not text:
                    continue
                self.chunks.append({
                    "document_id": doc["document_id"], "title": doc["title"],
                    "version": doc["version"], "device_family": doc["device_family"],
                    "fault_type": doc.get("fault_type"), "source": doc["source"],
                    "data_boundary": doc.get("data_boundary", "project_authored"),
                    "line_start": start + 1, "line_end": min(start + chunk_lines, len(lines)),
                    "sha256": digest, "text": text,
                    "chunk_id": f"{doc['document_id']}@{doc['version']}:{start + 1}",
                })
        self.counts = [Counter(tokens(c["title"] + " " + c["text"])) for c in self.chunks]
        self.lengths = [sum(c.values()) for c in self.counts]
        self.df = Counter(t for c in self.counts for t in c)
        self.average_length = sum(self.lengths) / max(1, len(self.lengths))
        self.vectors = None

    @classmethod
    def from_runbooks(cls, *, embedder=None, extra_documents=()):
        from .runbooks import RUNBOOKS
        documents = [{
            "document_id": r["runbook_id"], "title": r["title"], "version": r["version"],
            "device_family": r["device_family"], "fault_type": r["fault_type"],
            "source": "project://runbooks/" + r["runbook_id"],
            "data_boundary": "synthetic_runbook",
            "text": "\n".join([r["title"], " ".join(r["keywords"]), *r["steps"]]),
        } for r in RUNBOOKS]
        return cls(documents + list(extra_documents), embedder=embedder)

    @classmethod
    def from_json(cls, path: str | Path, **kwargs):
        return cls(json.loads(Path(path).read_text(encoding="utf-8")), **kwargs)

    def search(self, query: str, *, device_family=None, version=None, fault_type=None,
               top_k: int = 5, mode: str = "hybrid", rerank: bool = True):
        if mode not in {"bm25", "dense", "hybrid"} or not 1 <= top_k <= 20:
            raise ValueError("invalid retrieval settings")
        query_terms = tokens(query)
        if not query_terms or len(query) > 2000:
            raise ValueError("query must contain searchable text, at most 2000 characters")
        eligible = [i for i, c in enumerate(self.chunks)
                    if (not device_family or c["device_family"] == device_family)
                    and (not version or c["version"] == version)
                    and (not fault_type or c["fault_type"] == fault_type)]
        scores = {}
        for i in eligible:
            score = 0.0
            for term in set(query_terms):
                frequency = self.counts[i][term]
                if frequency:
                    idf = math.log(1 + (len(self.chunks) - self.df[term] + .5) / (self.df[term] + .5))
                    score += idf * frequency * 2.5 / (frequency + 1.5 * (
                        .25 + .75 * self.lengths[i] / max(self.average_length, 1)))
            if score > 0:
                scores[i] = score
        sparse = sorted(scores, key=lambda i: (-scores[i], self.chunks[i]["chunk_id"]))
        dense = []
        dense_status = "not_requested" if mode == "bm25" else "not_configured"
        if mode != "bm25" and self.embedder and eligible:
            try:
                if self.vectors is None:
                    self.vectors = self.embedder.encode([c["title"] + "\n" + c["text"] for c in self.chunks])
                    if len(self.vectors) != len(self.chunks):
                        self.vectors = None
                        raise ValueError("embedding count mismatch")
                q = self.embedder.encode([query])[0]
                dense_scores = {i: cosine(q, self.vectors[i]) for i in eligible}
                dense = sorted(eligible, key=lambda i: (-dense_scores[i], self.chunks[i]["chunk_id"]))
                dense_status = "available"
            except (OSError, ValueError, KeyError, TypeError, IndexError):
                dense_status = "unavailable"
        if mode == "dense" and dense_status != "available":
            return {"results": [], "dense_status": dense_status, "mode": mode,
                    "no_answer": True, "reranker": "none"}
        ranks = [sparse] if mode == "bm25" else [dense] if mode == "dense" else [sparse, dense]
        fused = {}
        for ranking in ranks:
            for rank, i in enumerate(ranking[:50], 1):
                fused[i] = fused.get(i, 0.0) + 1 / (60 + rank)
        # Explicit lexical reranker. This is not a neural cross-encoder.
        def rerank_score(i):
            coverage = len(set(query_terms) & self.counts[i].keys()) / len(set(query_terms))
            return fused[i] * (1 + .15 * coverage) if rerank else fused[i]
        ranked = sorted(fused, key=lambda i: (-rerank_score(i), self.chunks[i]["chunk_id"]))
        return {"results": [{**self.chunks[i], "score": round(rerank_score(i), 8)} for i in ranked[:top_k]],
                "dense_status": dense_status, "mode": mode, "no_answer": not ranked,
                "reranker": "lexical_coverage" if rerank else "none"}


@lru_cache(maxsize=1)
def default_index():
    import os
    endpoint = os.getenv("TELECOM_EMBEDDING_URL")
    corpus = os.getenv("TELECOM_KNOWLEDGE_JSON")
    embedder = HTTPEmbedder(endpoint) if endpoint else None
    return (KnowledgeIndex.from_json(corpus, embedder=embedder) if corpus else
            KnowledgeIndex.from_runbooks(embedder=embedder))
