import os
import sys
import uvicorn

if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
    port = int(os.getenv("PORT", 3002))
    host = os.getenv("HOST", "0.0.0.0")
    print(f"[*] Starting NibiaaNet IAM (User, Roles, Attribute) Microservice on http://{host}:{port}")
    uvicorn.run("app.main:app", host=host, port=port, app_dir=current_dir, reload=False)
