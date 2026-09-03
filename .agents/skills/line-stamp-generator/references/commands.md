# 静止スタンプ用コマンド

## プロジェクト

すべてハーネスのルートで実行する。公開 CLI は `scripts/line_stamp.py` で、スキル内部の Python ファイルを直接呼ばない。先に `use` で対象を ACTIVE にし、引数の全パスも同じ `projects/<slug>/` にする。公開 CLI はこの絶対パスの一致を検査し、ACTIVE と同一プロジェクトの更新を協調ロックする。別エージェントが更新中というエラーなら、その処理の完了後に再実行する。以下では例としてプロジェクト `usagi` を使う。

```powershell
python scripts/line_stamp.py project --root . list
python scripts/line_stamp.py project --root . new --slug usagi
python scripts/line_stamp.py project --root . confirm-p0 --materials received --source photo --count 16 --text yes --text-mode font --character-name ハッチくん --sample-candidates 1 --publish yes --rights own --adult yes --consent yes
python scripts/line_stamp.py project --root . use usagi
python scripts/line_stamp.py project --root . status
```

`new` は `^[a-z0-9][a-z0-9-]{1,39}$`（2〜40文字、先頭は英小文字または数字）に合う実名でない slug で、隔離された `gate: P0` のプロジェクトを作る。既存 slug は拒否される。素材をその `refs/` へ置き、P0 の全回答を復唱して承認を得てから `confirm-p0` を実行する。このコマンドは `refs/` 直下の通常ファイルと、`source`、枚数、文字状態、表示名、候補数、申請意図、素材利用権、写真の成年・本人許諾を一括検証・保存し、矛盾がなければ `gate: P1` へ進める。既存キャラクターでは `--adult n/a --consent n/a`、文字なしでは `--text no --text-mode none` を指定する。

旧 v1 プロジェクトは対象を `use` してから診断する。最初のコマンドは dry-run で、2つ目だけがバックアップ作成後に書き込む。欠落した `materials` は、P0 なら `pending`、P1 以降なら `refs/` の読取可能な非空素材を確認できたときだけ `received` にする。権利、許諾、ゲート、承認状態は変更しない。

```powershell
python scripts/line_stamp.py project --root . migrate
python scripts/line_stamp.py project --root . migrate --apply
```

## キャラクター層

背景が既に透過なら `--remove-light-background` を付けない。

```powershell
python scripts/line_stamp.py preprocess-character projects/usagi/raw/stamp01.png projects/usagi/characters/stamp01.png --remove-light-background --outline 10
```

`text_mode: ai`（文字が生成画像に焼き込まれている）では穴補正が文字のカウンターを埋めるため `--no-fill-holes` を付ける。`font|none` では付けない。公開 CLI はこの指定、stamp ID、P4/P5、SESSION の枚数・文字方式を照合する。白縁はこの指定の有無にかかわらず外周だけへ追加され、元画像内の閉じた透明領域は変更しない。

```powershell
python scripts/line_stamp.py preprocess-character projects/usagi/raw/stamp01.png projects/usagi/characters/stamp01.png --remove-light-background --outline 10 --no-fill-holes
```

この処理は文字合成前だけに使う。全体合成画像へ再適用しない。

## 文字合成

[static-manifest.example.json](../assets/static-manifest.example.json) を `projects/usagi/manifest.json` へコピーし、`text_mode`、フォント、色、セリフ、キャラクター画像を設定する。`font` を使う場合は、利用許諾を確認した日本語フォントを `projects/usagi/fonts/` に置く。manifest 内の相対パスは manifest のあるディレクトリを基準に解決される。`items[].text` は両方式で承認済みセリフを一字一句そのまま書く（`ai` では検査の正解として使う）。

manifest の `style.text_mode` は SESSION と一致させる。P4 の合成は item 01 だけ、P5 は ID が `1..SESSION count` と完全一致する全点だけを受け付ける。

`text_mode: font` では文字レイヤーを保存するため `--text-layer-dir` が必須である。

```powershell
python scripts/line_stamp.py compose-static --manifest projects/usagi/manifest.json --outdir projects/usagi/stamps --character-layer-dir projects/usagi/character-layers --text-layer-dir projects/usagi/text-layers
```

`text_mode: ai|none` では空の文字レイヤーを作らないため `--text-layer-dir` を渡さない。

```powershell
python scripts/line_stamp.py compose-static --manifest projects/usagi/manifest.json --outdir projects/usagi/stamps --character-layer-dir projects/usagi/character-layers
```

- `text_mode: font` — フォントで文字を描画する（既定）
- `text_mode: ai` — 文字を描かず、文字入りのキャラクター画像をそのまま配置する。文字帯の制約と縮小後の穴補正は外れる
- `text_mode: none` — 文字なし

## 文字検査（`text_mode: ai` のみ）

生成AIは誤字・脱字・鏡文字を出す。合成後に OCR で照合し、報告を版付きで残す。

```powershell
# P4: stamp01 の標本だけ
python scripts/line_stamp.py verify-text --manifest projects/usagi/manifest.json --dir projects/usagi/stamps --review-dir projects/usagi/review --only 1
# P5: SESSION count の全点（--only は付けない）
python scripts/line_stamp.py verify-text --manifest projects/usagi/manifest.json --dir projects/usagi/stamps --review-dir projects/usagi/review
```

- exit 0: 全点が記号・大小文字も含めて `match`。exit 1: `near` / `mismatch` / 画像欠落 / manifest 不備があり、目視確認または入力修正が必要。exit 2: 入力は有効だが OCR 不可（全点を目視）
- `near` は OCR ノイズの可能性が残るため成功扱いにしない。エージェントが画像を読んで判断材料をユーザーへ出す
- P4 は `gate: P4` と `--only 1`、P5 の最終証跡は `gate: P5`、`manifest.items` の ID が `1..SESSION count` と完全一致し、`--only` なしであることを必須にする。部分再検査だけを全点合格にはしない
- `--only` が空、または指定 id が manifest にない場合は検査を開始せず exit 1 にする。空の `manifest.items` や AI スタンプの空テキストも成功扱いにしない
- OCR 結果だけで合否や再生成を決めない。エージェントが各画像の文字を読み上げ、ユーザーが「全点正しい / 誤字あり（番号）」で承認して初めて SESSION `text_check: ok` にする。再生成は実画像でも不一致と確認された番号だけにする
- 日本語 OCR には tesseract 本体と `jpn.traineddata` が必要（`pip install pytesseract`）。無い環境では exit 2 になり、目視承認だけで判定する

## 確認一覧

P5 の `SESSION count` と完全一致する `stamp01.png` からの連番だけを、白系・濃色の背景へ並べて透過と可読性を確認する。欠品・余剰・`stamp-draft.png` のような非正規名は拒否する。出力は v01 から始め、既存最大版の次番号だけを使い、上書きしない。

```powershell
python scripts/line_stamp.py make-contact-sheet --input projects/usagi/stamps --output projects/usagi/review/review-v01.png --cols 4
```

## 梱包と検証

```powershell
python scripts/line_stamp.py self-test
python scripts/line_stamp.py package-static --stamps projects/usagi/stamps --character-dir projects/usagi/character-layers --outdir projects/usagi/submit --count 16 --zip-name line-stamp-submit.zip
python scripts/line_stamp.py validate-pack --dir projects/usagi/submit --count 16 --character-dir projects/usagi/character-layers --zip projects/usagi/submit/line-stamp-submit.zip
```

P5 承認後に SESSION を P6 へ進めてから梱包・検証する。`package-static --count` と `validate-pack --count/--text-mode` は SESSION と完全一致させる。`text_mode: ai` は全点の OCR・エージェント読上げ・ユーザー目視承認を終えた `text_check: ok` でなければ P6 処理を開始できない。`self-test` が PASS し、`validate-pack` が `errors=0` の場合だけ P6 を完了する。

`package-static` は `submit/` 配下の同一 filesystem 上に一時成果物を完成させてから、管理対象の `main.png` `tab.png` `stampNN.png` と指定 ZIP だけを置換する。無関係なファイルやサブディレクトリを削除しない。旧枚数の `stampNN.png` が残っていれば `validate-pack` が余剰として止めるため、エージェントは削除せずユーザーへ報告する。

`text_mode: ai` では `--text-mode ai` を付ける。文字のカウンターを穴と誤判定しないよう穴検査をスキップし、代わりに濃色背景の確認一覧を目視する。

`validate-pack` は文字の自然なカウンターを切り抜き漏れと誤判定しないよう、キャラクター単独レイヤーへ微小穴検査を行う。提出 PNG の寸法、偶数幅/高さ、RGB/RGBA、72dpi 以上、透過、容量を確認し、ZIP 内の各バイトが検証した提出ファイルと一致することも検査する。

## 公開前チェック

[submission.example.json](../assets/submission.example.json) を `projects/usagi/meta/submission.json` へコピーして埋め、SESSION と ZIP を合わせて検査する。AI を使用した場合は [ai-provenance.example.md](../assets/ai-provenance.example.md) を基に `projects/usagi/meta/ai-provenance.md` を作り、利用ツール、生成日、承認済みプロンプトまたはその保存先を記録する。SESSION が `text_mode: ai` なら `ai_used: true` と provenance の `scope: text` が必須である。販売エリア、対象国、AI/写真使用、ライセンス証明、LINEスタンプ プレミアム参加は既定値を黙認せず、ユーザーが選んだ値を保存する。価格は現在の登録画面から選んだ正の `price_jpy` を復唱し、ユーザー確認後だけ `price_confirmed: true` にする。

```powershell
python scripts/line_stamp.py check-publish-ready --session projects/usagi/SESSION.md --submission projects/usagi/meta/submission.json --zip projects/usagi/submit/line-stamp-submit.zip
```

エラー0で P7 のメタ案提示、承認後に [publish.md](publish.md) へ進む。
