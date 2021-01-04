import pandas as pd


# What needs to be done for analysis
# Load df from cleaned df csv file 
all_ads_df = pd.read_csv("cleaned-sorted-df.csv",index_col=False)


# Split all apartment dataframe in 4 categories 
# Create 4 dataFrames filtered by room count
only_1_rooms = all_ads_df[all_ads_df['Room_count']==1]
only_2_rooms = all_ads_df[all_ads_df['Room_count']==2]
only_3_rooms = all_ads_df[all_ads_df['Room_count']==3]
only_4_rooms = all_ads_df[all_ads_df['Room_count']==4]

cat_list = [only_1_rooms, only_2_rooms, only_3_rooms, only_4_rooms, all_ads_df]


def mini_report(df_name):
    """ Convert df column to list  and calculate basics stats """
    # extracts only EUR price colum valuses and adds to list
    lines = []
    filter_col = 'Price_in_eur'
    price_list = df_name[filter_col].tolist() 
    #print("Debug info: ", price_list)
    avg_price = sum(price_list) / len(price_list)
    min_price = min(price_list)
    max_price = max(price_list)
    price_range = max_price - min_price
#    print("Advertisement count: ",  len(price_list))
#    print(f'Average price: {avg_price} EUR')
#    print(f'Min price: {min_price} EUR')
#    print(f'Max price: {max_price} EUR')
#    print(f'Price range: {price_range} ')
    str_ac = "Advertisement count: " + str(len(price_list))
    str_avp = "Average price: " + str(avg_price) + " EUR"
    str_minp = "Min price: " + str(min_price) + " EUR"
    str_maxp = "Max price: " + str(max_price) + " EUR"
    str_pr = "Price range: " + str(price_range)  
    lines.append(str_ac)
    lines.append(str_avp)
    lines.append(str_minp)
    lines.append(str_maxp)
    lines.append(str_pr)
    return lines

def iterate_reports():
    txt_reprots = []
    for i, cat in enumerate(cat_list):
        cat_report = mini_report(cat)
        txt_reprots.append(cat_report)
    print("----- debug info ----")
    for i, reports in enumerate(txt_reprots):
            print("")
            print(str(i + 1) + " room apartment  price analysis")
            for line in reports:
                print(line)


iterate_reports()


# Category 1 advert price analisys
#2. I have interested in 1  and 2 rooms
#3. get count of apartments for sale - done 
#4. get price range for each room category  - done 
#5. get min / max / average price - done 

# Category 2 advert SQ meter analisys
#6. get min / max / average sqm size
#7. print chart price sqm 

# Category 3 advert floor location analisys
# Category 4 advert street location analisys
# Category 5 listed date analisys - requires correct datapoint fix bug
# Category 6 advert view count analisys - requires correct datapoint fix bug

