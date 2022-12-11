
#from src.ws.app.wsmodules.db_worker import extract_hash


def test_extract_hash():
    # Test with a URL that contains a hash
    assert extract_hash("https://ss.lv/msg/lv/real-estate/flats/riga/centre/p0q31691478.html") == "31691478"

    # Test with a URL that does not contain a hash
    assert extract_hash("https://ss.lv/msg/lv/real-estate/flats/riga/centre/") == ""

    # Test with an empty string
    assert extract_hash("") == ""
