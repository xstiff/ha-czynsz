"""Kody HTTP przy logowaniu: tylko odrzucone dane to błąd uwierzytelnienia."""
import pytest

from czynsz.api import TmdAuthError, TmdClient, TmdError


class _Resp:
    def __init__(self, status):
        self.status = status
        self.cookies = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self, content_type=None):
        return []


class _Session:
    def __init__(self, status):
        self.status = status

    def post(self, *args, **kwargs):
        return _Resp(self.status)


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_rejected_credentials_are_auth_errors(status):
    with pytest.raises(TmdAuthError):
        await TmdClient(_Session(status), 1, "x").async_login()


@pytest.mark.parametrize("status", [404, 429, 500, 503])
async def test_transient_errors_do_not_trigger_reauth(status):
    with pytest.raises(TmdError) as err:
        await TmdClient(_Session(status), 1, "x").async_login()
    assert not isinstance(err.value, TmdAuthError)
