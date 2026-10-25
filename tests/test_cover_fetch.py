import io
import json

from PIL import Image

from psyrip import cdrip


def jpg(size):
    b = io.BytesIO()
    Image.new("RGB", (size, size), "green").save(b, "JPEG")
    return b.getvalue()


def test_itunes_url_size_substitution():
    u = "https://is1-ssl.mzstatic.com/image/thumb/Music/xx/00724381123355.jpg/100x100bb.jpg"
    assert cdrip.itunes_art_url(u, 1500).endswith("/1500x1500bb.jpg")


def test_similarity_ignores_edition_suffixes():
    assert cdrip._sim("Lenny", "Lenny (Deluxe Edition)") == 1.0
    assert cdrip._sim("Lenny", "Blue Electric Light") < 0.5


def fake_net(monkeypatch, itunes_size, caa_size):
    def fake_get(url, timeout=10.0, headers=None):
        if "itunes.apple.com/search" in url:
            return json.dumps({"results": [
                {"artistName": "Lenny Kravitz", "collectionName": "Lenny", "releaseDate": "2001-01-01T00:00:00Z",
                 "artworkUrl100": "https://x/img/100x100bb.jpg"},
                {"artistName": "Other", "collectionName": "Something Else", "artworkUrl100": "https://x/other/100x100bb.jpg"}]}).encode()
        if "mzstatic" in url or "https://x/" in url:
            return jpg(itunes_size)
        if "coverartarchive" in url:
            return jpg(caa_size)
        raise AssertionError(url)
    monkeypatch.setattr(cdrip, "_get", fake_get)


def test_auto_prefers_larger_and_caps_size(monkeypatch):
    fake_net(monkeypatch, itunes_size=1405, caa_size=600)
    data, src = cdrip.best_cover("Lenny Kravitz", "Lenny", "mbid", "auto", 1500)
    assert src == "Apple Music" and Image.open(io.BytesIO(data)).size == (1405, 1405)
    data, _ = cdrip.best_cover("Lenny Kravitz", "Lenny", "mbid", "auto", 1000)         # Obergrenze wird eingehalten
    assert max(Image.open(io.BytesIO(data)).size) == 1000


def test_never_upscales_and_source_selection(monkeypatch):
    fake_net(monkeypatch, itunes_size=1405, caa_size=600)
    data, src = cdrip.best_cover("Lenny Kravitz", "Lenny", "mbid", "caa", 3000)
    assert src == "Cover Art Archive" and Image.open(io.BytesIO(data)).size == (600, 600)


def test_apple_falls_back_to_caa_when_no_match(monkeypatch):
    fake_net(monkeypatch, itunes_size=1405, caa_size=600)
    data, src = cdrip.best_cover("Nobody", "Unrelated Album", "mbid", "apple", 1500)
    assert src == "Cover Art Archive"
