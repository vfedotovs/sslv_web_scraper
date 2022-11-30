from Report import Report


segments = []
images = [ ]
#segments = [ 'room_stats.txt',
#             'house_stats.txt',
#             'apt_loc_stats.txt' ]


#images = [ 'single_room_sqm_prices.png',
#           'double_room_sqm_prices.png',
#           'triple_room_sqm_prices.png',
#           'quad_room_sqm_prices.png',
#           'all_room_sqm_prices.png' ]


def gen_report(report_type: str, file_name: str, segments: list, images: list) -> None:
    """
    Generate report.
    """
    report = Report(report_type, file_name)
    report.insert_header('Daily Report')
    if len(segments) > 0:
        for segment in segments:
            report.insert_text_segment(segment)
    if len(segments) == 0:
        report.insert_error_msg('No segments to display')
#    if len(images) > 0:
#        report.insert_images(images)
    if  len(images) == 0:
        report.insert_error_msg('No images to display')
    report.save_report('Ogre_daily.pdf')


gen_report('Daily', 'Ogre_daily.pdf', segments, images)

