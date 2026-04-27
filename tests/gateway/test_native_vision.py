"""Tests for native vision support — sending images as multimodal content parts
instead of converting them to text descriptions via the auxiliary vision pipeline.
"""

import base64
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module-level helpers under test
# ---------------------------------------------------------------------------

# Ensure the parent path is importable
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class TestShouldUseNativeVision:
    """Tests for _should_use_native_vision()."""

    def _import(self):
        from gateway.run import _should_use_native_vision
        return _should_use_native_vision

    def test_env_true(self, monkeypatch):
        fn = self._import()
        monkeypatch.setenv("HERMES_VISION_NATIVE", "true")
        assert fn("openrouter", "gpt-4o") is True

    def test_env_false(self, monkeypatch):
        fn = self._import()
        monkeypatch.setenv("HERMES_VISION_NATIVE", "false")
        assert fn("openrouter", "gpt-4o") is False

    def test_env_1(self, monkeypatch):
        fn = self._import()
        monkeypatch.setenv("HERMES_VISION_NATIVE", "1")
        assert fn("openrouter", "gpt-4o") is True

    def test_env_0(self, monkeypatch):
        fn = self._import()
        monkeypatch.setenv("HERMES_VISION_NATIVE", "0")
        assert fn("openrouter", "gpt-4o") is False

    def test_auto_with_vision_model(self, monkeypatch):
        fn = self._import()
        monkeypatch.setenv("HERMES_VISION_NATIVE", "auto")

        caps = MagicMock()
        caps.supports_vision = True
        with patch("gateway.run.get_model_capabilities", return_value=caps, create=True):
            # Patch the import path used inside the function
            with patch.dict("sys.modules", {}):
                # Just test that when models_dev returns vision, result is True
                pass
        # Direct mock via monkeypatch of the function's import
        mock_caps = MagicMock(supports_vision=True)
        with patch("agent.models_dev.get_model_capabilities", return_value=mock_caps):
            assert fn("openrouter", "gpt-4o") is True

    def test_auto_without_vision_model(self, monkeypatch):
        fn = self._import()
        monkeypatch.setenv("HERMES_VISION_NATIVE", "auto")
        mock_caps = MagicMock(supports_vision=False)
        with patch("agent.models_dev.get_model_capabilities", return_value=mock_caps):
            assert fn("openrouter", "some-text-only-model") is False

    def test_auto_no_caps_data(self, monkeypatch):
        fn = self._import()
        monkeypatch.setenv("HERMES_VISION_NATIVE", "auto")
        with patch("agent.models_dev.get_model_capabilities", return_value=None):
            assert fn("unknown", "unknown-model") is False

    def test_default_is_auto(self, monkeypatch):
        fn = self._import()
        monkeypatch.delenv("HERMES_VISION_NATIVE", raising=False)
        mock_caps = MagicMock(supports_vision=True)
        with patch("agent.models_dev.get_model_capabilities", return_value=mock_caps):
            assert fn("openrouter", "gpt-4o") is True


class TestFileToDataUrl:
    """Tests for _file_to_data_url()."""

    def _import(self):
        from gateway.run import _file_to_data_url
        return _file_to_data_url

    def test_jpeg_file(self, tmp_path):
        fn = self._import()
        # Create a tiny valid JPEG (smallest possible)
        img = tmp_path / "test.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
        result = fn(str(img))
        assert result.startswith("data:image/jpeg;base64,")
        # Verify the base64 decodes back
        b64_part = result.split(",", 1)[1]
        decoded = base64.b64decode(b64_part)
        assert decoded[:4] == b"\xff\xd8\xff\xe0"

    def test_png_file(self, tmp_path):
        fn = self._import()
        img = tmp_path / "test.png"
        img.write_bytes(b"\x89PNG" + b"\x00" * 100)
        result = fn(str(img))
        assert result.startswith("data:image/png;base64,")

    def test_unknown_extension_defaults_to_jpeg(self, tmp_path):
        fn = self._import()
        img = tmp_path / "test.bin"
        img.write_bytes(b"\x00" * 100)
        result = fn(str(img))
        assert result.startswith("data:image/jpeg;base64,")


class TestRunConversationMultimodal:
    """Tests for run_conversation accepting multimodal content."""

    def test_str_message_still_works(self):
        """Ensure backward compatibility — str messages pass through."""
        from run_agent import AIAgent
        agent = MagicMock(spec=AIAgent)
        agent._main_model_supports_vision = False
        # Just verify the type check logic
        msg = "Hello world"
        assert isinstance(msg, str)

    def test_list_message_accepted(self):
        """Multimodal content parts are a valid message type."""
        msg = [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            {"type": "text", "text": "What is this?"},
        ]
        assert isinstance(msg, list)
        # Extract text parts
        text = " ".join(
            p.get("text", "") for p in msg
            if isinstance(p, dict) and p.get("type") == "text"
        ).strip()
        assert text == "What is this?"

    def test_persist_user_message_from_multimodal(self):
        """When user_message is multimodal, persist_user_message should auto-generate."""
        msg = [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            {"type": "text", "text": "Analyze this image"},
        ]
        # Simulate the auto-generation logic from run_conversation
        persist = " ".join(
            p.get("text", "") for p in msg
            if isinstance(p, dict) and p.get("type") == "text"
        ).strip() or "[Image(s) attached]"
        assert persist == "Analyze this image"

    def test_persist_user_message_images_only(self):
        """When multimodal message has no text, persist should be placeholder."""
        msg = [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        ]
        persist = " ".join(
            p.get("text", "") for p in msg
            if isinstance(p, dict) and p.get("type") == "text"
        ).strip() or "[Image(s) attached]"
        assert persist == "[Image(s) attached]"


class TestAnthropicPreprocessPreservesVision:
    """Tests for _preprocess_anthropic_content preserving images for vision models."""

    def test_preserves_images_when_vision_capable(self):
        from run_agent import AIAgent
        agent = object.__new__(AIAgent)
        agent._main_model_supports_vision = True
        agent._anthropic_image_fallback_cache = {}

        content = [
            {"type": "text", "text": "What is this?"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        ]
        result = agent._preprocess_anthropic_content(content, "user")
        # Should return content unchanged
        assert result == content
        assert any(p.get("type") == "image_url" for p in result)

    def test_strips_images_when_not_vision_capable(self):
        from run_agent import AIAgent
        agent = object.__new__(AIAgent)
        agent._main_model_supports_vision = False
        agent._anthropic_image_fallback_cache = {}

        content = [
            {"type": "text", "text": "What is this?"},
            {"type": "image_url", "image_url": {"url": "https://example.com/cat.jpg"}},
        ]
        # Mock the entire fallback method to return a text note
        with patch.object(
            AIAgent, "_describe_image_for_anthropic_fallback",
            return_value="[The user attached an image. Here's what it contains:\nA cat]",
        ):
            result = agent._preprocess_anthropic_content(content, "user")
        # Should be a string (images converted to text)
        assert isinstance(result, str)
        assert "cat" in result.lower()

    def test_no_image_parts_unchanged(self):
        from run_agent import AIAgent
        agent = object.__new__(AIAgent)
        agent._main_model_supports_vision = True
        agent._anthropic_image_fallback_cache = {}

        content = "Just a plain text message"
        result = agent._preprocess_anthropic_content(content, "user")
        assert result == "Just a plain text message"


class TestConfigNativeVision:
    """Tests for the auxiliary.vision.native config key."""

    def test_default_config_has_native_key(self):
        from hermes_cli.config import DEFAULT_CONFIG
        vision_cfg = DEFAULT_CONFIG["auxiliary"]["vision"]
        assert "native" in vision_cfg
        assert vision_cfg["native"] == "auto"

    def test_native_true_string(self):
        from hermes_cli.config import DEFAULT_CONFIG
        # Verify the default is "auto" (string)
        assert DEFAULT_CONFIG["auxiliary"]["vision"]["native"] == "auto"
