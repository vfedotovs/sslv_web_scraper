#!/usr/bin/env python

import requests
import schedule
import time
#import sys
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
import os

logger = logging.getLogger('task_scheduler')
logger.setLevel(logging.INFO)
fh = logging.handlers.RotatingFileHandler('task_scheduler.log', maxBytes=1000000, backupCount=10)
fh.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s: %(name)s: %(levelname)s: %(funcName)s: %(lineno)d: %(message)s')
fh.setFormatter(formatter)
logger.addHandler(fh)






#url='https://www.ss.lv/lv/real-estate/flats/ogre-and-reg/ogre/sell/'
url='http://ws:80/run-task/ogre'

def execute_ogre_task():
    logger.info("Trying to get http://127.0.0.1:80/run-task/ogre url ...")
    response = requests.get(url)
    if response.status_code == 200:
        print("Success! - 200")
        logger.info("GET  http://127.0.0.1:80/run-task/ogre Success! - 200")
        print("GET http://127.0.0.1:80/run-task/ogre Success! - 200")
    elif response.status_code == 404:
        print("Not Found. - 404")
    logger.info("Completed Ogre city apartments for sale scraping task ...")
    print("Completed ogre scraping task ...")

schedule.every(60).seconds.do(execute_ogre_task)

while True:
    print("Started task scheduler trigger get ss.lv every 60 sec , beat every 10 sec ...")
    logger.info("Task scheduler is running trigger GET ss.lv every 60 sec , beat every 10 sec ...")
    schedule.run_pending()
    time.sleep(10)




