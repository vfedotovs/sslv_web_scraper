# from src.ws.app.wsmodules.df_cleaner import split_price_column
# import pandas as pd
#
#
# def test_split_price_column():
#     # Test with a dataframe that contains a price column with multiple values
#     df = pd.DataFrame(
#         {"Price": ["€ 1 000 (17.65)", "€ 2 000 (30.85)", "€ 3 000 (42.55)"]})
#     expected_output = pd.DataFrame({"SQ_M_EUR": ["17.65", "30.85", "42.55"],
#                                     "Price_in_eur": ["€ 1 000", "€ 2 000", "€ 3 000"]})
#     assert split_price_column(df).equals(expected_output)
#
#     # Test with a dataframe that contains a price column with a single value
#     df = pd.DataFrame({"Price": ["€ 1 000 (17.65)"]})
#     expected_output = pd.DataFrame({"SQ_M_EUR": ["17.65"],
#                                     "Price_in_eur": ["€ 1 000"]})
#     assert split_price_column(df).equals(expected_output)
#
#     # Test with a dataframe that contains a price column with empty values
#     df = pd.DataFrame({"Price": ["", "", ""]})
#     expected_output = pd.DataFrame({"SQ_M_EUR": ["", "", ""],
#                                     "Price_in_eur": ["", "", ""]})
#     assert split_price_column(df).equals(expected_output)
