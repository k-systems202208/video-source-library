# 全動画形式再生CI

## 目的

実機ライブラリに存在する動画拡張子を取りこぼさず、CIで「映像と音声の両方がブラウザ再生可能な経路を持つ」ことを検証する。

## 実ライブラリ基準

2026-09-11に作成した `video_library_list.xlsx` の動画ファイル一覧 4,869件を集計した。

| 拡張子 | 件数 |
| --- | ---: |
| MKV | 2,786 |
| MP4 | 1,898 |
| AVI | 172 |
| WEBM | 11 |
| MPG | 1 |
| FLV | 1 |
| 合計 | 4,869 |

この集合を `tests/fixtures/real_library_video_extensions.json` に固定し、通常ユニットテストでもスキャナ認識対象との一致を確認する。

## CIの実メディア検証

`playback-formats` ジョブでFFmpeg / ffprobeを用意し、実動画は使わず各拡張子の短い合成動画を生成する。

- MP4: H.264 + AAC（直接再生系）
- WEBM: VP9 + Opus（直接再生系）
- MKV: H.264 + AC3（互換変換系）
- AVI: MPEG-4 Part 2 + MP3（互換変換系）
- MPG: MPEG-2 Video + MP2（互換変換系）
- FLV: FLV1 + MP3（互換変換系）

各入力を `playback_compat.prepare_browser_playback()` に通し、最終出力について次を検証する。

1. 映像ストリームが存在する
2. 音声ストリームが存在する
3. MP4出力は H.264 + AAC
4. WebM直接出力は VP8 / VP9 / AV1 + Opus / Vorbis
5. FFmpegで映像・音声を実際にデコードできる
6. 実ライブラリ6拡張子のうち1種類でも未検証ならCI失敗

## 方針

- 実動画はCIへアップロードしない
- 元動画は変更しない
- 今後実ライブラリに新しい拡張子が追加された場合はfixtureと再生経路を同時に更新する
- このCIを、AVI等の互換再生機能を追加・変更する際の必須ゲートとする
