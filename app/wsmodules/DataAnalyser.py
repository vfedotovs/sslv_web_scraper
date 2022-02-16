#!/usr/bin/env python3
""" DataAnalyzer creates statistical text segments and images for report

DataAnalyzer provides functionality to extract statistical data segments
and create statistical images from data frame and postgress database.

Module requires:
	* cleaned-sorted-df.csv - contains scraped data

Module creates:
	* daily_room_type_stats.txt


Todo:
    * 
		- create new imprived methods
		- will create str segments (most of them i have algos)
			- rooms %
			- hose floors
			- apt locations
			- sqm ranges for each
		- will create images based on DF
		- need interface to connect to DB and extract historic dict and save to to df and csv

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
        img_title = 'Single_room_sqm_prices'
        #file_name = '{}_{}.png'.format(xclmn, yclmn)
        file_name = 'single_room_sqm_prices.png'
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
    dfa.gen_image(data_frame, 'Size_sqm', "Price_in_eur")
    #dfa.gen_image('double_room_sqm_prices.png')
    #dfa.gen_image('triple_room_sqm_prices.png')
    #dfa.gen_image('quad_room_sqm_prices.png')
    #dfa.gen_image('all_room_sqm_prices.png')


def run_monthly_analitics() -> None:
    """docstring"""
    pass


main()


