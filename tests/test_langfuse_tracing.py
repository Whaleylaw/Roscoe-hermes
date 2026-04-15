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
