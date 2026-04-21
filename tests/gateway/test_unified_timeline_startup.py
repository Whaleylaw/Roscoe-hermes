"""Regression test for the T10 unified_timeline startup migration hook.

Gateway startup runs the T9 one-shot migrator exactly once — guarded by a
flag file in ``HERMES_HOME``. Subsequent starts are a no-op even if the
migrator itself re-walks (manual reruns via
``scripts/migrate_to_unified_timeline.py`` remain possible).
"""

from pathlib import Path


def test_startup_runs_migration_once(tmp_path, monkeypatch):
    hermes_home = tmp_path / "home"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    from gateway.run import maybe_run_unified_timeline_migration

    called = []

    def fake_migrate(*, db_path=None, profile_id="default"):
        called.append(profile_id)
        return 0

    # Monkeypatch the import site.
    import scripts.migrate_to_unified_timeline as m
    monkeypatch.setattr(m, "migrate", fake_migrate)

    # First call runs migration, creates flag file.
    maybe_run_unified_timeline_migration()
    assert called == ["default"]
    assert (hermes_home / ".unified_timeline_migrated").exists()

    # Second call is a no-op because the flag file exists.
    maybe_run_unified_timeline_migration()
    assert called == ["default"]
