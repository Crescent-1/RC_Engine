"""Launch the RC Engine GUI:  python -m gui

Binds localhost only; opens the browser once the server is up.
"""

import threading
import webbrowser

import uvicorn

HOST = "127.0.0.1"
PORT = 8730


def main():
    threading.Timer(1.0, lambda: webbrowser.open(f"http://{HOST}:{PORT}")).start()
    from .app import app
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
