import pytest

from s2lib import Api, World, fixture


@pytest.fixture(scope="session")
def api():
    a = Api()
    yield a
    a.http.close()


@pytest.fixture
def world(api):
    return World(api, fixture())


@pytest.fixture
def make_world(api):
    def _make(fx=None, **over):
        return World(api, fx if fx is not None else fixture(**over))
    return _make


# ---------------------------------------------------------------- screens (playwright)

@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture(params=["mobile", "desktop"])
def page(request, browser):
    from uilib import VIEWPORTS
    ctx = browser.new_context(viewport=VIEWPORTS[request.param])
    pg = ctx.new_page()
    pg.set_default_timeout(8000)
    yield pg
    ctx.close()


@pytest.fixture
def new_page(browser):
    """Factory for extra pages/viewports inside one test."""
    ctxs = []

    def _make(width=390, height=844):
        ctx = browser.new_context(viewport={"width": width, "height": height})
        ctxs.append(ctx)
        pg = ctx.new_page()
        pg.set_default_timeout(8000)
        return pg
    yield _make
    for c in ctxs:
        c.close()
