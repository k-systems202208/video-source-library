from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "windows-installer" / "src" / "launcher.py"


class LauncherLayoutV093Tests(unittest.TestCase):
    def test_critical_operations_are_before_expandable_scan_area(self) -> None:
        text = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn('WINDOW_GEOMETRY = "780x690"', text)
        operations = text.index('operations_frame = ttk.Frame(main)')
        audit = text.index('text="全件再生監査"')
        scan = text.index('scan_box = ttk.LabelFrame(main, text="起動スキャン"')
        self.assertLess(operations, scan)
        self.assertLess(audit, scan)
        self.assertIn('operations_frame.pack(fill="x", pady=(0, 10))', text)
        self.assertIn('scan_box.pack(fill="both", expand=True)', text)
        self.assertNotIn('footer = ttk.Frame(main)', text)

    def test_standard_height_uses_compact_scan_log(self) -> None:
        text = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn('self.log_text = tk.Text(scan_box, height=4', text)
        self.assertNotIn('self.log_text = tk.Text(scan_box, height=8', text)


if __name__ == "__main__":
    unittest.main()
