#!/usr/bin/env python
""" This module is sending HTTP GET request to fast_api endpints every 24H """

import logging
from logging.handlers import RotatingFileHandler
from logging import handlers
import sys
import time
import requests
import schedule


log = logging.getLogger('task_scheduler')
log.setLevel(logging.INFO)
ts_log_format = logging.Formatter(
        "%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s] : %(funcName)s: %(lineno)d: %(message)s")

ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(ts_log_format)
log.addHandler(ch)

fh = handlers.RotatingFileHandler('task_scheduler.log',
                                   maxBytes=(1048576*5),
                                   backupCount=7)
fh.setFormatter(ts_log_format)
log.addHandler(fh)


URL='http://ws:80/run-task/ogre'


def execute_ogre_task():
    """HTTP GET for run-task/ogre fast-api endpoint"""
    log.info("HTTP GET http://127.0.0.1:80/run-task/ogre")
    response = requests.get(URL)
    if response.status_code == 200:
        log.info('HTTP GET response - 200')
    elif response.status_code != 200:
        log.info('HTTP GET response failed with %s code, response.status_code')
    fast_api_response = response.text
    log.info('FAST_API Response: %s, fast_api_response')


# schedule.every().hour.do(execute_ogre_task)  # development
schedule.every().day.at("23:00").do(execute_ogre_task)  # production


while True:
    log.info('ts_loop: checking every 8 hours if cheduled task needs to run again...')
    schedule.run_pending()
    time.sleep(28800)
