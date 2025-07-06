import os
import logging
from typing import List

logging.basicConfig(level=logging.INFO)

def remove_tmp_files(files_to_remove: List[str]) -> None:
    """Delete files in the provided list, logging any errors."""
    for data_file in files_to_remove:
        try:
            os.remove(data_file)
            logging.info(f"Deleted: {data_file}")
        except OSError as e:
            logging.error(f"Error deleting {data_file}: {e.strerror}")

if __name__ == "__main__":
    data_files = [
        '1_rooms_tmp.txt',
        'Mailer_report.txt',
        'Ogre-raw-data-report.txt',
        'basic_price_stats.txt',
        'cleaned-sorted-df.csv',
        'pandas_df.csv',
        '1-4_rooms.png',
        '1_rooms.png',
        '2_rooms.png',
        'test.png',
        'mrv2.txt'
    ]
    remove_tmp_files(data_files)
