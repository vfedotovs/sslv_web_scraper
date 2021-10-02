import uvicorn
from fastapi import BackgroundTasks, FastAPI

# Example how to import my modules
# Folder app > folder wsmodules > web_scraper.py function scrape_website()
from app.wsmodules.ws_worker import ws_worker_main

app = FastAPI()


@app.get("/")
def home():
    return {'FastAPI server is ready !!!'}


@app.get("/run-task/{city}")
async def run_long_task(city: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(ws_worker_main)
    return {"message": "run task for ogre  city in the background"}


if __name__ =='__main__':
    uvicorn.run(app)


