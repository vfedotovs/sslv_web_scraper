import re


def create_mailer_report():

    text_data = create_oneline_report('Ogre-raw-data-report.txt', 'test.txt', 'type1')
    create_mailer_report(text_data, 'Mailer_report.txt')


def create_oneline_report(source_file: str, dest_file: str, report_type: str) ->None:
    """ TODO decription

    Args:
        #TODO

    Returns:
        None

    """
    #TODO implement me
    # Requires
    # number: url  :  filtered room count : street: house type: price
    #
    urls = []
    room_counts = []
    room_sizes = []
    room_streets = []
    room_prices = []
    oneline_report = []
    # Read data from file + RE
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
                room_sizes.append(line.rstrip('\n'))
            if not line:
                break

    for i in range(len(urls) - 1):
        oneline = urls[i] + " " + room_counts[i] + " " + room_sizes[i] + " " + room_streets[i] + "   " + room_prices[i]
        # print(oneline)
        oneline_report.append(oneline)
    return oneline_report



def create_mailer_report(text: list,file_name: str) ->None:
    """ Writes oneline data text to mailer report file """

    with open(file_name, 'a') as the_file:
        for line in text:
            the_file.write(f"{line}\n")


create_mailer_report()
