#!/usr/bin/env python3
""" DataAnalyzer creates statistical text segments and images for report

DataAnalyzer provides functionality to extract statistical data segments
and create statistical images from data frame and postgress database.

Module requires:
	* cleaned-sorted-df.csv - contains scraped data

Module creates:
	* daily_room_type_stats.txt


Todo:
    * [ ] Create str segments (most of algos are in jupyter)
			- [ ] rooms types %
			- [ ] house floors
			- [ ] apt locations
			- [ ] sqm size ranges for each
			- [ ] sqm price ranges for each
	* [ ] Create images based on DF
			- [ ] gen_image(data_frame, 'Size_sqm', "Price_in_eur") - created but df not filtered by room cunt = 1
            - [ ] gen_image('double_room_sqm_prices.png')
            - [ ] gen_image('triple_room_sqm_prices.png')
            - [ ] gen_image('quad_room_sqm_prices.png')
            - [] gen_image('all_room_sqm_prices.png')

	* Need interface to connect to DB and extract historic dict and save to to df and csv

"""
import pandas as pd


class DataFrameAvalyzer():

    def __init__(self, df_file_name: str):
        self.df_file_name = df_file_name

    def analyze_df_room_types(self, file) -> None:
        pass

    def analyze_df_house_types(self, file) -> None:
        pass

    def analyze_df_apt_loc_types(self, file) -> None:
        pass


    def gen_image(self, data_frame: pd.DataFrame, xclmn: str, yclmn: str) -> None:
        """Generate scatter plot based x and y axsis as data frame column values,
        include title and save to *.png file"""
        img_title = 'All room sqm size to price relationships'
        #file_name = '{}_{}.png'.format(xclmn, yclmn)
        file_name = 'all_room_sqm_prices.png'
        ax = data_frame.plot.scatter(
            x=xclmn, y=yclmn, s=100, title=img_title, grid=True)
        fig = ax.get_figure()
        fig.savefig(file_name)


class DBAnalyzer():
    pass


def main():
    """docstring"""
    run_daily_analitics()
    run_monthly_analitics()


def run_daily_analitics() -> None:
    """docstring"""
    data_frame = pd.read_csv('cleaned-sorted-df.csv')
    dfa = DataFrameAvalyzer('cleaned-sorted-df.csv')
    #dfa.analyze_df_room_types('daily_room_stats.txt')
    #dfa.analyze_df_house_types('daily_house_stats.txt')
    #dfa.analyze_df_apt_loc_types('daily_apt_loc_stats.txt')
    #dfa.gen_image(data_frame, 'Size_sqm', "Price_in_eur")
    #dfa.gen_image('double_room_sqm_prices.png')
    #dfa.gen_image('triple_room_sqm_prices.png')
    #dfa.gen_image('quad_room_sqm_prices.png')
    dfa.gen_image(data_frame, 'Size_sqm', "Price_in_eur")


def run_monthly_analitics() -> None:
    """docstring"""
    pass


main()


