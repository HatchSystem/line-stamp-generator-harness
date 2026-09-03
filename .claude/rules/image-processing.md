# 画像処理ルール

- 文字入れは SESSION `text_mode` に従う。`font`（既定）では生成モデルに文字を描かせず、ポーズ付きキャラクター画像だけを生成して `compose_static.py` で後から描画する。`ai` では承認済みセリフを一字一句プロンプトへ入れて描かせ、`verify_text.py` の OCR とエージェントの読み取り、ユーザーの目視承認で誤字を検査する。方式を途中で混ぜない
- `ai` では穴補正（`preprocess_character.py --no-fill-holes`）と穴検査（`validate_pack.py --text-mode ai`）を行わない。文字のカウンターを埋めるため
- 文字は透明な専用レイヤーへ描く。縁取りは同心の `stroke_width` のみ。影・ずらし複製・ぼかし・グローは使わない
- 背景除去・微小穴補正・白縁はキャラクターレイヤーだけに、文字合成より前に適用する。最終合成画像へ穴埋めをしない
- 最終処理は低アルファ画素の RGBA ゼロ化だけ。文字のカウンターや自然な抜きを白で埋めない
- 写真由来は 2〜2.5 頭身の線画・平坦な色。既存キャラは原作デザインと配色を変えない
- 毎回、承認済み三面図（既存キャラは正本も）を画像参照に含める
- 写真にない小物、他者、背景、商標ロゴを追加しない
- 生成結果（`characters/`）と文字合成結果（`stamps/`）を分けて保存する。`character-layers/` は穴検査と main/tab 生成に使う
- 確認一覧は白背景と濃色背景の両方で見る。修正のたびに `review-v02.png` と版を上げ、上書きしない
- パイプライン順: `preprocess_character.py` → `compose_static.py` →（`ai` のみ `verify_text.py`）→ `make_contact_sheet.py` → `package_static.py` → `validate_pack.py` → `check_publish_ready.py`

詳細: `.claude/skills/line-stamp-generator/references/text-and-transparency.md`, `commands.md`
