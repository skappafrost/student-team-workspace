import os

os.environ["DATABASE_URL"] = "sqlite:///./stw_smoke.db"

import uvicorn

from app import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)
