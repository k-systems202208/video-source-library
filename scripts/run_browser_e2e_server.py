from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
TESTS = ROOT / "tests"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from database import connect
from metadata_importer import import_metadata
from sample_metadata import build_metadata
from server import create_server


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the VideoLibrary Playwright E2E fixture server")
    parser.add_argument("--port", type=int, default=8876)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="video-library-e2e-") as temp:
        root = Path(temp)
        database = root / "library.db"
        video_root = root / "videos"
        video_root.mkdir(parents=True, exist_ok=True)

        with connect(database) as connection:
            result = import_metadata(
                connection,
                build_metadata(work_count=12, video_count=24),
            )

        server = create_server(
            database,
            host="127.0.0.1",
            port=args.port,
            video_root=video_root,
            data_root=root,
        )
        print(
            f"Playwright E2E fixture: http://127.0.0.1:{server.server_port}/ "
            f"({result['works']} works / {result['videos']} videos)",
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
