# from app.wsmodules.data_formater_v14 import get_file_path


# Trigger CICD 1.5.4 2024-09-08:T09:00
# Trigger CICD 1.5.4 2024-09-08:T09:24

def test_create_file(tmpdir):
    p = tmpdir.mkdir("sub").join("hello.txt")
    p.write("content")
    assert p.read() == "content"
    assert len(tmpdir.listdir()) == 1


# def test_input_file_exists():
#    """TODO"""
#    pass


# def test_ouput_file_exists():
#    """TODO"""
#    #output = calc.sum(2,4)
#    #assert output == 6
#    pass
