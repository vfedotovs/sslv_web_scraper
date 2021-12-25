from app.wsmodules import web_scraper
from app.wsmodules import data_formater
from app.wsmodules import db_worker


def ws_worker_main():
    web_scraper
    data_formater
    db_worker


ws_worker_main()
