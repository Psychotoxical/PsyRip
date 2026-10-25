from psyrip.naming import DEFAULT_RIP_NAMING, NamingContext, render


def ctx(**kw):
    tags = {"artist": "Madonna", "album": "Ray of Light", "title": "Holiday", "track": "4/12", "disc": "1"}
    tags.update(kw.pop("tags", {}))
    return NamingContext(tags=tags, **kw)


def test_basic():
    assert render("[artist]\\[album]\\[track] [artist] - [title]", ctx()) == \
        "Madonna\\Ray of Light\\04 Madonna - Holiday"


def test_default_rip_naming_normal_and_compilation():
    assert render(DEFAULT_RIP_NAMING, ctx()) == "Madonna\\Ray of Light\\04 Madonna - Holiday"
    assert render(DEFAULT_RIP_NAMING, ctx(compilation=True)).startswith("Various Artists\\")
    c = ctx(tags={"album artist": "Boss"})
    assert render(DEFAULT_RIP_NAMING, c).startswith("Boss\\")
    assert ", Disc 2" in render(DEFAULT_RIP_NAMING, ctx(disc=2, tags={"disc": "2"}))


def test_doc_examples():
    c = ctx()
    assert render("[RIGHT]3,abcdefg[]", c) == "efg"
    assert render("[GRAB]2,4,abcdefg[]", c) == "bcd"
    assert render("[DEL]2,4,abcdefg[]", c) == "aefg"
    assert render("[SETLEN]4,,,abcdefg[]", c) == "abcd"
    assert render("[SETLEN]14,65,,abcdefg[]", c) == "AAAAAAAabcdefg"
    assert render("[SETLEN]14,,66,abcdefg[]", c) == "abcdefgBBBBBBB"
    assert render("[TRIMFIRSTFOLDER]f1\\f2\\f3[]", c) == "f2\\f3"
    assert render("[TRIMLASTFOLDER]f1\\f2\\f3[]", c) == "f1\\f2"
    assert render("[REPLACE]<comma_>,@,a,b[]", c) == "a@b"
    assert render("[WORD]A Quick Brown Fox,2[]", c) == "A Quick"
    assert render("[GROUP]4,[artist][]", c) == "m-p"
    assert render("[SPLIT]/,A1/A2/A3,3[]", c) == "A3"
    assert render("[IFEQUALS]genre,pop,Pop![]", ctx(tags={"genre": "Pop"})) == "Pop!"
    assert render("[IF][artist],len<,5,short,long[]", c) == "long"
    assert render("[SETLEN]2,48,,[disc][]", c) == "01"


def test_nesting_and_commas_in_tags():
    c = ctx(tags={"artist": "Smith, John"})
    assert render("[UPPER][GRAB]1,1,[artist][][][LOWER][GRAB]2,,[artist][][]", c) == "Smith, john"
    assert render("[IFVALUE]artist,[artist],none[]", c) == "Smith, John"


def test_sanitize():
    assert render("[title]", ctx(tags={"title": 'a/b:c?"d'})) == "a-b-c'd"


def test_origpath():
    c = ctx(origpath="D:\\Music\\Rock\\Band", origfilename="song")
    assert render("[origpath]\\[origfilename]", c) == "D:\\Music\\Rock\\Band\\song"
    assert render("[BACKFOLDER]1[]", c) == "Band"
    assert render("[FRONTFOLDER]1[]", c) == "Music"
