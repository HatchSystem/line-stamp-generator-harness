# CI自己診断の修正と効率的なmacOS対応

## 目的

静止画LINEスタンプ制作ハーネスをPython 3.10以上で安定して実行できる状態に戻し、Ubuntu・Windows・macOSの主要3 OSを継続検証する。製品コードの安全条件は緩めず、最低／最新Python版とOS差の組み合わせを絞ったCIで、過剰な直積テストと重複処理を避ける。

## 影響範囲

- 変更する:
  - `.agents/skills/line-stamp-generator/scripts/self_test.py`
  - `scripts/line_stamp.py`
  - `.github/workflows/ci.yml`
  - `scripts/check_structure.mjs`
  - `README.md`
  - `tasks/todo.md`、完了後の `tasks/history/`
  - 再利用価値が確認できた場合だけ `.agents/learnings/`
- 変更しない:
  - `image_utils.py` の「文字マスクは非空かつ60%以下」という製品側の検証条件
  - `compose_static.py` の正規化済みパス返却契約
  - P0〜P8、SESSION schema、画像生成・梱包・公開処理
- 実行時に生成される:
  - ローカルのテストログ
  - コミット・プッシュを別途承認された場合のGitHub Actions実行結果

## 確認済み原因

1. Windows 3.10 / 3.14 は `checked_output_directories()` が返す解決済みパスを、テストが未解決の `project / ...` と比較して失敗している。Windowsの一時ディレクトリ表記差を考慮していないテスト側の問題である。
2. Ubuntu 3.10 / 3.14 は、穴を除外しない比較用として空マスクを渡している。しかし製品側は空の文字マスクを意図どおり拒否するため、期待する穴検査へ到達する前にテストが停止している。

## ステップ

- [x] 1. Windows向けパスassertionの期待値も `.resolve()` し、返却値が各プロジェクトの正規ディレクトリと一致することをOS非依存で検査する（確認: stamps / character-layers / text-layers の3項目をすべて比較）
- [x] 2. 「穴を除外しない」fixtureを、空マスクではなく中央の穴を覆わない小さな有効二値マスクへ変更する（確認: マスク外の穴が検出される）
- [x] 3. 空マスク拒否を独立した異常系テストとして追加し、製品側の安全条件を維持する（確認: `ValueError` と期待するメッセージを検査）
- [x] 4. CIを「品質基準1件」と「互換性3件」に分ける。品質基準はUbuntu + Python 3.10でNode構文・構成・hook・Python CLI・空白を検査し、互換性はUbuntu / Windows / macOS + Python 3.14でPython CLIだけを検査する（確認: 3 OS、最低3.10、最新3.14を4ジョブで網羅し、6通りの直積とNode検査の重複を避ける）
- [x] 5. 同じrefの古いCIを自動キャンセルするconcurrency、read-only権限、fail-fast無効、SHA固定Action、現実的なtimeoutを維持・設定する（確認: 安全性を下げず、不要な実行時間を削減する）
- [x] 6. 構成検査とREADMEを新しい対応範囲へ同期する（確認: macOS、Python 3.10以上、効率化した4ジョブ構成が文書と検査で一致する）
- [x] 7. ローカルで実行可能な `git diff --check`、Node構文検査、構成検査、hook自己診断を実行する。Pythonが利用可能なら公開CLI自己診断も実行する
- [x] 8. 差分をレビューし、製品側の検証条件を緩和していないこと、CI変更が目的に必要な最小範囲であることを確認する
- [x] 9. レビュー結果を記入して `tasks/history/` へ保存する。再利用価値が確認できた知見だけ共有learningsへ記録する
- [ ] 10. コミット・プッシュが承認された場合、GitHub Actionsを実行し、品質基準1件とUbuntu / Windows / macOS互換性3件がすべて成功することを確認する。別の失敗が現れた場合は原因を再評価し、無関係な修正を追加しない

## 進捗メモ

- 2026-09-05: GitHub Actions run 33949597508 の全ジョブログを確認した。Node構文、構成544項目、hook検査は成功し、公開Python CLI自己診断だけが失敗している。
- 2026-09-05: Windows 2件は `self_test.py:797` の未正規化期待パス比較、Ubuntu 2件は `self_test.py:1768` の空マスクfixtureが原因と特定した。
- 2026-09-05: 選択中の制作プロジェクトは存在しないため、プロジェクト固有 `LEARNINGS.md` の参照・更新対象はない。共有learningsの索引、方針、画像品質・Windows実行環境の既存知見を確認した。
- 2026-09-05: macOSは実装上明示的に排除されていないが、現行CIに含まれず保証できない。過剰な6通りのOS×Python直積にはせず、最低版1件と最新版3 OSの計4件で言語互換性とOS差を分担する方針へ更新した。
- 2026-09-05: 自己診断2件、4ジョブCI、concurrency、README、構成契約を実装した。Node構文、構成554項目、hook自己診断、`git diff --check` はPASS。ローカルにPythonがないため公開CLI自己診断はCIで確認する。
- 2026-09-05: レビューで外部Action固定検査が未固定の `uses:` 行を見逃せる懸念を発見し、全外部Action参照を40桁SHAで検査するよう修正した。再検査はPASS。
- 2026-09-05: 初回プッシュ後のrun 33953035667ではUbuntu 2件がPASSし、Windows / macOSは残っていたreview入出力の未正規化パス比較で停止した。同じ原因の残り2 assertionを `resolve()` へ統一した。
- 2026-09-05: 追補run 33953157707ではUbuntu 2件とmacOSがPASSし、Windowsだけがcp1252への日本語help出力で停止した。公開CLI入口をUTF-8へ構成し、狭いコードページを模擬する回帰試験を追加した。

## レビュー

- 完了内容: 自己診断fixtureのOS非依存化、macOSを含む4ジョブCI、重複Node検査削減、古いCIの自動キャンセル、対応環境の文書・構成契約を実装した。
- 確認結果: `node --check scripts/check_structure.mjs`、`node scripts/check_structure.mjs`（554 checks）、`node scripts/hooks/self_test.mjs`、`git diff --check` はPASS。
- 残課題: ローカルPython不在のため公開CLI自己診断は未実行。コミット・プッシュ後にGitHub Actionsの4ジョブを確認する。
- 学び: OS差を扱うテストは期待値も正規化し、厳格な入力契約では有効な正常fixtureと拒否fixtureを分離する。CIは最低版・最新版・OS差へ責務を分け、静的検査を重複実行しない。
