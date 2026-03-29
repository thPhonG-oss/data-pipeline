from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from realtime.auth import DNSEAuthManager


@pytest.fixture
def auth():
    return DNSEAuthManager(username="test@example.com", password="pass")


def _mock_auth_response(token="tok123"):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"token": token}
    return resp


def _mock_me_response(investor_id=999):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"investorId": investor_id}
    return resp


def test_get_token_fetches_and_caches(auth):
    with (
        patch("realtime.auth.requests.post", return_value=_mock_auth_response()) as mock_post,
        patch("realtime.auth.requests.get", return_value=_mock_me_response()),
    ):
        token = auth.get_token()
        assert token == "tok123"
        # Second call must NOT make another HTTP request
        auth.get_token()
        assert mock_post.call_count == 1


def test_get_investor_id_cached(auth):
    with (
        patch("realtime.auth.requests.post", return_value=_mock_auth_response()),
        patch("realtime.auth.requests.get", return_value=_mock_me_response(42)) as mock_get,
    ):
        investor_id = auth.get_investor_id()
        assert investor_id == "42"
        auth.get_investor_id()
        assert mock_get.call_count == 1


def test_token_refreshed_when_near_expiry(auth):
    with (
        patch(
            "realtime.auth.requests.post", return_value=_mock_auth_response("new_tok")
        ) as mock_post,
        patch("realtime.auth.requests.get", return_value=_mock_me_response()),
    ):
        # Simulate token fetched 7.5h ago (within 1h expiry window of 8h token)
        auth._token = "old_tok"
        auth._investor_id = "1"
        auth._token_fetched_at = datetime.now(tz=UTC) - timedelta(hours=7, minutes=30)

        token = auth.get_token()
        assert token == "new_tok"
        assert mock_post.call_count == 1


def test_raises_on_auth_failure(auth):
    resp = MagicMock()
    resp.raise_for_status.side_effect = Exception("401 Unauthorized")
    with patch("realtime.auth.requests.post", return_value=resp):
        with pytest.raises(Exception, match="401"):
            auth.get_token()
