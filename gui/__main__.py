"""Launch the RC Engine GUI:  python -m gui

Binds localhost by default; opens the browser once the server is up.
Set RC_GUI_HOST=0.0.0.0 to also serve over Tailscale/LAN (the app has no
auth of its own — only expose it on trusted networks like a tailnet).
"""

import os
import threading
import webbrowser

import uvicorn

HOST = os.environ.get("RC_GUI_HOST", "127.0.0.1")
PORT = int(os.environ.get("RC_GUI_PORT", "8730"))


def main():
    browse_host = "127.0.0.1" if HOST == "0.0.0.0" else HOST
    threading.Timer(1.0, lambda: webbrowser.open(f"http://{browse_host}:{PORT}")).start()
    from .app import app
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
