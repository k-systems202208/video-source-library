# metadata

`video_library.json` は利用者の実ライブラリ情報（作品・ファイル名・相対パス等）を含むため、公開GitHubにはコミットしません。

実機検証時だけ、このフォルダーへローカル配置してください。

```text
metadata/video_library.json
```

`.gitignore` で明示的に除外されています。

実データ検証:

```powershell
python scripts\validate_phase1.py metadata\video_library.json
```
