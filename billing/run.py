import os
import uvicorn
from dotenv import load_dotenv

load_dotenv()

PORT = int(os.getenv("PORT", "3003"))
HOST = os.getenv("HOST", "0.0.0.0")

if __name__ == "__main__":
    print(f"[*] Starting NibiaaNet Billing & Subscription Microservice on {HOST}:{PORT}")
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=False)
