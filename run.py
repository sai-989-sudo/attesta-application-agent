"""Start Attesta:  python run.py   → http://127.0.0.1:8000"""
import os
import webbrowser

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    if os.environ.get("ATTESTA_NO_BROWSER") != "1":
        webbrowser.open(f"http://127.0.0.1:{port}")
    uvicorn.run("backend.main:app", host="127.0.0.1", port=port, reload=False)
