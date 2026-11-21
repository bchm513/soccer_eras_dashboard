"""Serve the dashboard and print its link.

    python serve.py              # opens http://localhost:8000 in your default browser
    python serve.py 8080         # another port
    python serve.py --no-open    # just print the link
"""
import http.server
import socketserver
import sys
import webbrowser
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent / "dashboard"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASHBOARD), **kwargs)

    def log_message(self, *args):          # keep the terminal quiet
        pass


def main(argv: list[str]) -> None:
    port = next((int(a) for a in argv if a.isdigit()), 8000)
    url = f"http://localhost:{port}"
    try:
        server = socketserver.ThreadingTCPServer(("", port), Handler)
    except OSError:
        raise SystemExit(f"Port {port} is in use. Try another: python serve.py {port + 1}")
    with server:
        print(f"\n  Eras of the Game is running at  {url}\n")
        if "--no-open" not in argv:
            webbrowser.open(url)           # your default browser, via the operating system
            print("  Opened in your default browser. Press Ctrl+C to stop.\n")
        else:
            print("  Press Ctrl+C to stop.\n")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("  Stopped.")


if __name__ == "__main__":
    main(sys.argv[1:])
