"""Per-task enrichment backend dispatch (issue #14).

All tests are offline: Claude is monkeypatched, Ollama HTTP is faked. No live
API or daemon calls.
"""
import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import ingest  # noqa: E402


# ── resolve_enrich: default is all-Claude, block deep-merges over it ──────────

def test_resolve_enrich_absent_block_is_all_claude():
    cfg = ingest.resolve_enrich({})
    assert set(cfg["tasks"]) == {"tagger", "rewrite", "merge", "glossary"}
    assert all(v == "claude" for v in cfg["tasks"].values())
    assert cfg["backends"]["claude"]["model"] == "claude-sonnet-4-6"


def test_resolve_enrich_partial_block_fills_gaps_with_claude():
    kb = {"enrich": {
        "backends": {"ollama": {"model": "qwen3:8b"}},
        "tasks": {"tagger": "ollama", "rewrite": "ollama", "glossary": "ollama"},
    }}
    cfg = ingest.resolve_enrich(kb)
    assert cfg["tasks"]["merge"] == "claude"        # unspecified → default
    assert cfg["tasks"]["tagger"] == "ollama"
    assert cfg["backends"]["ollama"]["model"] == "qwen3:8b"
    assert cfg["backends"]["claude"]["model"] == "claude-sonnet-4-6"  # kept


# ── enrich_call: routes each task to its configured backend ──────────────────

def _hybrid_cfg():
    return ingest.resolve_enrich({"enrich": {
        "backends": {"ollama": {"model": "qwen3:8b"}},
        "tasks": {"tagger": "ollama", "rewrite": "ollama",
                  "merge": "claude", "glossary": "ollama"},
    }})


def test_enrich_call_routes_merge_to_claude(monkeypatch):
    seen = {}
    monkeypatch.setattr(ingest, "call_claude",
                        lambda s, u, model, label: seen.update(model=model) or "CLAUDE")
    monkeypatch.setattr(ingest, "call_ollama",
                        lambda *a, **k: pytest.fail("merge must not hit ollama"))
    out = ingest.enrich_call("merge", "sys", "usr", _hybrid_cfg())
    assert out == "CLAUDE"
    assert seen["model"] == "claude-sonnet-4-6"


def test_enrich_call_routes_tagger_to_ollama(monkeypatch):
    seen = {}
    monkeypatch.setattr(ingest, "call_ollama",
                        lambda s, u, model, **k: seen.update(model=model) or "OLLAMA")
    monkeypatch.setattr(ingest, "call_claude",
                        lambda *a, **k: pytest.fail("tagger must not hit claude"))
    out = ingest.enrich_call("tagger", "sys", "usr", _hybrid_cfg())
    assert out == "OLLAMA"
    assert seen["model"] == "qwen3:8b"


def test_enrich_call_unknown_backend_raises():
    cfg = ingest.resolve_enrich({"enrich": {"tasks": {"tagger": "gpt5"}}})
    with pytest.raises(RuntimeError, match="unknown backend 'gpt5'"):
        ingest.enrich_call("tagger", "s", "u", cfg)


# ── call_ollama: payload shape, think-stripping, fail-loud, ctx guard ─────────

class _FakeResp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_call_ollama_builds_chat_payload_and_strips_think(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data)
        return _FakeResp(json.dumps(
            {"message": {"content": "<think>reasoning</think>ANSWER"}}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    out = ingest.call_ollama("sys", "usr", model="qwen3:8b", label="tagger")
    assert out == "ANSWER"                                   # <think> stripped
    assert captured["url"].endswith("/api/chat")
    assert captured["body"]["stream"] is False
    assert captured["body"]["think"] is False
    roles = [m["role"] for m in captured["body"]["messages"]]
    assert roles == ["system", "user"]


def test_call_ollama_unreachable_fails_loud(monkeypatch):
    def boom(req, timeout):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(RuntimeError, match="unreachable"):
        ingest.call_ollama("s", "u", model="qwen3:8b", label="rewrite")


def test_call_ollama_missing_model_http_error_fails_loud(monkeypatch):
    def boom(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {},
                                     io.BytesIO(b'{"error":"model not found"}'))
    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(RuntimeError, match="HTTP 404"):
        ingest.call_ollama("s", "u", model="absent", label="glossary")


def test_call_ollama_guards_against_silent_ctx_truncation():
    big = "x" * 40000        # ~10k tok, well over 70% of num_ctx=8192
    with pytest.raises(RuntimeError, match="num_ctx"):
        ingest.call_ollama("sys", big, model="qwen3:8b", num_ctx=8192, label="rewrite")
