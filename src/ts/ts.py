#!/usr/bin/env python3
"""
This module is sending HTTP GET requests to fast_api endpints
every day at 0:30 AM.

It solves triggering task using cronjob on schedule problem with multiple
container application
"""

import logging
from logging.handlers import RotatingFileHandler
import sys
import time
import requests
import schedule


log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

LOG_FILE = "task_scheduler.log"
# Create a rotating file handler
file_handler = RotatingFileHandler(LOG_FILE,
                                   maxBytes=1024 * 1024,
                                   backupCount=9)
file_formatter = logging.Formatter(
    "%(asctime)s [%(threadName)-12.12s] "
    "[%(levelname)-5.5s] : %(funcName)s: %(lineno)d: %(message)s")

file_handler.setFormatter(file_formatter)
log.addHandler(file_handler)

# Create a stdout (console) handler
stdout_handler = logging.StreamHandler(sys.stdout)
stdout_formatter = logging.Formatter(
    "%(asctime)s [%(threadName)-12.12s] "
    "[%(levelname)-5.5s] : %(funcName)s: %(lineno)d: %(message)s")

stdout_handler.setFormatter(stdout_formatter)
log.addHandler(stdout_handler)

URL = 'http://ws:80/run-task/ogre'


def execute_ogre_task():
    """
    Executes an HTTP GET request to the run-task/ogre FastAPI endpoint.

    This function sends an HTTP GET request to the specified URL for the
    run-task/ogre FastAPI endpoint. It logs information about the request,
    response, and any errors that may occur.

    Returns:
        None

    Raises:
        requests.Timeout: If the HTTP request times out.
        requests.RequestException: If an error occurs during the HTTP request.

    Note:
        This function assumes that 'URL' and 'log'
        are defined in the global scope.
    """
    timeout_seconds = 30
    fast_api_response = None  # Default value

    try:
        log.info("HTTP GET %s", URL)
        response = requests.get(URL, timeout=timeout_seconds)
        if response.status_code == 200:
            log.info('HTTP GET response - 200')
        else:
            log.info(
                'HTTP GET response failed with %s code', response.status_code)
        fast_api_response = response.text
        log.info("FAST_API Response: %s", fast_api_response)

    except requests.Timeout:
        log.error("Request timed out after %s seconds.", timeout_seconds)
    except requests.RequestException as request_exception:
        log.error("Request error: %s", str(request_exception))
    log.info("FAST_API Response: %s ", fast_api_response)


def run_task_scheduler():
    """
    Run the task scheduler for executing the 'execute_ogre_task' function.

    This function initializes the task scheduler to execute the
    'execute_ogre_task' function. It sets up a daily scheduled task
    to trigger an HTTP GET call to the 'run-task/ogre' endpoint
    at 0:30 AM. The scheduler continuously checks for pending
    tasks and runs them.

    The function enters a loop that periodically checks the scheduler
    for pending tasks. After each check, it sleeps for 3600 seconds
    (1 hour) before checking again. The loop continues indefinitely.

    Note:
        - Ensure that the 'execute_ogre_task' function is implemented
          and properly handles the HTTP GET call to the
          'run-task/ogre' endpoint.
        - The 'log' object must be defined in the global scope.

    Returns:
        None

    """
    log.info("--- Started task_scheduler module ---")
    schedule.every().day.at("00:30").do(execute_ogre_task)
    while True:
        log.info("Sleeping for 3600 seconds before checking if HTTP GET to "
                 "'run-task/ogre' endpoint needs to trigger")
        # Check for pending tasks in the scheduler and run them
        schedule.run_pending()
        # Sleep for 1 hour (3600 seconds) before the next check
        time.sleep(3600)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger(__name__)

    run_task_scheduler()
