import uvicorn
from fastapi import BackgroundTasks, FastAPI
import time

# Example how to import my modules
# Folder app > folder wsmodules > web_scraper.py function scrape_website()
#from app.wsmodules.ws_worker import ws_worker_main
print("fastapi 1: before import of scrape_website")
#from app.wsmodules.db_worker import db_worker_main


print("fastapi 2: before fastapi app object is created ")
app = FastAPI()


@app.get("/")
def home():
    return {'FastAPI server is ready !!!'}


print("fastapi 3: before http /run-task/{city} call ")
@app.get("/run-task/{city}")
async def run_long_task(city: str, background_tasks: BackgroundTasks):
    print("DEBUG:fastapi; recieved http request on endpoint /run-task/ogre")
    print("DEBUG:fastapi: importing scrape_website module")
    from app.wsmodules.web_scraper import scrape_website
    print("DEBUG: calling scrape_website module")
    background_tasks.add_task(scrape_website)
    print("DEBUG: sleeping 30 sec")
    time.sleep(30)


    print("DEBUG:fastapi: importing data_formater module")
    from app.wsmodules.data_formater import create_mailer_report
    print("DEBUG: calling data_formater module")
    background_tasks.add_task(create_mailer_report)

    print("DEBUG: sleeping 30 sec")
    time.sleep(30)
    #print("DEBUG: calling db_worker_main module")
    #background_tasks.add_task(db_worker_main)
    return {"message": "run task for ogre  city in the background"}


if __name__ =='__main__':
    uvicorn.run(app)


