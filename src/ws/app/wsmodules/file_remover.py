import os


data_files = ['1_rooms_tmp.txt',
              'Mailer_report.txt',
              'Ogre-raw-data-report.txt',
              'basic_price_stats.txt',
              'cleaned-sorted-df.csv',
              'pandas_df.csv',
              '1-4_rooms.png',
              '1_rooms.png',
              '2_rooms.png',
              'test.png',
              'mrv2.txt',
              'Ogre_city_report.pdf']


def remove_tmp_files() -> None:
    """Iterates over file list and deletes file
    if matches file name in list"""
    for data_file in data_files:
        try:
            os.remove(data_file)
        except OSError as e:
            print(f'Error: {data_file} : {e.strerror}')


remove_tmp_files()
