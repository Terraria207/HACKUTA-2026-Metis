import argparse

from metis.server import serve

parser = argparse.ArgumentParser(prog="python -m metis", description="Run the Metis server with its supervisor.")
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=8000)
parser.add_argument("--no-browser", action="store_true", help="Do not open the browser")
args = parser.parse_args()
serve(args.host, args.port, open_browser=not args.no_browser)
