from src.ws.app.wsmodules.db_worker import extract_hash
# import psycopg2


def test_extract_hash():
    # Test with a URL that contains a hash
    assert extract_hash(
        "https://www.ss.lv/msg/lv/real-estate/flats/ogre-and-reg/ogre/hejdl.html") == "hejdl"

    # Test with a URL that does not contain a hash
    assert extract_hash(
        "https://ss.lv/msg/lv/real-estate/flats/riga/centre/") == ""

    # Test with an empty string
    assert extract_hash("") == ""
