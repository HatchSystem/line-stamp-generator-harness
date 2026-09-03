# 静止スタンプ用コマンド

## プロジェクト

ハーネスのルートで実行する。`scripts/` は `.claude/skills/line-stamp-generator/scripts/` を指す。

```powershell
python scripts/project.py list                                             # 進行中一覧（* が選択中）
python scripts/project.py new --slug usagi --source photo --count 16 --text yes --text-mode font   # 作成して選択
python scripts/project.py use usagi                                        # 既存を選択
python scripts/project.py status                                           # 選択中の SESSION
```

`--slug` は英小文字・数字・ハイフンのみ（実名は使わない）。`--source` は `photo`（人物写真をキャラ化）か `character`（既存キャラを踏襲）。`--count` は 8/16/24/32/40 のみ。`--text-mode` は `font`（埋め込みフォント、既定）か `ai`（生成AIが文字を描く）。既存 slug への `new` は拒否される。

以降のコマンドは `projects/<slug>/` へ移動して実行する。

## キャラクター層

背景が既に透過なら `--remove-light-background` を付けない。

```powershell
python scripts/preprocess_character.py raw/stamp01.png characters/stamp01.png --remove-light-background --outline 10
```

`text_mode: ai`（文字が画像に含まれる）では穴補正が文字のカウンターを埋めるため `--no-fill-holes` を付ける。

```powershell
python scripts/preprocess_character.py raw/stamp01.png characters/stamp01.png --remove-light-background --outline 10 --no-fill-holes
```

この処理は文字合成前だけに使う。全体合成画像へ再適用しない。

## 文字合成

[static-manifest.example.json](static-manifest.example.json) を作業場所へコピーし、`text_mode`、フォント、色、セリフ、キャラクター画像を設定する。`items[].text` は両方式で承認済みセリフを一字一句そのまま書く（`ai` では検査の正解として使う）。

```powershell
python scripts/compose_static.py --manifest manifest.json --outdir stamps --character-layer-dir character-layers --text-layer-dir text-layers
```

- `text_mode: font` — フォントで文字を描画する（既定）
- `text_mode: ai` — 文字を描かず、文字入りのキャラクター画像をそのまま配置する。文字帯の制約と縮小後の穴補正は外れる
- `text_mode: none` — 文字なし

## 文字検査（`text_mode: ai` のみ）

生成AIは誤字・脱字・鏡文字を出す。合成後に OCR で照合し、報告を版付きで残す。

```powershell
python scripts/verify_text.py --manifest manifest.json --dir stamps --review-dir review          # 全点
python scripts/verify_text.py --manifest manifest.json --dir stamps --review-dir review --only 1 # P4 の 01 だけ
```

- exit 0: 全点 `match`。exit 1: `mismatch` あり（該当番号を再生成）。exit 2: OCR 不可（全点を目視）
- `near` は OCR ノイズの可能性。エージェントが画像を読んで判断材料をユーザーへ出す
- OCR 結果だけで合格にしない。エージェントが各画像の文字を読み上げ、ユーザーが「全点正しい / 誤字あり（番号）」で承認して初めて SESSION `text_check: ok` にする
- 日本語 OCR には tesseract 本体と `jpn.traineddata` が必要（`pip install pytesseract`）。無い環境では exit 2 になり、目視承認だけで判定する

## 確認一覧

修正版では必ず出力名の版を上げる。

```powershell
python scripts/make_contact_sheet.py --input stamps --output review/review-v01.png --cols 4
```

## 梱包と検証

```powershell
python scripts/package_static.py --stamps stamps --character-dir character-layers --outdir submit --count 16 --zip-name line-stamp-submit.zip
python scripts/validate_pack.py --dir submit --count 16 --character-dir character-layers --zip submit/line-stamp-submit.zip
```

`text_mode: ai` では `--text-mode ai` を付ける。文字のカウンターを穴と誤判定しないよう穴検査をスキップし、代わりに濃色背景の確認一覧を目視する。

`validate_pack.py` は文字の自然なカウンターを切り抜き漏れと誤判定しないよう、キャラクター単独レイヤーへ微小穴検査を行う。

## 公開前チェック

[submission.example.json](submission.example.json) を `meta/submission.json` へコピーして埋め、SESSION と ZIP を合わせて検査する。

```powershell
python scripts/check_publish_ready.py --session SESSION.md --submission meta/submission.json --zip submit/line-stamp-submit.zip
```

エラー0で P7 のメタ案提示、承認後に [publish.md](publish.md) へ進む。
