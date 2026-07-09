#!/usr/bin/env python3
"""
This module is sending HTTP GET requests to fast_api endpints
every day at 0:40 AM UTC

It solves triggering task using cronjob on schedule problem with multiple
container application
"""

import logging
from logging.handlers import RotatingFileHandler
import sys
import time
import os
import requests
import schedule
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread


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

# Dynamic city support for multi-city (reads CITY from .env.<city>)
city = os.getenv("CITY", "ogre").lower()
URL = f"http://ws:8000/run-task/{city}"


class HealthCheckHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for health checks"""

    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status":"healthy"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress default logging to avoid cluttering logs"""
        pass


def run_health_server():
    """Run health check server in background thread"""
    server = HTTPServer(('0.0.0.0', 8080), HealthCheckHandler)
    log.info("Health check server started on port 8080")
    server.serve_forever()


def execute_task():
    """
    Executes an HTTP GET request to the run-task/{city} FastAPI endpoint.

    This function sends an HTTP GET request to the dynamic URL for the
    current CITY. It logs information about the request,
    response, and any errors that may occur.

    Returns:
        None

    Raises:
        requests.Timeout: If the HTTP request times out.
        requests.RequestException: If an error occurs during the HTTP request.

    Note:
        The CITY env var (from .env.<city>) determines the endpoint.
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
    Run the task scheduler for the current CITY.

    This function initializes the task scheduler to execute the task
    for the current city. It sets up a daily scheduled task
    to trigger an HTTP GET call to the 'run-task/{city}' endpoint
    at 0:40 AM UTC. The scheduler continuously checks for pending
    tasks and runs them.

    The function enters a loop that periodically checks the scheduler
    for pending tasks. After each check, it sleeps for 3600 seconds
    (1 hour) before checking again. The loop continues indefinitely.

    Note:
        - The CITY environment variable (from .env.<city>) controls
          which city endpoint is called.
        - Ensure that execute_task properly handles the HTTP GET call.
        - The 'log' object must be defined in the global scope.

    Returns:
        None

    """
    log.info("--- Started task_scheduler module ---")

    # Start health check server in background thread
    health_thread = Thread(target=run_health_server, daemon=True)
    health_thread.start()

    schedule.every().day.at("00:40").do(execute_task)
    while True:
        # log.info("Sleeping for 3600 seconds before checking if HTTP GET to "
        #         "'run-task/ogre' endpoint needs to trigger")
        # Check for pending tasks in the scheduler and run them
        schedule.run_pending()
        # Sleep for 1 hour (3600 seconds) before the next check
        time.sleep(600)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger(__name__)

    run_task_scheduler()
