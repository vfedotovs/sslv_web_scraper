import pandas as pd
import matplotlib.pyplot as plt


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

# loading data to dataframe from csv file
df_to_clean = pd.read_csv("pandas_df.csv")


def clean_data_frame(df_name):
    df = df_name.replace(to_replace=r'Istabas:>', value='', regex=True)
    df.replace(to_replace=r'Platiba:>', value='', regex=True, inplace=True)
    df.replace(to_replace=r'Stavs:>', value='', regex=True, inplace=True)
    df.replace(to_replace=r'/lifts', value='', regex=True, inplace=True)
    df.replace(to_replace=r'Iela:><b>', value='', regex=True, inplace=True)
    df.replace(to_replace=r'Price:>', value='', regex=True, inplace=True)
    df.replace(to_replace=r'Date:>', value='', regex=True, inplace=True)
    return df


def clean_sqm_column(df_name):
    # Sptitting column value in to new columns by separator
    df = df_name["Size_sq_m"].str.split(" ", n = 1, expand = True) # n =1 == in 2 slices

    # Create new column and sourcing data from 0th split index
    df_name["Size_sqm"]= df[0] # 0 - index at separation

    df = df_name.loc[:, df_name.columns != 'Size_sq_m'] # Drop old split column
    clean_df = df.loc[:, df.columns != 'Unnamed: 0'] # Drop duplicate  column
    return clean_df


def split_price_column(df_name):
    # Sptitting and cleanup for price columo value in to new columns by separator
    new = df_name["Price"].str.split("(", n = 1, expand = True)

    # Creating separate columns for price and SQM new data frame
    df_name["Price_EUR"]= new[0]
    df_name["SQ_M_EUR"]= new[1]

    # Remove EUR sign in price column and remove space (split at 3 slices)
    no_euro_symb = df_name["Price_EUR"].str.split(" ", n = 2, expand = True)

    # Creates new column and combines 2 indexes
    df_name["Price_in_eur"]= no_euro_symb[0] + no_euro_symb[1]

    # drop old split columns
    df = df_name.loc[:, df_name.columns != 'Price']
    final_df = df.loc[:, df.columns != 'Price_EUR']
    return final_df


def clean_sqm_eur_col(df_name):
    # Split value at EUR  symbol
    new = df_name["SQ_M_EUR"].str.split("€", n = 1, expand = True)

    # Create new column with from split df  and use only 0 index
    df_name["SQ_meter_price"]= new[0]

    # Remvoe space from clumn value strings
    df_name['SQ_meter_price'] = df_name['SQ_meter_price'].str.replace(' ', '')

    # Convert to float
    df_name['SQ_meter_price'] = df_name['SQ_meter_price'].astype(float)

    # Drop old SQ_M_EUR column
    final_df = df_name.loc[:, df_name.columns != 'SQ_M_EUR']
    return final_df





# exclude old SQ_M_EUR column == rady for save and export and analytics
final_df = clean_df.loc[:, clean_df.columns != 'SQ_M_EUR']


sorted_by_sqm = final_df.sort_values(by='SQ_meter_price', ascending=True)


only_two_rooms = sorted_by_sqm[sorted_by_sqm['Room_count']=='2']
#only_two_rooms

#TODO:  add date incertion in data_formater feature for df (will calculate how many days old is ad)
#TODO: convert othewhise plotting does not work
# convert column values to int



# convert str to int
#clean_lift_col['Price_EUR'] = clean_lift_col['Price_EUR'].astype(int)
#clean_lift_col["Price_EUR"].dtypes


### Analytics Start Here ###

# sorting df by column name
sorted_by_sqm = clean_lift_col.sort_values(by='Size_sqm', ascending=True)

all_room_prices = sorted_by_sqm['Price_EUR'].tolist()
all_room_price_count = len(all_room_prices)
avg_all_price = sum(all_room_prices) / all_room_price_count
print("All room apartment count: ",all_room_price_count )
print("All room average price: ",avg_all_price )


### Creating charts
sorted_by_sqm.plot.scatter(x='Size_sqm',y="Price_EUR",s=100, title="All 1-4 room apartments",grid=True)
#sorted_by_sqm.plot.scatter(x='Size_sqm',y="Room_count")
#sorted_by_sqm.plot.scatter(x='Price_EUR',y="Room_count")



### Filter out only 2 room apartments
only_2_rooms = sorted_by_sqm[sorted_by_sqm['Room_count']=='2']

# only_2_room_sqm = only_2_rooms.loc[:, only_2_rooms.columns == 'Size_sqm']



# list of values of  column
two_room_prices = only_2_rooms['Price_EUR'].tolist()
two_room_price_count = len(two_room_prices)
avg_price = sum(two_room_prices) / two_room_price_count




### Creating charts
only_2_rooms.plot.scatter(x='Size_sqm',y="Price_EUR",s=100, title="Only 2 room apartments",grid=True)

## TODO add labels as variables
print("2 room apartment count: ",two_room_price_count )
print("2 room average price: ",avg_price )


# Testing pychart
only_2_rooms.groupby(['Size_sqm']).sum().plot(kind='pie',subplots=True,figsize=(7,7), autopct='%1.1f%%')



### Filter out only 1 room apartments
only_1_rooms = sorted_by_sqm[sorted_by_sqm['Room_count']=='1']

one_room_prices = only_1_rooms['Price_EUR'].tolist()
one_room_price_count = len(one_room_prices)
avg_one_room_price = sum(one_room_prices) / one_room_price_count

print("1 room apartment count: ",one_room_price_count )
print("1 room average price: ", avg_one_room_price )

### Creating charts
only_1_rooms.plot.scatter(x='Size_sqm',y="Price_EUR",s=100, title="Only 1 room apartments",grid=True)


### Filter out only 3 room apartments
only_3_rooms = sorted_by_sqm[sorted_by_sqm['Room_count']=='3']

### Creating charts
only_3_rooms.plot.scatter(x='Size_sqm',y="Price_EUR",s=100, title="Only 3 room apartments",grid=True)




