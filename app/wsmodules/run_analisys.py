""" module docstring """

import pandas as pd

data_frame = pd.read_csv('cleaned-sorted-df.csv')

#segments = [ 'room_stats.txt',
#             'house_stats.txt',
#             'apt_loc_stats.txt' ]


#images = [ 'single_room_sqm_prices.png',
#           'double_room_sqm_prices.png',
#           'triple_room_sqm_prices.png',
#           'quad_room_sqm_prices.png',
#           'all_room_sqm_prices.png' ]
data_frames = [ ]


def run_analisys():
    for data_frame in data_frames:
        analyze_data('room_stats', 'room_stats.txt', data_frame)
        analyze_data('house_stats', 'house_stats.txt', data_frame)
        analyze_data('apt_loc_stats', 'room_stats.txt', data_frame)
        gen_image(data_frame, 'Price', 'Sqm')


def analyze_data(segment_type: str, file_name: str,
                 data_frame: pd.DataFrame) -> None:
    """ TODO """
    pass

def gen_image(data_frame: pd.DataFrame, xclmn: str, yclmn: str) -> None:
    """Generate scatter plot based x and y axsis as data frame column values,
    include title and save to *.png file"""
    img_title = 'FIXME'
    file_name = '{}_{}.png'.format(xclmn, yclmn)
    ax = data_frame.plot.scatter(
        x=xclmn, y=yclmn, s=100, title=img_title, grid=True)
    fig = ax.get_figure()
    fig.savefig(file_name)


run_analisys()

