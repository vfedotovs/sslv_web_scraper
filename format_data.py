import re

def main():
    oneline_report('Ogre-report.txt', 'test.txt', 'type1')


def oneline_report(source_file: str, dest_file: str, report_type: str) ->None:
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
            match_room_size = re.search("Platība:", line)
            if match_room_size:
                room_sizes.append(line.rstrip('\n'))
            if not line:
                break

    # print(urls)
    # print(room_counts)
    # print(room_sizes)
    for i in range(len(urls) - 1):
        oneline = urls[i] + " " + room_counts[i] + " " + room_sizes[i]
        print(oneline)

main()
