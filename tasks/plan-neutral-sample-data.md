# 個人・ブランドを連想させるサンプル名称の中立化

## 目的

サンプル値として使われている `ハッチくん` / `Hatch-kun` / `HatchWorks` / `Hatch` などを、ユーザー指定の汎用的な例示名へ置き換える。ドキュメント、申請メタの見本、自己診断fixtureの値を揃え、実際のリポジトリ識別子と制作済みプロジェクトは変更しない。

## 調査結果

- Git管理対象の検索と、隠しディレクトリを含む作業ツリー検索で、サンプル値の対象は4ファイル・11箇所。
- `submission.example.json` は日英タイトル・日英説明・creator_name・copyrightの6箇所。
- `README.md` と `references/commands.md` はP0確定コマンドのキャラクター名が各1箇所。
- `scripts/self_test.py` はSESSION fixture、P0入力fixture、対応するassertionの3箇所。
- `HatchSystem` は今回のサンプル検索では見つからず、Git remoteの実在リポジトリ所有者として確認した。サンプル値として追加で見つかった場合だけ置換対象にする。
- 現行 `check_copyright` は半角英数字のみを受け付け、スペースを拒否する。LINE公式ガイドもコピーライトを50文字以内・英数字のみとしているため、推奨例の `2026 ExampleCreator` はスペースを省いた `2026ExampleCreator` とする。検証規則は緩めない。
- `projects/ACTIVE` はなく、対象プロジェクト固有の記録はない。

## 置換対応

| 用途 | 現在 | 変更後 |
|---|---|---|
| 日本語キャラクター名・コマンド例 | `ハッチくん` | `サンプルくん` |
| 英語キャラクター名 | `Hatch-kun` | `Sample-kun` |
| 英語fixtureのキャラクター名 | `Hatch` | `Sample-kun` |
| 日本語タイトル | `ハッチくんの毎日スタンプ` | `サンプルくんの毎日スタンプ` |
| 英語タイトル | `Hatch-kun Daily Stickers` | `Sample-kun Daily Stickers` |
| creator_name | `HatchWorks` | `ExampleCreator` |
| copyright | `2026HatchWorks` | `2026ExampleCreator` |

説明文も同じ名称に揃える。

- 日本語: `あいさつや返事に使えるサンプルくんの日常スタンプです。家族や友だちとの会話にどうぞ。`
- 英語: `Everyday stickers of Sample-kun for greetings and quick replies to family and friends.`

## 影響範囲

- 変更する:
  - `.agents/skills/line-stamp-generator/assets/submission.example.json`
  - `.agents/skills/line-stamp-generator/references/commands.md`
  - `.agents/skills/line-stamp-generator/scripts/self_test.py` の対象fixtureとassertionのみ
  - `README.md`
  - `tasks/todo.md`、本計画、完了後の `tasks/history/`
- 変更しない:
  - Git remote、リポジトリ所有者・実在の参照URL、Git履歴。
  - `projects/` のSESSION、画像、申請メタ、提出ZIP。既存案件の一括置換や移行は行わない。
  - schema、CLI引数、検証規則、価格・枚数・販売設定・申告項目、制作ゲート、画像処理、CI設定。
  - 実際の製品・フォント・プラットフォーム名や、禁止語を検証する意図的なテストデータ。
  - 過去の計画・履歴にある旧名称の記録。新しい例示値としては利用しない。
- 実行時に生成される:
  - 既存自己診断の一時fixture・検証結果とレビュー履歴。スタンプや申請データは生成しない。

## ステップ

- [x] 1. 計画承認後、4ファイルの対象値を対応表どおりに変更する（確認: 日英タイトル・説明・コマンド例・fixtureが同じ例示キャラクターを指す）。
- [x] 2. P0入力fixtureとassertionを同時に更新する（確認: 入力した名称がSESSIONへ保存されるという既存テストの目的と判定は維持される）。
- [x] 3. JSONの構文と新しいタイトル・説明・creator_name・copyrightを既存の文字数／文字種検証で確認する（確認: 改名した項目が合格し、他フィールドは変わっていない。サンプル単体には成果物がないため、P7全体のPASSとは扱わない）。
- [x] 4. `git grep` と `rg` で `ハッチ` / `Hatch` を大小文字を区別せず再検索する（確認: 現行のサンプル値は0件。計画の置換前表、履歴、実在リポジトリ参照は用途を確認して除外し、実在URLを壊さない）。
- [x] 5. 動作確認として `node scripts/check_structure.mjs` / `node scripts/hooks/self_test.mjs` / `python scripts/line_stamp.py self-test` / `git diff --check` を実行する（確認: 既存検査がPASSし、変更が名称と記録に限定されている。新しい検査機構や重複テストは追加しない）。
- [x] 6. レビュー記入と `tasks/history/` への保存を行う（確認: 対象漏れ・意図しない置換・サンプルの検証不適合がない。再利用できる知見がなければ「学びなし」と記録する）。

## 進捗メモ

- 2026-09-06: 計画案を作成。計画承認後、4ファイル・11箇所の名称変更を実施。検証完了。前回の完了済みtodoは `tasks/history/2026-09-06-chat-only-questions.md` に保存済み。
- 共有learningsのfixture・schema移行方針を確認した。今回は値だけの変更でschema移行は不要。
- 公式確認: [LINE制作ガイドライン・テキスト](https://creator.line.me/ja/guideline/sticker/)（2026-09-06確認）。

- 検証中に計画書のコマンド列挙が構成検査で誤解釈されたため、コマンド間の区切り表記を修正して再検証した。検査コード自体の変更はない。

## レビュー

- 完了内容: 承認済み計画に従い、4ファイル・11箇所のサンプル名称を変更。日英タイトル・説明、作者名、コピーライト、コマンド例、fixtureとassertionを統一。
- 確認結果: JSON構文、既存検証関数によるメタ6項目の文字数・文字種、他フィールドのHEAD一致を確認。rgとgit grepで現行サンプルの旧名称は0件。構成検査558 checks、hook自己診断、公開CLIのPython自己診断、git diff --checkがすべてPASS。P7全体の検証結果とは扱わない。
- 残課題: なし。コミット・プッシュは今回の実装依頼に含まれないため未実施。
- 学び: 学びなし。既存検証規則や共通知見の変更は不要。
