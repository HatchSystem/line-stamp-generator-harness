# クロスプラットフォームCIの修正と効率化

## 完了内容

- Windowsで解決済みパスと未解決パスを比較していた自己診断を、両側とも `resolve()` したOS非依存の比較へ修正した
- マスク外の穴を確認する正常fixtureを非空の有効二値マスクへ変更し、空マスク拒否を独立した異常系テストへ分離した
- CIをUbuntu + Python 3.10の全品質検査1件と、Ubuntu / Windows / macOS + Python 3.14の互換性検査3件へ整理した
- Node検査は1回だけにし、同一refの古い実行を自動キャンセルする。read-only権限、fail-fast無効、10分timeout、外部ActionのSHA固定を構成契約で維持する
- READMEへUbuntu・Windows・macOSの対応範囲と、最低／最新Python版を4ジョブで分担する方針を記載した

## 確認結果

- `node --check scripts/check_structure.mjs`: PASS
- `node scripts/check_structure.mjs`: PASS（553 checks）
- `node scripts/hooks/self_test.mjs`: PASS
- `git diff --check`: PASS
- `python scripts/line_stamp.py self-test`: ローカルにPython実行系がないため未実行。コミット・プッシュ後のGitHub Actions 4ジョブで確認する
- GitHub Actions run 33953035667: Ubuntuの品質・互換性2ジョブはPASS。Windows / macOSで同種の未正規化reviewパスassertionが残っていることが判明し、期待値を `resolve()` する追加修正を行った

## /review

- 違反: なし。禁止操作、認証情報、制作プロジェクト、製品側の画像検証条件には触れていない
- 懸念: 初回の構成検査は、見つかったSHAだけを検査するため未固定Actionの追加を見逃せた
- 改善: 全外部 `uses:` 参照を列挙し、すべてが40桁SHAで終わることを検査するよう修正済み。再検査はPASS

## 学び

OS差を扱うテストは期待値も正規化する。厳格化した入力契約では有効な正常fixtureと無効入力の拒否fixtureを分離する。CIは最低言語版、最新言語版、OS差、静的検査へ責務を分け、不要な直積と重複処理を避ける。
