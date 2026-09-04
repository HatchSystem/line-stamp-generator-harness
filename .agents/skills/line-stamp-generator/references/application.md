# 申請メタ案（P7）

人物写真由来・既存キャラ由来のどちらでも、タイトルと説明へ実名を書かず承認されたキャラ名を使う。ユーザーが審査申請を希望しない場合は `publish: local-only` とし、公開申請を案内しない。未申請の成果物は LINE 上で配布・利用できない。

用意する案（`meta/submission.json` に保存。形式は [submission.example.json](../assets/submission.example.json)）:

- スキーマ: `schema_version: 3` を維持する。旧形式は先に公開 CLI の `project --root . migrate` で診断する
- 日本語タイトル: 公式カウントで2〜40。全角は2文字換算のため、全角だけなら最大20文字
- 英語タイトル: 短い英題。全角文字を含めない
- 日本語説明: 日常での用途を公式カウント10〜160で（全角は2文字換算）
- 英語説明: 同上。全角文字を含めない
- クリエイター名: 実名を避けた表示名（公式カウント50以内。全角は2文字換算）
- コピーライト: 半角英字・数字のみ（空白や記号なし）、50文字以内
- 価格: 現在の登録画面の選択肢からユーザーが選んだ正の整数を `price_jpy` に保存し、同じ値を復唱して確認した後だけ `price_confirmed: true` にする。テンプレートの `false` は未確認を表し、公開前チェックを通らない
- 販売エリア: `sales_area` を公式 UI の3択に合わせて `all`（販売可能な全て）／`some`（販売可能な一部）／`selected`（選択したエリア）から選ぶ。`all` は `sales_countries: []`、`some|selected` は画面で選んだ国を重複のない2文字国コードで記録する
- 販売開始設定: `manual`（手動で販売を開始）。自動開始は選ばない
- LINE STORE 表示: `store_visibility` を `public`（公開）／`private`（非公開）から選ぶ。ローカル限定を表す SESSION `publish: local-only` とは別概念
- AI使用: `ai_used` を真偽値で明示する。`text_mode` から推測せず、画像・文字の制作で実際に使った事実をユーザーと確認する。`true` なら [ai-provenance.example.md](../assets/ai-provenance.example.md) を基に、利用ツール、生成日、承認済みプロンプトまたはその保存先を `meta/ai-provenance.md` に保持する
- 写真使用: `photo_used` を真偽値で明示し、最終提出画像が登録画面の「写真の使用」に該当するかをユーザーと確認する。写真由来プロジェクトでも完全な描き起こしなら自動決定しない
- ライセンス証明: 通常は質問も保存も必須にしない。LINE から追加資料を求められ、ユーザーが提示した場合だけ、任意の `license_proof` に `status: user-confirmed` と作品の HTTPS URL または対象プロジェクト内の既存相対パス（例: `refs/license.pdf`）を記録する。エージェントは証明書を作らず、検査も法的有効性を保証しない
- LINEスタンプ プレミアム: 登録画面の既定を黙認せず、参加するかをユーザーへ確認し `premium_participation` の真偽値で保存する
- タグ案: 各スタンプに最大9個。P3の表情・用途から機械的に候補を作る

価格、販売エリア、LINE STORE 表示、AI/写真使用、プレミアム参加などの有限の選択は、関連する最大3問を1回の構造化選択 UI にまとめ、推奨案を先頭にして影響を示す。`python scripts/line_stamp.py check-publish-ready ...` を通し、エラー0でユーザーにメタ案を提示する。承認後に [publish.md](publish.md) の P8 へ進む。

ZIPには `main.png`、`tab.png`、規定数のスタンプPNGだけを入れる。提供写真、三面図、レビュー一覧、SESSION、メタ文書は入れない。
