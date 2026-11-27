from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "windows-installer" / "src" / "video-library.html"


class VideoLibraryInlineScriptSyntaxTests(unittest.TestCase):
    def test_inline_javascript_parses_with_node(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is not installed")

        html = HTML.read_text(encoding="utf-8")
        scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", html, flags=re.IGNORECASE | re.DOTALL)
        self.assertGreaterEqual(len(scripts), 1)

        source = "\n;\n".join(scripts)
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "video-library-inline.js"
            script.write_text(source, encoding="utf-8")
            completed = subprocess.run(
                [node, "--check", str(script)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )

        self.assertEqual(
            completed.returncode,
            0,
            msg="video-library.html inline JavaScript syntax error:\n" + completed.stdout,
        )


if __name__ == "__main__":
    unittest.main()
