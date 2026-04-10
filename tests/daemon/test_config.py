"""Tests for daemon.config."""

import os
from unittest import mock

import pytest

from daemon.config import DaemonConfig


class TestDaemonConfig:
    """DaemonConfig reads exclusively from environment variables."""

    def test_defaults(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            cfg = DaemonConfig()
        assert cfg.enabled is False
        assert cfg.heartbeat_seconds == 60
        assert cfg.initial_delay_seconds == 10
        assert cfg.approval_only is True
        assert cfg.openclaw_gateway_url == "https://openclaw-gateway-dfdi.onrender.com"
        assert cfg.mission_control_url == ""
        assert cfg.firmvault_url == ""
        assert len(cfg.worker_id) > 0

    def test_enabled_true(self):
        with mock.patch.dict(os.environ, {"DAEMON_ENABLED": "true"}, clear=True):
            cfg = DaemonConfig()
        assert cfg.enabled is True

    def test_enabled_yes(self):
        with mock.patch.dict(os.environ, {"DAEMON_ENABLED": "yes"}, clear=True):
            cfg = DaemonConfig()
        assert cfg.enabled is True

    def test_enabled_1(self):
        with mock.patch.dict(os.environ, {"DAEMON_ENABLED": "1"}, clear=True):
            cfg = DaemonConfig()
        assert cfg.enabled is True

    def test_enabled_false_for_random_string(self):
        with mock.patch.dict(os.environ, {"DAEMON_ENABLED": "nope"}, clear=True):
            cfg = DaemonConfig()
        assert cfg.enabled is False

    def test_heartbeat_override(self):
        with mock.patch.dict(os.environ, {"DAEMON_HEARTBEAT_SECONDS": "30"}, clear=True):
            cfg = DaemonConfig()
        assert cfg.heartbeat_seconds == 30

    def test_heartbeat_invalid_falls_back(self):
        with mock.patch.dict(os.environ, {"DAEMON_HEARTBEAT_SECONDS": "abc"}, clear=True):
            cfg = DaemonConfig()
        assert cfg.heartbeat_seconds == 60

    def test_approval_only_default_is_true(self):
        """Safety: approval_only defaults to True for testing."""
        with mock.patch.dict(os.environ, {}, clear=True):
            cfg = DaemonConfig()
        assert cfg.approval_only is True

    def test_approval_only_can_be_disabled(self):
        with mock.patch.dict(os.environ, {"DAEMON_APPROVAL_ONLY": "false"}, clear=True):
            cfg = DaemonConfig()
        assert cfg.approval_only is False

    def test_urls_from_env(self):
        env = {
            "OPENCLAW_GATEWAY_URL": "https://custom-gateway.example.com",
            "MISSION_CONTROL_URL": "https://mc.example.com",
            "FIRMVAULT_URL": "https://fv.example.com",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = DaemonConfig()
        assert cfg.openclaw_gateway_url == "https://custom-gateway.example.com"
        assert cfg.mission_control_url == "https://mc.example.com"
        assert cfg.firmvault_url == "https://fv.example.com"

    def test_worker_id_from_env(self):
        with mock.patch.dict(os.environ, {"DAEMON_WORKER_ID": "my-worker"}, clear=True):
            cfg = DaemonConfig()
        assert cfg.worker_id == "my-worker"

    def test_summary_contains_key_fields(self):
        with mock.patch.dict(os.environ, {"DAEMON_ENABLED": "true"}, clear=True):
            cfg = DaemonConfig()
        s = cfg.summary()
        assert s["enabled"] is True
        assert "heartbeat_seconds" in s
        assert "approval_only" in s
        assert "worker_id" in s
