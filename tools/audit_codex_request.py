"""Capture a synthetic Codex request locally, with no credentials or model call.

Usage: python tools/audit_codex_request.py NATIVE_CODEX_EXE [MODEL]
Retains the request in a new temporary folder; prints only shape and sizes.
"""
import gzip
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rc_engine.codex_cli import build_argv, write_text_catalog
from rc_engine.cli_runtime import subscription_env


def main():
    work = Path(tempfile.mkdtemp(prefix="rc-codex-wire-audit-"))
    (work / "home").mkdir()
    (work / "instructions.txt").write_text("Return the requested text only.", encoding="utf-8")
    captures = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if self.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            captures.append(json.loads(raw))
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"Offline audit: no model invoked"}}')

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = subscription_env()
    # A fresh home contains no saved login. Never send any production auth.
    env["CODEX_HOME"] = str(work / "home")
    write_text_catalog(sys.argv[1], work)
    model = sys.argv[2] if len(sys.argv) > 2 else "gpt-6-astra"
    args = build_argv(sys.argv[1], model, "low", work)
    overrides = {
        "model_provider": "offline_audit",
        "model_providers.offline_audit.name": "Local synthetic audit",
        "model_providers.offline_audit.base_url": f"http://127.0.0.1:{server.server_port}/v1",
        "model_providers.offline_audit.wire_api": "responses",
        "model_providers.offline_audit.requires_openai_auth": False,
        "model_providers.offline_audit.request_max_retries": 0,
        "model_providers.offline_audit.stream_max_retries": 0,
        "features.enable_request_compression": False,
    }
    # Remove subscription-only login constraint for the credential-free stub.
    pos = args.index('forced_login_method="chatgpt"')
    del args[pos - 1:pos + 1]
    for key, value in overrides.items():
        args[-1:-1] = ["-c", f"{key}={json.dumps(value)}"]
    try:
        result = subprocess.run(args, input="Return OK.", cwd=work, env=env,
                                text=True, encoding="utf-8", capture_output=True, timeout=45)
    finally:
        server.shutdown()
        server.server_close()
    (work / "diagnostics.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
    for i, request in enumerate(captures):
        (work / f"request-{i}.json").write_text(json.dumps(request, indent=2), encoding="utf-8")
        print(json.dumps({"keys": list(request), "instructions_chars": len(request.get("instructions", "")),
                          "tools": [t.get("name", t.get("type")) for t in request.get("tools", [])],
                          "embedded_tools": [t.get("name", t.get("type")) for m in request.get("input", []) for t in m.get("tools", [])],
                          "tool_chars": len(json.dumps(request.get("tools", []))),
                          "input_chars": len(json.dumps(request.get("input", []))),
                          "messages": [{"role": m.get("role"), "chars": len(json.dumps(m))}
                                       for m in request.get("input", [])]}))
        tools = request.get("tools", []) + [t for m in request.get("input", []) for t in m.get("tools", [])]
        texts = [c.get("text", "") for m in request.get("input", []) for c in m.get("content", [])]
        assert not tools, "Unexpected tool schema in text-only request"
        assert not any(tag in "\n".join(texts) for tag in
                       ("<skills_instructions>", "<multi_agent_role>", "<collaboration_mode>", "<environment_context>"))
    print(f"Captured {len(captures)} requests; retained at {work}")
    if not captures:
        print(result.stdout[-1500:] + result.stderr[-1500:])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
