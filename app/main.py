""" This module is processing HTTP get requsts to scrape property data form ss.lv"""


from datetime import datetime
import logging
from logging import handlers
from logging.handlers import RotatingFileHandler
import os
import sys
import uvicorn
from fastapi import BackgroundTasks, FastAPI
from app.wsmodules.web_scraper import scrape_website
from app.wsmodules.data_formater_v14 import data_formater_main
from app.wsmodules.df_cleaner import df_cleaner_main
from app.wsmodules.db_worker import db_worker_main
from app.wsmodules.analytics import analytics_main
from app.wsmodules.sendgrid_mailer import sendgrid_mailer_main
#from app.wsmodules.file_remover import remove_tmp_files



log = logging.getLogger('')
log.setLevel(logging.DEBUG)
fa_log_format = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s] : %(funcName)s: %(lineno)d: %(message)s")

ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(fa_log_format)
log.addHandler(ch)

fh = handlers.RotatingFileHandler('fast_api.log', maxBytes=(1048576*5), backupCount=7)
fh.setFormatter(fa_log_format)
log.addHandler(fh)

app = FastAPI()
CITY_NAME = 'Ogre'


@app.get("/")
def home():
    """Test enpoint to verify if fast-api is live"""
    return {"FastAPI server is ready !!!"}


@app.get("/run-task/{city}")
async def run_long_task(city: str, background_tasks: BackgroundTasks):
    """ Endpint to trigger scrape, format and insert data in DB"""
    task_run_state = task_runned_today(CITY_NAME)
    if task_run_state:
        log.info("EXIT: will not call ws_worker module because task was run last 24H")
        return {"message": "Task already run in last 24H will not run today again"}
    log.info("Sent scrape_website task to background - time to complete 150 sec")
    background_tasks.add_task(scrape_website)
    log.info("Sent data_formater_main task to background: TTC < 2 sec")
    background_tasks.add_task(data_formater_main)
    log.info("Sent df_cleaner_main task to background: TTC < 2 sec")
    background_tasks.add_task(df_cleaner_main)
    log.info("Sent db_worker_main task to background: TTC < 3 sec")
    background_tasks.add_task(db_worker_main)
    log.info("Sent analytics_main task to background: TTC < 5 sec")
    background_tasks.add_task(analytics_main)
    log.info("Sent sendgrid_mailer task to background: TTC < 5 sec")
    background_tasks.add_task(sendgrid_mailer_main)
    log.info("Send all taks to background completed")
    return {
            "message": "FAST_API_REPLAY scrape Ogre city sent as background task"
    }


def task_runned_today(city_name):
    """Checks if file Ogre-raw-data-report-YYYY-MM-DD.txt with todays data exist"""
    todays_date = datetime.today().strftime('%Y-%m-%d')
    target_filename = city_name + '-raw-data-report-' + todays_date + '.txt'
    if not os.path.exists('data'):
        os.makedirs('data')
    for filename in os.listdir("data"):
        if filename == target_filename:
            log.info('File %s found, task for Ogre has run today', target_filename)
            return True
    log.info('File %s was not found, running scrape task for Ogre city', target_filename)
    return False


if __name__ == "__main__":
    uvicorn.run(app)
