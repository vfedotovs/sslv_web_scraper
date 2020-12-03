import pandas as pd


"""
Main features of this module:
1. Sort/filter data what is read if pandas df csv file
2. Create charts that can be converted to pdf and attached to email

Detailed requirement list:
1. Filter only 2 room apartments
2. Sort them by price / get count min max and average price 
3. Sort them by space / the same as above
4. Sort tehm by instert date / the same as above
5. Create charts for 3 steps mentioned above 

"""

# Read Pandas df from CSV

all_apartments = pd.read_csv("pandas-df.csv")
#test_data.head()

# Write df to csv file
# df.to_csv("only-2-room.csv")

