
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
    remove_tmp_files()

    # Check that the files were deleted
    assert not os.path.exists("test_file1.txt")
    assert not os.path.exists("test_file2.txt")
    assert not os.path.exists("test_file3.txt")


def test_gen_debug_subject():
    # Set the release global variable
    global release
    release = "v1.4.9"

    # Test the function
    assert gen_debug_subject() == "Ogre City Apartments for sale from ss.lv webscraper v1.4.9 YYYYMMDD_HHMM"

    # Check that the function returns a different value each time it is called
    assert gen_debug_subject() != gen_debug_subject(
