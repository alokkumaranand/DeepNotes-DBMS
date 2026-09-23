"""Start the local application: python -m deepnotes [--demo] [--port 8000]."""
import argparse
import os
import uvicorn


def main():
    parser = argparse.ArgumentParser(description="Run DeepNotes locally (one backend process).")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--demo", action="store_true", help="Use explicit deterministic demo output, not a real model")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if args.demo:
        os.environ["DEEPNOTES_DEMO"] = "true"
    uvicorn.run("deepnotes.api:create_app", factory=True, host="127.0.0.1", port=args.port, workers=1)


if __name__ == "__main__":
    main()
