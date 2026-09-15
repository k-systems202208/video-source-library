from pathlib import Path

p = Path("tests/test_release_consistency.py")
text = p.read_text(encoding="utf-8")
old = '        self.assertEqual(APP_VERSION, "1.0.0")\n'
new = '        self.assertEqual(APP_VERSION, "1.1.0")\n'
if old not in text:
    raise SystemExit("release consistency version marker not found")
p.write_text(text.replace(old, new, 1), encoding="utf-8")

p = Path("tests/test_credits_people_ui_v110.py")
text = p.read_text(encoding="utf-8")
old = '        self.assertIn("/^#\\/person\\/(.+)$/", html)\n'
new = '        self.assertIn(r"/^#\\/person\\/(.+)$/", html)\n'
if old not in text:
    raise SystemExit("route assertion marker not found")
p.write_text(text.replace(old, new, 1), encoding="utf-8")
