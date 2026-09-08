"""Crew as the KAS engine's auth owner: vault probe and callback answer.

The relay described in :mod:`kiro_crew.acp.kas_transport` has two auth owners.
This module is the runtime's seam to the one where Crew owns the credential:

- :func:`vault_holds_identity` decides, at spawn time, whether the relay is
  started without ``--auth-method cli`` -- true only when Crew's own vault
  (:mod:`kiro_crew.auth.store`) holds a stored identity. It is a plain read of
  the vault, no refresh and no network, and it never raises: a vault that cannot
  be read is reported as "no identity", which keeps the spawn on the cli-owned
  path a signed-out operator already has.
- :func:`answer_get_access_token` renders the response for the engine's
  ``_kiro/auth/getAccessToken`` request from
  :class:`kiro_crew.auth.provider.KasAuthProvider` (resolve + refresh under the
  cross-process lock, refresh token withheld). Failures are mapped to a
  token-free error string the runtime can both log and return.

Why the probe and the answer are separated from the runtime: the runtime module
keeps :mod:`kiro_crew.auth` (and through it aiohttp) off its import graph until a
KAS spawn actually needs it, matching how it defers ``config.loader``. Both
functions are also independently testable without a live process.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class HostAuthCallbackError(Exception):
    """The callback could not be answered. ``str(exc)`` is token-free by construction."""


def vault_holds_identity() -> bool:
    """True when Crew's own vault stores a Kiro identity (any of the three kinds).

    Blocking file IO -- call off the event loop. Never raises: a missing,
    unreadable, or linked vault directory is ``False`` (with the reason logged
    once at WARNING for the unreadable case), so a broken vault degrades to the
    cli-owned spawn rather than failing the spawn.
    """
    # Deferred: keeps kiro_crew.auth off the runtime's import graph.
    from kiro_crew.auth.store import TokenStore, TokenStoreError
    from kiro_crew.config.paths import data_home

    try:
        return TokenStore(data_home()).resolve() is not None
    except TokenStoreError as exc:
        logger.warning("Crew credential vault unreadable; KAS spawns cli-owned: %s", exc)
        return False
    except Exception as exc:  # noqa: BLE001 - a vault probe must never fail a spawn
        logger.warning(
            "Crew credential vault probe failed (%s); KAS spawns cli-owned",
            type(exc).__name__,
        )
        return False


async def vault_holds_identity_off_loop() -> bool:
    """:func:`vault_holds_identity` on a worker thread."""
    return await asyncio.to_thread(vault_holds_identity)


async def answer_get_access_token() -> dict:
    """Build the ``_kiro/auth/getAccessToken`` response from Crew's vault.

    Returns the covenant shape (``accessToken``, ``expiresAt``, optional
    ``profileArn`` / ``provider`` / ``authMethod``); the refresh token is never
    part of it. Raises :class:`HostAuthCallbackError` with a token-free message
    when no credential is stored or the refresh fails, so the runtime can return
    the same string to the engine as a JSON-RPC error.
    """
    # Deferred for the same reason as in vault_holds_identity.
    from kiro_crew.auth.bridge import handle_get_access_token
    from kiro_crew.auth.provider import KasAuthProvider, NotAuthenticated
    from kiro_crew.auth.store import TokenStore, TokenStoreError
    from kiro_crew.config.paths import data_home

    try:
        provider = KasAuthProvider(TokenStore(data_home()))
        return await handle_get_access_token(provider)
    except NotAuthenticated as exc:
        # The engine renders this string in its sign-in prompt; keep it short.
        raise HostAuthCallbackError("not signed in to Kiro Crew") from exc
    except TokenStoreError as exc:
        # Detail (a path, never a secret) stays in the local log; the engine gets
        # only the category.
        logger.warning("KAS auth callback: credential vault error: %s", exc)
        raise HostAuthCallbackError("credential vault error") from exc
    except Exception as exc:  # noqa: BLE001
        # An unexpected exception's message could carry response bytes from a
        # refresh endpoint; expose only its type, and only in the local log.
        logger.warning("KAS auth callback: token refresh failed: %s", type(exc).__name__)
        raise HostAuthCallbackError("token refresh failed") from exc
