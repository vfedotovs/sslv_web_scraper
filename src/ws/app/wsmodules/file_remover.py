import os


def get_data_files_to_remove(city_name: str = None) -> list:
    """Return list of temp files to clean, city-aware if city_name provided."""
    files = [
        '1_rooms_tmp.txt',
        'Mailer_report.txt',
        'basic_price_stats.txt',
        'cleaned-sorted-df.csv',
        'pandas_df.csv',
        '1-4_rooms.png',
        '1_rooms.png',
        '2_rooms.png',
        'test.png',
        'mrv2.txt',
    ]
    if city_name:
        files.extend([
            f'{city_name}-raw-data-report.txt',
            f'{city_name}_city_report.pdf',
            f'{city_name}-raw-data-report-*.txt',  # dated variants may be handled by glob elsewhere
        ])
    else:
        # legacy
        files.extend([
            'Ogre-raw-data-report.txt',
            'Ogre_city_report.pdf',
        ])
    return files


def remove_tmp_files(city_name: str = None) -> None:
    """Iterates over file list and deletes files if they match.
    Supports city_name for multi-city hygiene (Phase 3)."""
    files = get_data_files_to_remove(city_name)
    for data_file in files:
        try:
            os.remove(data_file)
            print(f'Removed: {data_file}')
        except OSError as e:
            # ignore not found
            if e.errno != 2:
                print(f'Error removing {data_file}: {e.strerror}')


if __name__ == "__main__":
    import sys
    city = sys.argv[1] if len(sys.argv) > 1 else None
    remove_tmp_files(city)
