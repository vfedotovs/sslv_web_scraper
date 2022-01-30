""" df_cleaner.py module

Main features of this module:
    1. Read csv to pandas df in memory
    2. Clean up values in df columns
    3. Save as clean df in csv format
"""
import pandas as pd

print("Debug info: Starting data frame cleaning module ... ")
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
    df = df_name["Size_sq_m"].str.split(" ", n=1, expand=True)  # n=1 == in 2 slices
    # Create new column and sourcing data from 0th split index
    df_name["Size_sqm"] = df[0]  # 0 - index at separation
    df = df_name.loc[:, df_name.columns != 'Size_sq_m']  # Drop old split column
    clean_df = df.loc[:, df.columns != 'Unnamed: 0']  # Drop duplicate  column
    return clean_df


def split_price_column(df_name):
    # Spitting and cleanup for price column value in to new columns by separator
    new = df_name["Price"].str.split("(", n=1, expand=True)
    # Creating separate columns for price and SQM new data frame
    df_name["Price_EUR"] = new[0]
    df_name["SQ_M_EUR"] = new[1]
    # Remove EUR sign in price column and remove space (split at 3 slices)
    no_euro_symb = df_name["Price_EUR"].str.split(" ", n=2, expand=True)
    # Creates new column and combines 2 indexes
    df_name["Price_in_eur"] = no_euro_symb[0] + no_euro_symb[1]
    # drop old split columns
    df = df_name.loc[:, df_name.columns != 'Price']
    final_df = df.loc[:, df.columns != 'Price_EUR']
    return final_df


def clean_sqm_eur_col(df_name):
    # Split value at EUR  symbol
    new = df_name["SQ_M_EUR"].str.split("€", n=1, expand=True)
    # Create new column with from split df  and use only 0 index
    df_name["SQ_meter_price"] = new[0]
    # Remvoe space from clumn value strings
    df_name['SQ_meter_price'] = df_name['SQ_meter_price'].str.replace(' ', '')
    # Convert to float
    df_name['SQ_meter_price'] = df_name['SQ_meter_price'].astype(float)
    # Drop old SQ_M_EUR column
    final_df = df_name.loc[:, df_name.columns != 'SQ_M_EUR']
    return final_df


def save_text_report_to_file(text: list, file_name: str) -> None:
    """Writes oneline data text to mailer report file"""
    with open(file_name, 'a') as the_file:
        for line in text:
            the_file.write(f"{line}\n")


def create_email_body(clean_data_frame, file_name: str) -> None:
    """Creates categorized by room count ad hash : data for email body.

    Requires:
        clean_data_frame: pandas data frame

    Creates:
        email_body_txt_m4.txt: text file"""

    email_body_txt = []
    for room_count in range(4):
        room_count_str = str(room_count + 1)
        section_line = str(room_count_str + " room apartment segment:")
        email_body_txt.append(section_line)
        filtered_by_room_count = clean_data_frame.loc[clean_data_frame['Room_count'] == int(room_count_str)]
        colum_line = "[Rooms, Floor, Size , Price, SQM Price, Apartment Street, Pub_date,  URL]"
        email_body_txt.append(colum_line)
        for index, row in filtered_by_room_count.iterrows():
            url_str = row["URL"]
            sqm_str = row["Size_sqm"]
            floor_str = row["Floor"]
            total_price = row["Price_in_eur"]
            sqm_price = row['SQ_meter_price']
            rooms_str = row['Room_count']
            street_str = row['Street']
            pub_date_str = row['Pub_date']
            report_line = "  " + str(rooms_str) + "     " + \
                          str(floor_str) + "    " + \
                          str(sqm_str) + "   " + \
                          str(total_price) + "    " + \
                          str(sqm_price) + "   " + \
                          str(street_str) + "   " + \
                          str(pub_date_str) + " " + \
                          str(url_str)
            email_body_txt.append(report_line)
    save_text_report_to_file(email_body_txt, file_name)



def df_cleaner_main():
    """ Cleans df, sorts df by price in EUR, save to csv file """
    clean_df = clean_data_frame(df_to_clean)
    clean_sqm_col = clean_sqm_column(clean_df)
    clean_price_col = split_price_column(clean_sqm_col)
    clean_df = clean_sqm_eur_col(clean_price_col)
    sorted_df = clean_df.sort_values(by='Price_in_eur', ascending=True)
    sorted_df.to_csv("cleaned-sorted-df.csv")
    all_ads_df = pd.read_csv("cleaned-sorted-df.csv", index_col=False)
    create_email_body(all_ads_df, 'email_body_txt_m4.txt')
    print("Debug info: Completed dat_formater module ... ")



# Main module code driver
df_cleaner_main()
