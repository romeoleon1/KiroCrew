"""Tests for the runtime's seam to Crew-owned KAS auth (:mod:`kiro_crew.acp.kas_host_auth`).

Two functions, both driven against a real :class:`TokenStore` rooted in a temp
data home: the spawn-time vault probe (``vault_holds_identity``) and the callback
answer (``answer_get_access_token``). The provider's own resolve/refresh behavior
is covered in ``test_kas_auth_flows.py``; here the network is never touched — a
stored token that is still far from expiry is returned without a refresh, and the
failure mapping is exercised by construction.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from kiro_crew.acp.kas_host_auth import (
    HostAuthCallbackError,
    answer_get_access_token,
    vault_holds_identity,
    vault_holds_identity_off_loop,
)
from kiro_crew.auth.store import KasToken, TokenStore, TokenStoreError


def _token(identity: str = "social", *, expires_in: int = 3600, **overrides) -> KasToken:
    kwargs = dict(
        access_token="at-value",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
        provider="Google",
        identity=identity,
        refresh_token="rt-value",
        profile_arn="arn:aws:codewhisperer:us-east-1:1:profile/x",
    )
    kwargs.update(overrides)
    return KasToken(**kwargs)


@pytest.fixture
def data_home(tmp_path):
    """Point the seam's deferred ``data_home()`` import at a temp vault root."""
    home = tmp_path / "data-home"
    home.mkdir()
    with patch("kiro_crew.config.paths.data_home", return_value=home):
        yield home


class TestVaultProbe:
    def test_empty_vault_is_no_identity(self, data_home):
        assert vault_holds_identity() is False

    def test_stored_identity_is_detected(self, data_home):
        TokenStore(data_home).save(_token())
        assert vault_holds_identity() is True

    def test_expired_but_refreshable_identity_still_counts(self, data_home):
        """The probe asks "is anyone signed in", not "is the token live": an
        expired access token with a refresh token is exactly what the provider
        refreshes on the first callback, so the spawn must be Crew-owned."""
        TokenStore(data_home).save(_token(expires_in=-60))
        assert vault_holds_identity() is True

    def test_unreadable_vault_degrades_to_no_identity(self, data_home, caplog):
        """A vault error must not fail the spawn; it falls back to cli-owned."""
        with patch(
            "kiro_crew.auth.store.TokenStore.resolve",
            side_effect=TokenStoreError("refusing linked token-store directory"),
        ):
            assert vault_holds_identity() is False
        assert "cli-owned" in caplog.text

    def test_unexpected_error_degrades_to_no_identity(self, data_home):
        with patch("kiro_crew.auth.store.TokenStore.resolve", side_effect=RuntimeError("boom")):
            assert vault_holds_identity() is False

    @pytest.mark.asyncio
    async def test_off_loop_variant_agrees(self, data_home):
        assert await vault_holds_identity_off_loop() is False
        TokenStore(data_home).save(_token())
        assert await vault_holds_identity_off_loop() is True


class TestCallbackAnswer:
    @pytest.mark.asyncio
    async def test_renders_the_covenant_shape_without_the_refresh_token(self, data_home):
        TokenStore(data_home).save(_token())
        resp = await answer_get_access_token()
        assert resp["accessToken"] == "at-value"
        assert resp["provider"] == "Google"
        assert resp["profileArn"].startswith("arn:aws:codewhisperer:")
        assert "expiresAt" in resp
        assert "refreshToken" not in resp
        assert "rt-value" not in str(resp)

    @pytest.mark.asyncio
    async def test_no_identity_is_a_token_free_error(self, data_home):
        with pytest.raises(HostAuthCallbackError) as excinfo:
            await answer_get_access_token()
        assert str(excinfo.value) == "not signed in to Kiro Crew"

    @pytest.mark.asyncio
    async def test_vault_error_is_categorized_not_echoed(self, data_home, caplog):
        with patch(
            "kiro_crew.auth.store.TokenStore.resolve",
            side_effect=TokenStoreError("refusing linked token-store directory: /secret/path"),
        ):
            with pytest.raises(HostAuthCallbackError) as excinfo:
                await answer_get_access_token()
        assert str(excinfo.value) == "credential vault error"
        assert "/secret/path" not in str(excinfo.value)
        assert "/secret/path" in caplog.text

    @pytest.mark.asyncio
    async def test_unexpected_failure_exposes_only_its_type(self, data_home, caplog):
        """A refresh endpoint's response body could ride on an exception
        message; neither the engine nor the log gets it."""
        TokenStore(data_home).save(_token())

        class Exploding(Exception):
            pass

        with patch(
            "kiro_crew.auth.bridge.handle_get_access_token",
            side_effect=Exploding("body: at-value rt-value"),
        ):
            with pytest.raises(HostAuthCallbackError) as excinfo:
                await answer_get_access_token()
        assert str(excinfo.value) == "token refresh failed"
        assert "rt-value" not in caplog.text
        assert "Exploding" in caplog.text
