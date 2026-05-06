import importlib


def _reload_module():
    import agent.langfuse_tracing as lf

    return importlib.reload(lf)


def test_get_langfuse_readiness_missing_required(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_PROTOCOL", raising=False)
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)

    lf = _reload_module()
    ready = lf.get_langfuse_readiness()

    assert ready["enabled"] is False
    assert ready["reason"] == "missing_langfuse_credentials"
    assert set(ready["langfuse"]["missing_required"]) == {
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
    }
    assert ready["otel"]["ready"] is False


def test_get_langfuse_readiness_when_configured(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://us.cloud.langfuse.com")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://us.cloud.langfuse.com/api/public/otel")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "Authorization=Basic abc")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "hermes-roscoe")

    lf = _reload_module()
    ready = lf.get_langfuse_readiness()

    assert ready["enabled"] is True
    assert ready["reason"] == "configured"
    assert ready["langfuse"]["missing_required"] == []
    assert ready["otel"]["ready"] is True


def test_is_langfuse_enabled_uses_readiness(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

    lf = _reload_module()
    assert lf.is_langfuse_enabled() is False

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    lf = _reload_module()
    assert lf.is_langfuse_enabled() is True


def test_set_current_trace_io_noop_when_disabled(monkeypatch):
    lf = _reload_module()
    monkeypatch.setattr(lf, "is_langfuse_enabled", lambda: False)

    lf.set_current_trace_io(input="hello", output="world")


def test_set_current_trace_io_calls_sdk_when_enabled(monkeypatch):
    lf = _reload_module()

    calls = {}

    class _FakeLangfuse:
        def get_current_trace_id(self):
            return "trace_123"

        def set_current_trace_io(self, *, input=None, output=None):
            calls["input"] = input
            calls["output"] = output

    monkeypatch.setattr(lf, "is_langfuse_enabled", lambda: True)
    monkeypatch.setattr(lf, "get_langfuse", lambda: _FakeLangfuse())

    lf.set_current_trace_io(input="in", output="out")

    assert calls == {"input": "in", "output": "out"}


def test_set_current_generation_output_noop_when_disabled(monkeypatch):
    lf = _reload_module()
    monkeypatch.setattr(lf, "is_langfuse_enabled", lambda: False)

    lf.set_current_generation_output("out")


def test_set_current_generation_output_calls_sdk_when_enabled(monkeypatch):
    lf = _reload_module()

    calls = {}

    class _FakeLangfuse:
        def update_current_generation(self, *, output=None):
            calls["output"] = output

    monkeypatch.setattr(lf, "is_langfuse_enabled", lambda: True)
    monkeypatch.setattr(lf, "get_langfuse", lambda: _FakeLangfuse())

    lf.set_current_generation_output("assistant output")

    assert calls == {"output": "assistant output"}


def test_set_current_trace_session_context_updates_current_span_metadata(monkeypatch):
    lf = _reload_module()

    calls = {}

    class _FakeLangfuse:
        def get_current_trace_id(self):
            return "trace_abc"

        def update_current_span(self, *, metadata=None, **kwargs):
            calls["metadata"] = metadata
            calls["kwargs"] = kwargs

    monkeypatch.setattr(lf, "is_langfuse_enabled", lambda: True)
    monkeypatch.setattr(lf, "get_langfuse", lambda: _FakeLangfuse())
    monkeypatch.setattr(lf, "get_session_env", lambda name, default="": {
        "HERMES_SESSION_KEY": "agent:main:slack:group:C0AGJKT10QM",
        "HERMES_SESSION_PLATFORM": "slack",
        "HERMES_SESSION_CHAT_ID": "C0AGJKT10QM",
        "HERMES_SESSION_THREAD_ID": "",
        "HERMES_SESSION_USER_ID": "U123",
    }.get(name, default))
    monkeypatch.setenv("HERMES_CHANNEL_CWD", "/tmp/FirmVault/cases/frances-whitis")
    monkeypatch.setenv("HERMES_SESSION_ISOLATED", "true")

    lf.set_current_trace_session_context()

    assert calls["metadata"]["hermes_session_key"] == "agent:main:slack:group:C0AGJKT10QM"
    assert calls["metadata"]["user_id"] == "U123"
    assert calls["metadata"]["chat_id"] == "C0AGJKT10QM"
    assert calls["metadata"]["session_isolated"] is True


def test_set_current_trace_session_context_noop_without_active_trace(monkeypatch):
    lf = _reload_module()

    calls = {"count": 0}

    class _FakeLangfuse:
        def get_current_trace_id(self):
            return None

        def update_current_span(self, *, metadata=None, **kwargs):
            calls["count"] += 1

    monkeypatch.setattr(lf, "is_langfuse_enabled", lambda: True)
    monkeypatch.setattr(lf, "get_langfuse", lambda: _FakeLangfuse())
    monkeypatch.setattr(lf, "get_session_env", lambda name, default="": {
        "HERMES_SESSION_KEY": "agent:main:telegram:dm:7527183362",
        "HERMES_SESSION_PLATFORM": "telegram",
        "HERMES_SESSION_CHAT_ID": "7527183362",
        "HERMES_SESSION_THREAD_ID": "",
        "HERMES_SESSION_USER_ID": "",
    }.get(name, default))

    lf.set_current_trace_session_context()

    assert calls["count"] == 0
