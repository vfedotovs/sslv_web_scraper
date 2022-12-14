def test_calculate_stats_by_price():
    # Test with a dataframe that contains price values
    df = pd.DataFrame({"Price_in_eur": [100, 200, 300, 400, 500]})
    assert calculate_stats_by_price(df, "Price_in_eur") == ["Advertisement count: 5",
                                                            "Average price: 300.0 EUR",
                                                            "Min price: 100 EUR",
                                                            "Max price: 500 EUR",
                                                            "Price range: 400"]

    # Test with a dataframe that does not contain price values
    df = pd.DataFrame({"URL": ["https://ss.lv/msg/lv/real-estate/flats/riga/centre/p0q31691478.html",
                               "https://ss.lv/msg/lv/real-estate/flats/riga/centre/p0q31691478.html",
                               "https://ss.lv/msg/lv/real-estate/flats/riga/centre/p0q31691479.html"]})
    assert calculate_stats_by_price(df, "Price_in_eur") == ["Advertisement count: 0",
                                                            "Average price: 0 EUR",
                                                            "Min price: 0 EUR",
                                                            "Max price: 0 EUR",
                                                            "Price range: 0"]
    # Test with an empty dataframe
    df = pd.DataFrame()
    assert calculate_stats_by_price(df, "Price_in_eur") == ["Advertisement count: 0",
                                                            "Average price: 0 EUR",
                                                            "Min price: 0 EUR",
                                                            "Max price: 0 EUR",
                                                            "Price range: 0"]

