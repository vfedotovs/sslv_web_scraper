"""
write_report is used for pdf format report generation form csv dataframe file as source
pdf report file be used as atachment in email sending module
"""
import pandas as pd
from fpdf import FPDF


# This module functional requirements:
# 1. [x] Load data from csv file exported with python pandas df
# 2. [ ] Ability to create pdf file
#   - [ ] functionality change report titles and data frames ( example multiple cities)   
#   - [x] functionality to create charts (scatter plots) from data frame
#   - [x] functionality to ave scatter plot to png file
#   - [x] functionality to Import/add .png file to pdf file 
#   - [ ] functionality to write text from data frame to pdf file
#   - [ ] functionality to Include file created date in pdf report


def create_pdf_report(city_name: str, cdate: str) -> None:
    """ This is draft function to test ability to write to create and write pdf file """
    # library help https://pyfpdf.readthedocs.io/en/latest/reference/image/index.html
    pdf = FPDF()  # A4 (210 by 297 mm)
    pdf.add_page()
    pdf.set_font('Arial', 'B', 14)
    report_title = city_name + "city apartments for sale analytics report"
    date_created = "Report created: " + cdate
    pdf.write(5, report_title)  # write str text to pdf
    pdf.ln(5)
    pdf.write(5, date_created)  # write str text to pdf
    # pdf.image("test.png", 20,10, 150) # inserts png to pdf
    pdf.ln(20)  # ads new lines
    pdf.add_page()  # adds new page
    pdf.write(3, "Basic statistics about apartments")
    test_save_df_to_png()  # calling function to generate png from df
    pdf.image("test.png")  # inserts png to pdf
    pdf.output(name="Ogre_city_report.pdf")  # generate pdf files


def test_save_df_to_png():
    """ This is draft test function to crete graph from df ans ave to png """
    df = pd.read_csv("cleaned-sorted-df.csv")
    ax = df.plot.scatter(x='Size_sqm',
                           y="Price_in_eur",
                           s=100,
                           title="All 1-4 room apartments",
                           grid=True)
    fig = ax.get_figure()
    # fi.show() # for debugging
    fig.savefig('test.png')


def test_create_scatter_plot():
    """ Function with examples how to create scatter and py chart """
    # Testing scatter chart$
    # sorted_by_sqm.plot.scatter(x='Size_sqm',y="Price_EUR",s=100,
    #                           title="All 1-4 room apartments",grid=True)
    # only_1_rooms.plot.scatter(x='Size_sqm',y="Price_EUR",s=100,
    #                          title="Only 1 room apartments",grid=True)
    # only_2_rooms.plot.scatter(x='Size_sqm',y="Price_EUR",s=100,
    #                          title="Only 2 room apartments",grid=True)
    # only_3_rooms.plot.scatter(x='Size_sqm',y="Price_EUR",s=100,
    #                          title="Only 3 room apartments",grid=True)
    # Testing charts
    # only_2_rooms.groupby(['Size_sqm']).sum().plot(kind='pie',
    #                                               subplots=True,
    #                                               figsize=(7,7),
    #                                               autopct='%1.1f%%')


# main code driver
create_pdf_report("Ogre", "2021-02-03")
test_save_df_to_png()
