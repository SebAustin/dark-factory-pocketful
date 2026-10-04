import pytest

from s3lib import Api, World, base_fixture


@pytest.fixture(scope="session")
def api():
    a = Api()
    yield a
    a.http.close()


@pytest.fixture
def world(api):
    return World(api, base_fixture())


@pytest.fixture
def make_world(api):
    def _make(fx=None, **over):
        return World(api, fx if fx is not None else base_fixture(**over))
    return _make
