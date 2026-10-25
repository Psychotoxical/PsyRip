"""AccurateRip: „nicht in der Datenbank“ (404) ist etwas anderes als „Server nicht erreichbar“."""
import io
import urllib.error

import pytest

from psyrip import cdrip


def _disc():
    return cdrip.Disc([cdrip.Track(1, 0, 20000), cdrip.Track(2, 20000, 40000)], 40000, "X")


def _raise(exc):
    def f(*a, **k):
        raise exc
    return f


def test_404_means_not_in_database(monkeypatch):
    monkeypatch.setattr(cdrip.urllib.request, "urlopen", _raise(urllib.error.HTTPError("u", 404, "nf", {}, io.BytesIO())))
    assert cdrip.fetch_accuraterip(_disc()) is None


@pytest.mark.parametrize("exc", [urllib.error.URLError("getaddrinfo failed"), TimeoutError("timed out"),
                                 urllib.error.HTTPError("u", 503, "busy", {}, io.BytesIO())])
def test_network_errors_are_reported_as_unavailable(monkeypatch, exc):
    monkeypatch.setattr(cdrip.urllib.request, "urlopen", _raise(exc))
    with pytest.raises(cdrip.AccurateRipUnavailable):
        cdrip.fetch_accuraterip(_disc())
