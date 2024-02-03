from src.ws.app.wsmodules.sendgrid_mailer import gen_debug_subject
from src.ws.app.wsmodules.sendgrid_mailer import remove_tmp_files
import os
from datetime import datetime


def test_remove_tmp_files():
    # Create some test files
    with open("test_file1.txt", "w") as f:
        f.write("Hello, world!")
    with open("test_file2.txt", "w") as f:
        f.write("Hello, world!")
    with open("test_file3.txt", "w") as f:
        f.write("Hello, world!")

    # Set the data_files global variable
    global data_files
    data_files = ["test_file1.txt", "test_file2.txt", "test_file3.txt"]

    # Test the function
    remove_tmp_files(data_files)

    # Check that the files were deleted
    assert not os.path.exists("test_file1.txt")
    assert not os.path.exists("test_file2.txt")
    assert not os.path.exists("test_file3.txt")


def test_gen_debug_subject():
    # Set the release global variable
    global release
    release = "v1.4.12"
    now = datetime.now()
    date_time_id = now.strftime("%Y%m%d_%H%M")
    subject_title = "Ogre City Apartments for sale from ss.lv webscraperv1.4.12 " + date_time_id

    # Test the function
    assert gen_debug_subject() == subject_title
