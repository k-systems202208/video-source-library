from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str, label: str) -> None:
    p = ROOT / path
    text = p.read_text(encoding='utf-8')
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'{label}: expected 1 match, got {count}')
    p.write_text(text.replace(old, new, 1), encoding='utf-8')


# Phase 3 HTTP tests use arbitrary bytes and intentionally test Range semantics,
# not FFmpeg compatibility. Keep that contract isolated from the new layer.
replace(
    'tests/test_phase3.py',
    'import unittest\nfrom pathlib import Path\n',
    'import unittest\nfrom pathlib import Path\nfrom unittest import mock\n',
    'phase3 mock import',
)
replace(
    'tests/test_phase3.py',
    'from scanner import latest_scan_status, normalize_relative_path, resolve_video_file, scan_library\nfrom server import create_server, parse_range_header\n',
    'from scanner import latest_scan_status, normalize_relative_path, resolve_video_file, scan_library\nfrom playback_compat import PlaybackPreparation\nimport server as server_module\nfrom server import create_server, parse_range_header\n',
    'phase3 playback imports',
)
replace(
    'tests/test_phase3.py',
    "        self.server=create_server(self.db_path,host='127.0.0.1',port=0,video_root=self.video_root); self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start(); self.base_url=f'http://127.0.0.1:{self.server.server_port}'\n    def tearDown(self): self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2); self.temp.cleanup()\n",
    "        self.playback_patch=mock.patch.object(server_module,'prepare_browser_playback',side_effect=lambda source,extension,video_codec,audio_codec,cache_dir,**kwargs:PlaybackPreparation(path=Path(source),content_type='video/mp4',transcoded=False)); self.playback_patch.start()\n        self.server=create_server(self.db_path,host='127.0.0.1',port=0,video_root=self.video_root); self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start(); self.base_url=f'http://127.0.0.1:{self.server.server_port}'\n    def tearDown(self): self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2); self.playback_patch.stop(); self.temp.cleanup()\n",
    'phase3 runtime mock',
)

# 0.7.8 Matroska HTTP tests intentionally validate same-size in-memory header
# rewriting. Bypass 0.9.0 transcoding so that regression remains meaningful.
replace(
    'tests/test_japanese_audio_http_v078.py',
    'import unittest\nfrom pathlib import Path\n',
    'import unittest\nfrom pathlib import Path\nfrom unittest import mock\n',
    'v078 mock import',
)
replace(
    'tests/test_japanese_audio_http_v078.py',
    'from metadata_importer import import_file\nfrom sample_metadata import build_metadata\nfrom server import create_server\n',
    'from metadata_importer import import_file\nfrom playback_compat import PlaybackPreparation\nfrom sample_metadata import build_metadata\nimport server as server_module\nfrom server import create_server\n',
    'v078 playback imports',
)
replace(
    'tests/test_japanese_audio_http_v078.py',
    '''        self.server = create_server(\n            self.db_path,\n            host="127.0.0.1",\n            port=0,\n            video_root=self.video_root,\n        )\n''',
    '''        self.playback_patch = mock.patch.object(\n            server_module,\n            "prepare_browser_playback",\n            side_effect=lambda source, extension, video_codec, audio_codec, cache_dir, **kwargs: PlaybackPreparation(\n                path=Path(source), content_type="video/x-matroska", transcoded=False\n            ),\n        )\n        self.playback_patch.start()\n        self.server = create_server(\n            self.db_path,\n            host="127.0.0.1",\n            port=0,\n            video_root=self.video_root,\n        )\n''',
    'v078 runtime mock setup',
)
replace(
    'tests/test_japanese_audio_http_v078.py',
    '''        self.thread.join(timeout=2)\n        self.temp.cleanup()\n''',
    '''        self.thread.join(timeout=2)\n        self.playback_patch.stop()\n        self.temp.cleanup()\n''',
    'v078 runtime mock teardown',
)

replace(
    'tests/test_release_consistency.py',
    'self.assertEqual(APP_VERSION, "0.8.0")',
    'self.assertEqual(APP_VERSION, "0.9.0")',
    'release version',
)

print('legacy tests isolated from 0.9.0 transcoding')
