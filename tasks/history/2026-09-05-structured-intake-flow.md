# 構造化選択と P0 schema v3

## 目的

P0 の成年・本人許諾・著作権／ライセンス確認を廃止し、有限のユーザー選択を構造化選択 UI へ統一する。共通層をベンダー中立に保ち、Claude Code では `AskUserQuestion` を使用する。

## 実行フロー

1. ACTIVE と SESSION を確認し、続行・別案件・新規を構造化選択する
2. 新規なら P0 プロジェクトを作り、素材を対象 `refs/` に隔離する
3. 入力種別・枚数・文字有無、続いて文字方式・申請意図・候補数を最大3問ずつ確定する
4. キャラクター名を自由入力で受け、確定内容の承認後だけ `confirm-p0` で P1 へ進める
5. P1〜P5 は1ゲートずつ成果物を承認し、P6 で自己テスト・梱包検証を行う
6. P7 は申請設定を構造化選択し、追加資料は LINE から要求された場合だけ任意で扱う
7. P8〜P9 は入力・追跡を支援し、同意・審査リクエスト・リリースはユーザー本人が行う

## 完了内容

- SESSION / submission を schema v3 に更新し、新規 P0 と `confirm-p0` から `adult`、`consent`、`rights` を削除した
- migration は dry-run を既定とし、適用時に旧3フィールドと空の既定 `license_proof` をバックアップ後に削除する。ユーザー提示済みの任意資料は維持する
- `check-publish-ready` はライセンス証明なしを正常とし、任意情報が存在するときだけプロジェクト内パスまたは HTTPS URL を検証する
- 共通層を「構造化選択 UI」の能力契約にし、Claude アダプタへ `AskUserQuestion`、最大3問、推奨先頭、相互排他、利用不可時だけ番号付きフォールバックを明記した
- 対話資料へ P0〜P9 の実行フローを追加し、AGENTS、README、reference、review、publisher role、申請メタ例を同期した
- 構造検査を schema v3 と新しい対話契約へ更新し、確認一覧の排他的作成を実装構造ではなく transaction の振る舞いで検査するよう直した
- Ubuntu / Windows × Python 3.10 / 3.14 の CI を追加し、外部 Action は公式リリースのコミット SHA に固定した

## 確認

- PASS: `node --check scripts/check_structure.mjs`
- PASS: `node scripts/check_structure.mjs`（507 checks）
- PASS: `node scripts/hooks/self_test.mjs`
- PASS: `git diff --check`
- 未実行: `python scripts/line_stamp.py self-test`。ローカルに Python、WSL、コンテナランタイムがないため、初回 CI 実行で確認する

## レビュー

- 違反: なし
- 懸念: Python 自己テストのローカル実行証跡がない。CI 実行前であることを明示する
- 改善案: 初回 push / pull request で4ジョブの結果を確認し、失敗時は該当契約だけを修正する
- 学び: [structured intake contract](../../.agents/learnings/workflow.md#2026-09-05-structured-intake-contract)、[optional supporting evidence](../../.agents/learnings/publish.md#2026-09-05-optional-supporting-evidence)
