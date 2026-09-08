"""Windows-support contract for the Meetings builtin.

Pins ``platform.os``. The app gate is ``supports_platform(sys.platform)``, so a
narrower list is not a documentation nit — it is what stops the app from being
enabled at all. It shipped as ``["macos", "linux"]``, which predated the
audio-import Windows hardening rather than expressing any real POSIX
dependency: the app spawns no subprocess, imports no POSIX-only module, writes
every file through ``atomic_write``, serialises with ``threading`` locks rather
than ``fcntl``, and already branches on ``platform_compat.IS_WINDOWS`` where it
matters.
"""

from __future__ import annotations

import json
from pathlib import Path

# .../meetings/tests/test_windows_support.py -> parents[1] is the app root.
APP_ROOT = Path(__file__).resolve().parents[1]
APP_JSON = APP_ROOT / "app.json"

DECLARED_OS = ["macos", "linux", "windows"]


def _manifest() -> dict:
    return json.loads(APP_JSON.read_text(encoding="utf-8"))


# --- manifest platform declaration ---


def test_manifest_declares_every_platform_the_app_runs_on():
    """Pinned because both narrower answers misinform.

    ``["macos", "linux"]`` reads as "does not run on Windows" and makes the
    enable gate refuse; omitting the block falls back to the implicit default,
    which silently drops Windows the same way.
    """
    assert _manifest()["platform"]["os"] == DECLARED_OS


def test_declared_platforms_all_resolve_to_a_real_sys_platform():
    """Every declared name must map to a ``sys.platform`` value.

    An unmapped name is accepted into the list and then never matches, so a
    declaration can claim a platform the gate rejects.
    """
    from kiro_crew.apps.manifest import PlatformConfig

    cfg = PlatformConfig(os=_manifest()["platform"]["os"])
    for sys_platform in ("darwin", "linux", "win32"):
        assert cfg.supports_platform(sys_platform), sys_platform
