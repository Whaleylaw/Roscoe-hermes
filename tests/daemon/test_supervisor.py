"""Tests for daemon.supervisor."""

import os
import threading
import time
from unittest import mock

import pytest

from daemon.config import DaemonConfig
from daemon.supervisor import Supervisor, start, stop, _instance_lock, _running_instance


@pytest.fixture(autouse=True)
def _clean_module_state():
    """Ensure no stale daemon state leaks between tests."""
    import daemon.supervisor as mod
    mod._running_instance = None
    # Release lock if held from a prior test failure.
    try:
        mod._instance_lock.release()
    except RuntimeError:
        pass
    yield
    # Cleanup after test.
    stop(timeout=2)
    mod._running_instance = None
    try:
        mod._instance_lock.release()
    except RuntimeError:
        pass


class TestSupervisorLifecycle:
    """Test that the supervisor starts and stops cleanly."""

    def _make_config(self, **overrides):
        env = {
            "DAEMON_ENABLED": "true",
            "DAEMON_HEARTBEAT_SECONDS": "1",
            "DAEMON_INITIAL_DELAY_SECONDS": "0",
        }
        env.update(overrides)
        with mock.patch.dict(os.environ, env, clear=True):
            return DaemonConfig()

    def test_start_when_disabled_returns_none(self):
        with mock.patch.dict(os.environ, {"DAEMON_ENABLED": "false"}, clear=True):
            cfg = DaemonConfig()
        result = start(cfg)
        assert result is None

    def test_start_and_stop(self):
        cfg = self._make_config()
        thread = start(cfg)
        assert thread is not None
        assert thread.is_alive()

        stop(timeout=3)
        thread.join(timeout=3)
        assert not thread.is_alive()

    def test_duplicate_start_rejected(self):
        cfg = self._make_config()
        t1 = start(cfg)
        assert t1 is not None

        t2 = start(cfg)
        assert t2 is None, "Second start should be rejected"

        stop(timeout=3)
        t1.join(timeout=3)

    def test_supervisor_runs_ticks(self):
        cfg = self._make_config(DAEMON_HEARTBEAT_SECONDS="1")
        sup = Supervisor(cfg)

        # Run for ~2 seconds, then stop.
        def run_briefly():
            time.sleep(2.0)
            sup.request_stop()

        stopper = threading.Thread(target=run_briefly, daemon=True)
        stopper.start()
        sup.run()
        stopper.join(timeout=3)

        assert sup._tick_count >= 1, "Should have run at least one tick"

    def test_supervisor_respects_stop_during_sleep(self):
        cfg = self._make_config(DAEMON_HEARTBEAT_SECONDS="60")
        sup = Supervisor(cfg)

        # Request stop after 0.5s — should exit well before the 60s heartbeat.
        def stop_soon():
            time.sleep(0.5)
            sup.request_stop()

        stopper = threading.Thread(target=stop_soon, daemon=True)
        stopper.start()

        t0 = time.monotonic()
        sup.run()
        elapsed = time.monotonic() - t0

        assert elapsed < 5.0, f"Should have stopped promptly, took {elapsed:.1f}s"
        stopper.join(timeout=2)


class TestSupervisorApprovalOnly:
    """Test that approval_only mode is enforced."""

    def test_approval_only_defaults_true(self):
        with mock.patch.dict(os.environ, {"DAEMON_ENABLED": "true"}, clear=True):
            cfg = DaemonConfig()
        sup = Supervisor(cfg)
        assert sup.config.approval_only is True
