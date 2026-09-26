"""python -m trading_universe.api [--port 8000] : serves the API and the built website."""

import argparse
import os

import uvicorn


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m trading_universe.api")
    ap.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    a = ap.parse_args()
    uvicorn.run("trading_universe.api.server:app", host=a.host, port=a.port)


if __name__ == "__main__":
    main()
