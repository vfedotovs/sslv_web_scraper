# from src.ws.app.wsmodules.pdf_creator import split_data_frame
# import pandas as pd
#
#
# def test_split_data_frame():
#     # Create a test dataframe
#     df = pd.DataFrame({"Room_count": [1, 2, 3, 4, 1, 2, 3, 4, 1, 2, 3, 4],
#                        "Price_in_eur": [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200]})
#
#     # Test with a valid dataframe
#     assert split_data_frame(df, "Room_count", 1) == [df[df["Room_count"] == 1],
#                                                      df[df["Room_count"] == 2],
#                                                      df[df["Room_count"] == 3],
#                                                      df[df["Room_count"] == 4]]
#
#     # Test with an empty dataframe
#     df = pd.DataFrame()
#     assert split_data_frame(df, "Room_count", 1) == []
