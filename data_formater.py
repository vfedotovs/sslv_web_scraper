import re
# import pandas as pd


def write_mailer_report() -> None:
    """ This function will use *raw-data-report.txt
        will format data in one line and will create Mailer_report.txt
        that should be used by gmailer module   """

    text_data = create_oneline_report('Ogre-raw-data-report.txt')
    create_mailer_report(text_data, 'tmp_report.txt')
    create_filtered_report('tmp_report.txt', '1_rooms_tmp.txt', 'Istabas:>1')
    create_filtered_report('tmp_report.txt', '2_rooms_tmp.txt', 'Istabas:>2')
    create_filtered_report('tmp_report.txt', '3_rooms_tmp.txt', 'Istabas:>3')
    create_filtered_report('tmp_report.txt', '4_rooms_tmp.txt', 'Istabas:>4')
    tmp_reports = ['1_rooms_tmp.txt', '2_rooms_tmp.txt',
                   '3_rooms_tmp.txt', '4_rooms_tmp.txt']

    room_count = 1
    for report in tmp_reports:
        merge_reports(report, 'Mailer_report.txt', room_count)
        room_count += 1


def create_oneline_report(source_file: str) -> list:
    """ Converts raw-data-report to oneline report in memory
    Args:
        source_file: raw-data text file for example Ogre-raw-data-report.txt

    Returns: str list
    """
    urls = []
    room_counts = []
    room_sizes = []
    room_streets = []
    room_prices = []
    room_floors = []
    oneline_report = []
    with open(source_file) as file_handle:
        while True:
            line = file_handle.readline()
            match_url = re.search("https", line)
            if match_url:
                urls.append(line.rstrip('\n'))

            match_room_count = re.search("Istabas:", line)
            if match_room_count:
                room_counts.append(line.rstrip('\n'))

            match_room_street_count = re.search("Iela:", line)
            if match_room_street_count:
                room_streets.append(line.rstrip('\n'))

            match_room_price = re.search("Price:", line)
            if match_room_price:
                room_prices.append(line.rstrip('\n'))

            match_room_size = re.search("Platība:", line)
            if match_room_size:
                tmp = line.rstrip('\n')
                sizes = tmp.replace("Platība:", "Platiba:")
                room_sizes.append(sizes)

            match_room_floor = re.search("Stāvs:", line)
            if match_room_floor:
                tmp = line.rstrip('\n')
                floors = tmp.replace("Stāvs:", "Stavs:")
                room_floors.append(floors)

            if not line:
                break
    
    # Create pandas df for saving to csv
    # dict = {'URL': urls, 'Room_count': room_counts,
    #         'Size_sq_m' : room_sizes, 'Floor': room_floors,
    #         'Street': room_streets, 'Price': room_prices}
    # df = pd.DataFrame(dict)
    # df.to_csv("pandas_df.csv")

    for i in range(len(urls) - 1):
        # oneline = urls[i] + " " + room_counts[i] + " " + room_sizes[i] + " "
        #           + room_streets[i] + "   " + room_prices[i]

        # this is workaround for SMTP module ASCI errors
        oneline = urls[i] + " " + room_counts[i] + " " + room_floors[i] \
                  + " " + room_sizes[i] + "   " + room_prices[i]

        # print(oneline)
        oneline_report.append(oneline)
    return oneline_report


def create_mailer_report(text: list, file_name: str) -> None:
    """ Writes oneline data text to mailer report file """

    with open(file_name, 'a') as the_file:
        for line in text:
            the_file.write(f"{line}\n")


def create_filtered_report(source_file: str,
                           dest_file: str, keyword: str) -> None:
    """ Function imitates bash grep for filtering text file

    """
    with open(source_file, "r") as sfile:
        with open(dest_file, "w") as dfile:
            for line in sfile:
                if re.search(keyword, line):
                    dfile.write(line)


def merge_reports(source_file: str, dest_file: str, rc: int) -> None:
    """ Function merges multiple tmp reports in final report """

    with open(dest_file, "a") as dfile:
        with open(source_file, "r") as sfile:
            dfile.write("\n \n")
            rooms_title = "Report for " + str(rc) + " rooms:\n"
            dfile.write(rooms_title)
            for line in sfile:
                dfile.write(line)
            

write_mailer_report()
