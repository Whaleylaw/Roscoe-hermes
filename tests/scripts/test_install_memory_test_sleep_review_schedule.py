import plistlib
import sys
from pathlib import Path

import pytest

from scripts.install_memory_test_sleep_review_schedule import (
    LABEL,
    build_launchd_plist,
    install_launchd_schedule,
)


def test_build_launchd_plist_points_at_memory_test_wrapper(tmp_path):
    profile_home = tmp_path / "memory-test"
    profile_home.mkdir()

    plist = build_launchd_plist(
        profile_home=profile_home,
        python_executable="/usr/bin/python3",
        hour=3,
        minute=15,
    )

    assert plist["Label"] == LABEL
    assert plist["ProgramArguments"][:3] == [
        "/usr/bin/python3",
        str((Path.cwd() / "scripts" / "run_memory_test_sleep_review.py").resolve()),
        "--profile-home",
    ]
    assert plist["ProgramArguments"][3] == str(profile_home.resolve())
    assert plist["StartCalendarInterval"] == {"Hour": 3, "Minute": 15}
    assert "/opt/homebrew/bin" in plist["EnvironmentVariables"]["PATH"]
    assert plist["StandardOutPath"].endswith("memory-test-sleep-review.stdout.log")
    assert plist["StandardErrorPath"].endswith("memory-test-sleep-review.stderr.log")


def test_install_launchd_schedule_writes_plist_without_loading(tmp_path):
    profile_home = tmp_path / "memory-test"
    profile_home.mkdir()
    plist_path = tmp_path / "LaunchAgents" / f"{LABEL}.plist"

    result = install_launchd_schedule(
        profile_home=profile_home,
        plist_path=plist_path,
        python_executable=sys.executable,
        hour=4,
        minute=5,
        load=False,
    )

    assert result["success"] is True
    assert result["loaded"] is False
    assert result["plist_path"] == str(plist_path.resolve())
    with plist_path.open("rb") as handle:
        plist = plistlib.load(handle)
    assert plist["Label"] == LABEL
    assert plist["StartCalendarInterval"] == {"Hour": 4, "Minute": 5}
    assert (profile_home / "logs").is_dir()


def test_install_launchd_schedule_refuses_non_test_profile(tmp_path):
    profile_home = tmp_path / "default"
    profile_home.mkdir()

    with pytest.raises(ValueError, match="non-test profile"):
        build_launchd_plist(profile_home=profile_home)
