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


    from app.wsmodules.web_scraper import scrape_website  # first debug import
    print("DEBUG: adding task to background and calling scrape_website module")
    background_tasks.add_task(scrape_website)
    print("DEBUG: sleeping 10 sec")
    time.sleep(10)


    print("DEBUG:fastapi: importing data_formater module")
    from app.wsmodules.data_formater_v14 import data_formater_main  # second debug import
    print("DEBUG: calling data_formater module")
    background_tasks.add_task(data_formater_main)
    print("DEBUG: sleeping 5 sec")
    time.sleep(5)


    print("DEBUG:fastapi: importing df_cleaner module")
    from app.wsmodules.df_cleaner  import df_cleaner_main  # third debug import
    print("DEBUG: calling data_formater module")
    background_tasks.add_task(df_cleaner_main)
    print("DEBUG: sleeping 3 sec")
    time.sleep(3)


    print("DEBUG:fastapi: importing db_worker module")
    from app.wsmodules.db_worker  import db_worker_main  # fourth  debug import
    print("DEBUG: calling data_formater module")
    background_tasks.add_task(db_worker_main)
    print("DEBUG: sleeping 3 sec")
    time.sleep(3)


    return {"message": "Completed run scrape ss.lv task for ogre city as background task"}


if __name__ =='__main__':
    uvicorn.run(app)


