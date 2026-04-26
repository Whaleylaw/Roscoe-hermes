"""Tests for gateway/cross_session.py — session_target resolution."""

import json
from unittest.mock import patch

import pytest
import yaml

from gateway.cross_session import (
    SessionTarget,
    resolve_session_target,
    SessionTargetError,
)


def _setup(tmp_path, sessions, case_channels=None):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "sessions.json").write_text(json.dumps(sessions))
    if case_channels is not None:
        (tmp_path / "case_channels.yaml").write_text(yaml.safe_dump(case_channels))


def test_resolves_slack_channel_id(tmp_path):
    _setup(tmp_path, {
        "k": {
            "session_id": "sess-abby",
            "origin": {"platform": "slack", "chat_id": "C0AH0V6G2Q1"},
            "updated_at": "2026-04-25T00:00:00",
        },
    }, case_channels={
        "channel_to_cwd": {"C0AH0V6G2Q1": "/cases/abby-sitgraves"},
        "channel_to_slug": {"C0AH0V6G2Q1": "abby-sitgraves"},
    })
    with patch("gateway.mirror._SESSIONS_INDEX", tmp_path / "sessions" / "sessions.json"):
        target = resolve_session_target(
            "slack:C0AH0V6G2Q1",
            case_channels_path=tmp_path / "case_channels.yaml",
        )
    assert target == SessionTarget(
        session_id="sess-abby",
        cwd="/cases/abby-sitgraves",
        platform="slack",
        chat_id="C0AH0V6G2Q1",
        channel_name="abby-sitgraves",
    )


def test_resolves_case_slug(tmp_path):
    _setup(tmp_path, {
        "k": {
            "session_id": "sess-abby",
            "origin": {"platform": "slack", "chat_id": "C0AH0V6G2Q1"},
            "updated_at": "2026-04-25T00:00:00",
        },
    }, case_channels={
        "slug_to_channel": {"abby-sitgraves": "C0AH0V6G2Q1"},
        "channel_to_cwd": {"C0AH0V6G2Q1": "/cases/abby-sitgraves"},
        "channel_to_slug": {"C0AH0V6G2Q1": "abby-sitgraves"},
    })
    with patch("gateway.mirror._SESSIONS_INDEX", tmp_path / "sessions" / "sessions.json"):
        target = resolve_session_target(
            "case:abby-sitgraves",
            case_channels_path=tmp_path / "case_channels.yaml",
        )
    assert target.session_id == "sess-abby"
    assert target.cwd == "/cases/abby-sitgraves"


def test_resolves_slack_hash_name(tmp_path):
    _setup(tmp_path, {
        "k": {
            "session_id": "sess-abby",
            "origin": {"platform": "slack", "chat_id": "C0AH0V6G2Q1"},
            "updated_at": "2026-04-25T00:00:00",
        },
    }, case_channels={
        "slug_to_channel": {"abby-sitgraves": "C0AH0V6G2Q1"},
        "channel_to_cwd": {"C0AH0V6G2Q1": "/cases/abby-sitgraves"},
        "channel_to_slug": {"C0AH0V6G2Q1": "abby-sitgraves"},
    })
    with patch("gateway.mirror._SESSIONS_INDEX", tmp_path / "sessions" / "sessions.json"):
        target = resolve_session_target(
            "slack:#abby-sitgraves",
            case_channels_path=tmp_path / "case_channels.yaml",
        )
    assert target.session_id == "sess-abby"


def test_no_session_yet_raises(tmp_path):
    _setup(tmp_path, {}, case_channels={
        "slug_to_channel": {"abby-sitgraves": "C0AH0V6G2Q1"},
        "channel_to_cwd": {"C0AH0V6G2Q1": "/cases/abby-sitgraves"},
        "channel_to_slug": {"C0AH0V6G2Q1": "abby-sitgraves"},
    })
    with patch("gateway.mirror._SESSIONS_INDEX", tmp_path / "sessions" / "sessions.json"):
        with pytest.raises(SessionTargetError) as exc:
            resolve_session_target(
                "slack:C0AH0V6G2Q1",
                case_channels_path=tmp_path / "case_channels.yaml",
            )
    assert "no gateway session" in str(exc.value).lower()


def test_unknown_spec_raises(tmp_path):
    _setup(tmp_path, {})
    with pytest.raises(SessionTargetError):
        resolve_session_target(
            "telegram:42",
            case_channels_path=tmp_path / "case_channels.yaml",
        )
