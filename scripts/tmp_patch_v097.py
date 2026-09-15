from pathlib import Path

# Exclude known episode mismatches from replacement candidates.
p = Path("windows-installer/src/playback_audit.py")
text = p.read_text(encoding="utf-8")
old = '''        score, reason = _repair_candidate_score(source, path)\n        ranked.append(\n'''
new = '''        score, reason = _repair_candidate_score(source, path)\n        if reason == "EPISODE_MISMATCH":\n            continue\n        ranked.append(\n'''
if old not in text:
    raise SystemExit("repair candidate anchor not found")
text = text.replace(old, new, 1)
p.write_text(text, encoding="utf-8")

Path("windows-installer/src/app_version.py").write_text('APP_VERSION = "0.9.7"\n', encoding="utf-8")

p = Path("windows-installer/installer/VideoLibrary.iss")
text = p.read_text(encoding="utf-8")
if "0.9.6" not in text:
    raise SystemExit("installer version 0.9.6 not found")
p.write_text(text.replace("0.9.6", "0.9.7"), encoding="utf-8")

p = Path("tests/test_release_consistency.py")
text = p.read_text(encoding="utf-8")
if "0.9.6" not in text:
    raise SystemExit("release consistency 0.9.6 not found")
p.write_text(text.replace("0.9.6", "0.9.7"), encoding="utf-8")

readme = Path("README.md")
text = readme.read_text(encoding="utf-8")
anchor = "対象動画拡張子: `.mkv`, `.mp4`, `.avi`, `.webm`, `.mpg`, `.flv`, `.m4v`, `.mov`, `.wmv`"
section = '''### 0.9.6〜0.9.7: 元データ修復候補の安全化\n- 0.9.6: 元データ異常と同じフォルダーにある実動画をffprobe確認し、修復候補として最大3件提示\n- 0.9.7: エピソード番号が明確に不一致な別話は修復候補から除外し、置換可能性のある候補だけを「候補あり」に集計\n- 実ライブラリ24件では、0.9.6で表示された9件の候補はすべて別エピソードだったため、0.9.7の期待値は「候補あり0 / 候補なし24」\n- 候補探索は読み取り専用で、元動画・字幕・SQLite・PlaybackCacheを変更しない\n\n'''
if "### 0.9.6〜0.9.7: 元データ修復候補の安全化" not in text:
    if anchor not in text:
        raise SystemExit("README anchor not found")
    text = text.replace(anchor, section + anchor, 1)
readme.write_text(text, encoding="utf-8")
