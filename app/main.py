import uvicorn
from fastapi import BackgroundTasks, FastAPI
import time
from app.wsmodules.web_scraper import scrape_website
from app.wsmodules.data_formater_v14 import data_formater_main
from app.wsmodules.df_cleaner import df_cleaner_main
from app.wsmodules.db_worker import db_worker_main
from app.wsmodules.file_remover import remove_tmp_files


app = FastAPI()


@app.get("/")
def home():
    return {"FastAPI server is ready !!!"}


@app.get("/run-task/{city}")
async def run_long_task(city: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(scrape_website)
    print("DEBUG: sleeping 90 sec ... waiting for srape task to complete")
    time.sleep(90)
    background_tasks.add_task(data_formater_main)
    print("DEBUG: sleeping 5 sec .. waiting for dataformater task to complete")
    time.sleep(5)
    background_tasks.add_task(df_cleaner_main)
    print("DEBUG: sleeping 3 sec")
    time.sleep(3)
    background_tasks.add_task(db_worker_main)
    print("DEBUG: sleeping 5 sec")
    time.sleep(5)
    background_tasks.add_task(remove_tmp_files)
    return {
        "message": "Completed run scrape ss.lv task for ogre city as background task"
    }


if __name__ == "__main__":
    uvicorn.run(app)
