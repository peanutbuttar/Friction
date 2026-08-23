"""Browser sweep logic, tested against fake ScriptingBridge objects.

The real Apple Event path can't be unit tested (it needs a running browser and a
TCC grant), but the decision of *which* tabs to close is exactly where a bug
would silently close the wrong thing -- so that part is faked and tested.
"""
from __future__ import annotations

import pytest

from friction.blockers import browsers


class FakeTab:
    def __init__(self, url):
        self._url, self.closed = url, False

    def URL(self):          # noqa: N802 - mirrors the ScriptingBridge selector
        return self._url

    def close(self):
        self.closed = True


class FakeWindow:
    def __init__(self, tabs): self._tabs = tabs
    def tabs(self): return self._tabs


class FakeApp:
    def __init__(self, windows, running=True):
        self._windows, self._running = windows, running
    def isRunning(self): return self._running      # noqa: N802
    def windows(self): return self._windows


@pytest.fixture
def patch_app(monkeypatch):
    def install(app):
        monkeypatch.setattr(browsers, "_app", lambda bundle_id: app)
    return install


def test_closes_only_matching_tabs(patch_app):
    tabs = [FakeTab("https://reddit.com/r/all"),
            FakeTab("https://github.com/anthropics"),
            FakeTab("https://old.reddit.com/")]
    patch_app(FakeApp([FakeWindow(tabs)]))

    closed = browsers.sweep_browser("chrome", ["reddit.com"])

    assert [t.closed for t in tabs] == [True, False, True]
    assert {c.rule for c in closed} == {"reddit.com"}


def test_dry_run_closes_nothing(patch_app):
    tabs = [FakeTab("https://reddit.com/")]
    patch_app(FakeApp([FakeWindow(tabs)]))

    closed = browsers.sweep_browser("chrome", ["reddit.com"], dry_run=True)

    assert closed and closed[0].url == "https://reddit.com/"
    assert tabs[0].closed is False, "dry run must never close a tab"


def test_browser_not_running_is_skipped(patch_app):
    patch_app(None)   # _app returns None when the browser isn't running
    assert browsers.sweep_browser("chrome", ["reddit.com"]) == []


def test_no_rules_means_no_sweep(monkeypatch):
    """With nothing armed, don't even talk to the browser."""
    called = []
    monkeypatch.setattr(browsers, "_app", lambda b: called.append(b))
    assert browsers.sweep([], {"chrome": True}) == []
    assert called == []


def test_disabled_browser_is_not_swept(monkeypatch):
    called = []
    monkeypatch.setattr(browsers, "_app", lambda b: called.append(b))
    browsers.sweep(["reddit.com"], {"chrome": False, "arc": False})
    assert called == []


def test_multiple_windows(patch_app):
    a, b = FakeTab("https://x.com/"), FakeTab("https://x.com/home")
    patch_app(FakeApp([FakeWindow([a]), FakeWindow([b])]))
    browsers.sweep_browser("chrome", ["x.com"])
    assert a.closed and b.closed


def test_unreadable_tab_does_not_stop_the_sweep(patch_app):
    class Exploding(FakeTab):
        def URL(self): raise RuntimeError("apple event failed")  # noqa: N802
    good = FakeTab("https://reddit.com/")
    patch_app(FakeApp([FakeWindow([Exploding("x"), good])]))

    browsers.sweep_browser("chrome", ["reddit.com"])

    assert good.closed, "one bad tab must not abort the whole sweep"


def test_about_blank_never_closed(patch_app):
    tabs = [FakeTab("about:blank"), FakeTab("chrome://settings")]
    patch_app(FakeApp([FakeWindow(tabs)]))
    browsers.sweep_browser("chrome", ["reddit.com"])
    assert not any(t.closed for t in tabs)
