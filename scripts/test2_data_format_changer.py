#!/usr/bin/env python3

import subprocess
import os
from datetime import datetime


TEST_SETUP_FILES = ["Ogre-raw-data-report.txt"]


def gen_folder_name() -> str:
    now = datetime.now()
    time_string = now.strftime("%Y%m%d_%H%M")
    test_name = "_test2"
    return time_string + test_name 


def crete_folder(folder_name: str) -> None:
    cwd = os.getcwd()
    print(f"current dir {cwd}")
    path = os.path.join(cwd, folder_name)
    print(f"Creating folder {path}")
    try: 
        os.mkdir(path) 
    except OSError as error: 
        print(f" {error} while creating folder {path}") 


def copy_setup_files(setup_files: list[str]) -> None:
    for setup_file in setup_files:
        cmd = f"cp ../test_setup_files/{setup_file} {setup_file}"
        print(cmd)
        status = subprocess.call(cmd, shell=True)
        print(status)
    
    # special case for this module
    cmd1 = "mkdir data"
    print(cmd1)
    status = subprocess.call(cmd1, shell=True)
    print(status)


    cmd2 = "cp Ogre-raw-data-report.txt data"
    print(cmd2)
    status = subprocess.call(cmd2, shell=True)
    print(status)
    # curr_date = "2022-11-15"
    now = datetime.now()
    curr_date = now.strftime("%Y-%m-%d")
    cmd3 = f"mv data/Ogre-raw-data-report.txt data/Ogre-raw-data-report-{curr_date}.txt"
    print(cmd3)
    status = subprocess.call(cmd3, shell=True)
    




def clone_repo(folder_name: str, branch_name="main") -> None:
    cwd = os.getcwd()
    path = os.path.join(cwd, folder_name)
    os.chdir(path)
    cmd = "git clone https://github.com/vfedotovs/sslv_web_scraper.git ."
    print(cmd)
    status = subprocess.call(cmd, shell=True)
    print(status)
    print(f"Switching to branch: {branch_name}")
    #FIXME: take users  input for test branch and switch to user input branche other whise test main


def run_code() -> None:
    cmd = "python3 src/ws/app/wsmodules/data_format_changer.py"
    print(f"Started running code: {cmd}")
    status = subprocess.call(cmd, shell=True)
    print(status)
    print("Completed running code")


def check_test() -> bool:
    cwd = os.getcwd()
    path = os.path.join(cwd, "pandas_df.csv")
    print(path)
 
    # Check whether a path pointing to a file
    isFile = os.path.isfile(path)
    return isFile


def compare_result() -> None:
    expected = check_test()
    if expected:
        print("Test 2 file pandas_df.csv exists: Pass")
    if expected == False:
        print("Test 2 file pandas_df.csv exists: Fail")


def main() -> None:
    fn = gen_folder_name()
    crete_folder(fn)
    clone_repo(fn)
    copy_setup_files(TEST_SETUP_FILES)
    run_code()
    compare_result()


main()




