""" FIXME module docstring """
from datetime import datetime
from time import strftime
from fpdf import FPDF


class Report():
    """ docsting """

    def __init__(self, report_type, file_name):
        self.report_type = report_type
        self.file_name = file_name
        self.pdf = FPDF()
        self.pdf.add_page()
        self.pdf.set_font('Arial', 'B', 16)
        #self.insert_header(self.report_type)
        
    def insert_header(self, report_type: str) -> None:
        """ docstring """
        todays_date = datetime.today().strftime('%Y-%m-%d %H:%M')
        report_title = f"Ogre city apartments for sale {report_type}"
        date_created = f"Report date: {todays_date}"
        self.pdf.write(5, report_title)
        self.pdf.ln(5)
        self.pdf.write(5, date_created)
        self.pdf.ln(5)

    def insert_text_segment(self, text_lines: str) -> None:
        """ docstring """
        self.pdf.ln(5) # line break
        self.pdf.write(5, text_lines)
        self.pdf.ln(5)            

    def insert_error_msg(self, msg: str) -> None:
        """ docstring """
        self.pdf.ln(5) # line break
        self.pdf.write(5, msg)
        self.pdf.ln(5)


    def insert_images(self, images: list) -> None:
        """ docstring """
        for image in images:
            self.pdf.image(image, x=10, y=10, w=100, h=100)
            self.pdf.ln(5)

    def save_report(self, file_name: str) -> None:
        """ docstring """
        self.pdf.output(file_name, 'F')
