from psyrip import tagproc


def test_rules_map_delete_additions():
    t = {"artist": "THE BEATLES", "album": "Best of", "genre": "Alt Rock", "tracknumber": "4/12", "date": "1990-12-30"}
    out = tagproc.process(t, {
        "map": "artist>albumartist",
        "capitalize": "smart",
        "rules": "SET genre=Rock IF genre=Alt Rock\nSET album=[album], [artist] IFCONTAINS album=Best of",
        "drop_track_count": True, "drop_year_month_day": True,
        "additions": "comment=(c) [artist]",
    })
    assert out["albumartist"] == "The Beatles"          # Map läuft vor der Großschreibung und wird mitformatiert
    assert out["artist"] == "The Beatles"
    assert out["genre"] == "Rock"
    assert out["album"] == "Best Of, The Beatles"       # Smart-Capitalize läuft vor den Regeln
    assert out["tracknumber"] == "4" and out["date"] == "1990"
    assert out["comment"] == "(c) The Beatles"


def test_delete_modes_and_replace():
    t = {"artist": "a", "album": "b", "title": "Song (Disc1)"}
    assert tagproc.process(t, {"delete_mode": "except", "delete_names": "artist"}) == {"artist": "a"}
    assert tagproc.process(t, {"delete_mode": "single", "delete_names": "album"}) == {"artist": "a", "title": "Song (Disc1)"}
    assert tagproc.process(t, {"replace": "(disc1)[nocase]=>"})["title"] == "Song "
