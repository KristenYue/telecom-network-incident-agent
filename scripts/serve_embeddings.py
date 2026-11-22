"""Local CPU BGE embeddings. Install .[retrieval] or use a prepared Python env."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--model", default="BAAI/bge-small-zh-v1.5")
    parser.add_argument("--allow-download", action="store_true")
    args = parser.parse_args()
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(args.model, device="cpu", local_files_only=not args.allow_download)
    lock = Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if self.path != "/embed" or not 0 < length <= 200_000:
                    raise ValueError("invalid request")
                texts = json.loads(self.rfile.read(length))["texts"]
                if not isinstance(texts, list) or not 1 <= len(texts) <= 128:
                    raise ValueError("invalid batch")
                if any(not isinstance(t, str) or not 0 < len(t) <= 8000 for t in texts):
                    raise ValueError("invalid text")
                with lock:
                    vectors = model.encode(texts, normalize_embeddings=True).tolist()
                body = json.dumps({"model": args.model, "vectors": vectors}).encode()
                self.send_response(200)
            except (ValueError, KeyError, TypeError):
                body = b'{"error":"invalid embedding request"}'
                self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    print(f"CPU embedding service http://127.0.0.1:{args.port}/embed", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
