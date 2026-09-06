# 静止スタンプ用コマンド

## プロジェクト

すべてハーネスのルートで実行する。公開 CLI は `scripts/line_stamp.py` で、スキル内部の Python ファイルを直接呼ばない。先に `use` で対象を ACTIVE にし、引数の全パスも同じ `projects/<slug>/` にする。公開 CLI はこの絶対パスの一致を検査し、ACTIVE と同一プロジェクトの更新を協調ロックする。別エージェントが更新中というエラーなら、その処理の完了後に再実行する。以下では例としてプロジェクト `usagi` を使う。

```powershell
python scripts/line_stamp.py project --root . list
python scripts/line_stamp.py project --root . new --slug usagi
python scripts/line_stamp.py project --root . confirm-p0 --materials received --source photo --count 16 --text yes --text-mode font --character-name サンプルくん --sample-candidates 1 --publish yes
python scripts/line_stamp.py project --root . confirm-design --image refs/design-v01.png --reference refs/source.png --hairstyle "短い黒髪" --head-ratio 2.2 --clothing "青い上着" --color "#1A2B3C" --color "#F4D7C5" --eyes "丸い黒目" --accessories "なし"
python scripts/line_stamp.py project --root . confirm-three-view --image refs/three-view-v01.png
python scripts/line_stamp.py project --root . use usagi
python scripts/line_stamp.py project --root . status
```

`new` は `^[a-z0-9][a-z0-9-]{1,39}$`（2〜40文字、先頭は英小文字または数字）に合う実名でない slug で、隔離された `gate: P0` のプロジェクトを作る。Windows の予約デバイス名とハーネス予約名 `active` は使えず、既存 slug も拒否される。素材をその `refs/` へ置き、P0 の全回答を復唱して承認を得てから `confirm-p0` を実行する。このコマンドは `refs/` 直下の通常ファイルと、`source`、枚数、文字状態、表示名、候補数、申請意図を一括検証・保存し、矛盾がなければ `gate: P1` へ進める。`adult`、`consent`、`rights` は引数にも SESSION にも持たない。文字なしでは `--text no --text-mode none` を指定する。

`confirm-design` はP1の画像・数値仕様・参考画像を版付きハッシュ証跡として固定し、以前の三面図以降の承認を無効化する。`confirm-three-view` はP2画像を現在のP1証跡へ結び付ける。画像は先に例の版付きファイル名で `refs/` へ保存する。

旧形式のプロジェクトは対象を `use` してから診断する。最初のコマンドは dry-run で、2つ目だけがバックアップ作成後に書き込む。v4 への移行ではP1/P2証跡、文字マスク、P8アカウント項目を未確認状態で追加し、旧P9と審査後状態を制作完了へ移す。廃止済みの `adult`、`consent`、`rights` と、空の既定値だった `license_proof` は削除する。

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

[static-manifest.example.json](../assets/static-manifest.example.json) を `projects/usagi/manifest.json` へコピーし、`text_mode`、フォント、色、セリフ、キャラクター画像を設定する。`font` を使う場合は、日本語フォントを `projects/usagi/fonts/` に置く。manifest 内の相対パスは manifest のあるディレクトリを基準に解決される。`items[].text` は両方式で承認済みセリフを一字一句そのまま書く（`ai` では検査の正解として使う）。

manifest の `style.text_mode` は SESSION と一致させる。P4 の合成は item 01 だけ、P5 は ID が `1..SESSION count` と完全一致する全点だけを受け付ける。`style.safe_margin` は12〜16、推奨16とし、最終合成後の実測余白が12px未満なら内容を自動縮小する。`ai` は各 item に、最終画像上の文字だけを囲む `text_region: [left, top, right, bottom]` を指定する。

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

生成AIが合成後の各画像を実際に開いて文字を読み、誤字・脱字・鏡文字・字形崩れ・判読困難を確認する。CLIはこの目視結果を記録・検証し、画像認識そのものは行わない。

[visual-text-review.example.json](../assets/visual-text-review.example.json) を参考に、`review/visual-reading-vNN.json` を作る。`method: ai-visual`、現在のmanifestハッシュ、各画像の番号・ファイル名・ハッシュ・承認セリフ・読み取り・判定を記録する。モデル名や独立した検査サービスは必須にしない。`recognized` は実際に読めた内容とし、期待文字から補完しない。

```powershell
# P4: stamp01の記録を渡す
python scripts/line_stamp.py verify-text --manifest projects/usagi/manifest.json --dir projects/usagi/stamps --review-dir projects/usagi/review --only 1 --visual-review projects/usagi/review/visual-reading-v01.json
# P5: SESSION countの全点を読み取った記録を渡す（--onlyなし）
python scripts/line_stamp.py verify-text --manifest projects/usagi/manifest.json --dir projects/usagi/stamps --review-dir projects/usagi/review --visual-review projects/usagi/review/visual-reading-v02.json
```

- 判定は `match`（一致）、`mismatch`（誤字・字形崩れ等）、`unreadable`（判読困難）、`not-run`（未確認）。exit 0は全点一致、exit 1は不一致・未確認・判読困難・入力不備。`match` と記載しても読み取り文字が違えば不一致とする。空白・改行とUnicode正規化以外の文字差は無視しない
- P4は `gate: P4` と `--only 1`、P5は `gate: P5` とID `1..SESSION count` の全点を必須とする。欠番・重複・部分再検査を全点合格にしない
- レポートは `review/text-check-vNN.md` と `.json`（schema 3）、文字領域マスクは `text-masks/vNN/` に保存する。既存版を上書きしない
- 全点一致の結果を添えたP5一覧をユーザーが通常チャットで承認した後、SESSION `text_check: ok` と最新の `text_mask_version` を記録する。文字だけの追加ユーザー検査は不要
- 画像やmanifest変更時は目視確認をやり直す。P5の最終記録は全点を揃え、変更していない画像の記録は同一ハッシュの場合だけ引き継げる
- 既存の承認済みschema 2レポートと文字マスクは読み取り互換で維持する。旧OCR結果をAI目視済みへ自動変換しない。再確認時はP5（01候補はP4）へ戻し `text_check: not-run` として新しい目視記録を作り、成果物を再承認する。SESSION schemaの移行は不要
- 旧 `--vision-evidence`、`--lang`、`--scale`、`--min-similarity` は廃止。新しい記録には `--visual-review` を使う

## 確認一覧

P5 の `SESSION count` と完全一致する全画像を必ず1枚へまとめ、白系・濃色の背景へ並べて透過と可読性を確認する。欠品・余剰・`stamp-draft.png` のような非正規名は拒否する。出力は v01 から始め、既存最大版の次番号だけを使い、上書きしない。

```powershell
python scripts/line_stamp.py make-contact-sheet --input projects/usagi/stamps --output projects/usagi/review/review-v01.png --cols 4
```

## 梱包と検証

```powershell
python scripts/line_stamp.py self-test
python scripts/line_stamp.py package-static --stamps projects/usagi/stamps --character-dir projects/usagi/character-layers --outdir projects/usagi/submit --count 16 --zip-name line-stamp-submit.zip
python scripts/line_stamp.py validate-pack --dir projects/usagi/submit --count 16 --character-dir projects/usagi/character-layers --zip projects/usagi/submit/line-stamp-submit.zip
```

P5 承認後に SESSION を P6 へ進めてから梱包・検証する。`package-static --count` と `validate-pack --count/--text-mode` は SESSION と完全一致させる。`text_mode: ai` は全点のAI目視一致とP5一覧承認を終えた `text_check: ok` でなければ P6 処理を開始できない。`self-test` が PASS し、`validate-pack` が `errors=0` の場合だけ P6 を完了する。

`package-static` はレビュー済み内部正本 `stamps/stampNN.png` を提出用の `submit/NN.png` へ番号対応でコピーする。`submit/` 配下の同一 filesystem 上に一時成果物を完成させてから、管理対象の `main.png` `tab.png` `NN.png` と指定 ZIP だけを置換する。ZIP member は `main.png`、`tab.png`、`01.png`〜`NN.png` だけにする。無関係なファイルやサブディレクトリを削除しない。旧枚数の数値名PNGが残っていれば `validate-pack` が余剰として止める。旧形式の `submit/stampNN.png` は削除せず警告し、ZIPから除外する。

`text_mode: ai` では `--text-mode ai` を付ける。`validate-pack` は最新の版付き文字領域マスクを使い、「口」「日」など文字内の穴だけを除外して、文字領域外の微小穴を検査する。マスク欠落・ハッシュ不一致・キャラクターを過度に覆う広い領域はエラーになる。

`validate-pack` は文字の自然なカウンターを切り抜き漏れと誤判定しないよう、内部名 `character-layers/stampNN.png` のキャラクター単独レイヤーへ微小穴検査を行う。提出名 `submit/NN.png` の寸法、偶数幅/高さ、RGB/RGBA、72dpi 以上、透過、容量を確認し、対応するレビュー済み `stamps/stampNN.png` およびZIP内の同名memberとバイト一致することも検査する。

## 公開前チェック

[submission.example.json](../assets/submission.example.json) を `projects/usagi/meta/submission.json` へコピーして埋め、SESSION と ZIP を合わせて検査する。AI を使用した場合は [ai-provenance.example.md](../assets/ai-provenance.example.md) を基に `projects/usagi/meta/ai-provenance.md` を作り、利用ツール、生成日、承認済みプロンプトまたはその保存先を記録する。SESSION が `text_mode: ai` なら `ai_used: true` と provenance の `scope: text` が必須である。販売エリア、対象国、AI/写真使用、LINEスタンプ プレミアム参加は既定値を黙認せず、ユーザーが選んだ値を保存する。`license_proof` は通常は省略し、LINE から追加資料を求められユーザーが提示した場合だけ任意で保存する。価格は現在の登録画面から選んだ正の `price_jpy` を復唱し、ユーザー確認後だけ `price_confirmed: true` にする。

```powershell
python scripts/line_stamp.py check-publish-ready --session projects/usagi/SESSION.md --submission projects/usagi/meta/submission.json --zip projects/usagi/submit/line-stamp-submit.zip
```

エラー0で P7 のメタ案提示、承認後に [publish.md](publish.md) へ進む。

## 制作中の学びとP8完了

問題または教訓は、その場で対象プロジェクトへ追記する。秘密情報や個人情報は引数へ含めない。

```powershell
python scripts/line_stamp.py project --root . record-learning --gate P5 --kind problem --summary "余白不足" --impact "検証停止" --cause "上端へ寄り過ぎ" --resolution "自動縮小" --candidate "安全余白を生成時から固定"
python scripts/line_stamp.py project --root . confirm-account --account-name "表示名" --seller-id "販売者ID" --registration-target "新規スタンプ登録"
python scripts/line_stamp.py project --root . complete-production --account-name "表示名" --seller-id "販売者ID" --registration-target "新規スタンプ登録" --preview-confirmed
```

P8は `confirm-account` 後も入力直前に画面表示との一致を確認する。入力とプレビューのユーザー確認が終わったら `complete-production` が `production-complete` を保存し、定型の制作完了メッセージを表示する。審査リクエスト後の状態は扱わない。
