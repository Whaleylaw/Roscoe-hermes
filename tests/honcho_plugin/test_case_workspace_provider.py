"""Regression tests for passive case-scoped Honcho workspace selection."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from plugins.memory.honcho import HonchoMemoryProvider
from plugins.memory.honcho.client import HonchoClientConfig


def test_provider_derives_case_workspace_from_cwd_and_skips_global_memory_migration():
    cfg = HonchoClientConfig(
        enabled=True,
        base_url="http://localhost:8000",
        workspace_id="lawyer-incorporated",
        session_strategy="per-directory",
    )
    manager = MagicMock()
    manager.get_or_create.return_value = SimpleNamespace(messages=[])

    with (
        patch("plugins.memory.honcho.client.HonchoClientConfig.from_global_config", return_value=cfg),
        patch("plugins.memory.honcho.client.get_honcho_client", return_value=MagicMock()),
        patch("plugins.memory.honcho.session.HonchoSessionManager", return_value=manager) as manager_cls,
    ):
        provider = HonchoMemoryProvider()
        provider.initialize(
            "session-123",
            platform="slack",
            cwd="/Users/aaronwhaley/.hermes/agents/paralegal/workspace/FirmVault/cases/michael-crader",
            gateway_session_key="agent:paralegal:slack:channel:C0CASE123",
        )

    effective_cfg = manager_cls.call_args.kwargs["config"]
    assert effective_cfg.workspace_id == "case-michael-crader"
    assert provider._session_key == "agent-paralegal-slack-channel-C0CASE123"
    manager.migrate_memory_files.assert_not_called()


def test_provider_respects_explicit_honcho_workspace_override():
    cfg = HonchoClientConfig(
        enabled=True,
        base_url="http://localhost:8000",
        workspace_id="lawyer-incorporated",
        session_strategy="per-directory",
    )
    manager = MagicMock()
    manager.get_or_create.return_value = SimpleNamespace(messages=[])

    with (
        patch("plugins.memory.honcho.client.HonchoClientConfig.from_global_config", return_value=cfg),
        patch("plugins.memory.honcho.client.get_honcho_client", return_value=MagicMock()),
        patch("plugins.memory.honcho.session.HonchoSessionManager", return_value=manager) as manager_cls,
    ):
        provider = HonchoMemoryProvider()
        provider.initialize(
            "session-123",
            platform="slack",
            cwd="/not/a/case/path",
            honcho_workspace="case-abby-sitgraves",
        )

    effective_cfg = manager_cls.call_args.kwargs["config"]
    assert effective_cfg.workspace_id == "case-abby-sitgraves"
    manager.migrate_memory_files.assert_not_called()
