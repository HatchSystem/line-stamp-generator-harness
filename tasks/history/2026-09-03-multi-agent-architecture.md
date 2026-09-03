# マルチエージェント対応の汎用構成

## 目的

Claude Code 固有ディレクトリに偏っていた共通手順・役割・検証実装を、Claude Code、Codex、Cursor などが同じ契約で利用できる構成へ移す。LINEスタンプ制作のP0〜P9承認境界と、ユーザーだけが行う法的同意・不可逆操作を維持しながら、参照ドリフトと環境差による安全機能の欠落を防ぐ。

## 実施内容

- `AGENTS.md` を全エージェント共通の入口、`.agents/skills/`・`.agents/roles/`・`.agents/learnings/` をベンダー中立な正本とした
- `.claude/`・`.codex/`・`.cursor/` は正本を参照するコマンド、役割、hook設定だけの薄いアダプタにした
- 公開CLIを `scripts/line_stamp.py` に固定し、内部Python実装の物理パスを文書やアダプタから隠した
- 安全判定を `scripts/hooks/policy.mjs` に集約した。Claude旧hookは判定を複製せず、Pythonのコマンド名差を吸収し、不在なら共通Node hookへフォールバックする互換経路にした
- `scripts/check_structure.mjs` に正本/アダプタの依存方向、role/skill集合、frontmatter、リンク、設定、公開CLI、P0、schema、申請メタ、画像/ZIP、hook委譲の回帰検査を実装した
- 新規案件を不完全な `gate: P0` として隔離する `project new` と、`refs/` の素材実体および全回答を検証してP1へ進める `confirm-p0` を分離した
- SESSIONと申請メタをschema v2とし、選択中プロジェクトだけを対象にしたdry-run既定、明示`--apply`、バックアップ、同一filesystem原子置換、途中失敗時の巻き戻しを実装した
- 素材利用権と写真の本人許諾を分離し、成年状態を外見から推測しない。公開メタには販売エリア/国、AI・写真使用、プレミアム参加、プロジェクト内AI来歴、HTTPSまたはプロジェクト内のライセンス参照を明示した
- `font` だけが透明文字レイヤーを保存し、`ai|none` では空レイヤーを作らないようにした。提出PNGは寸法、偶数、モード、DPI、透明背景、可視内容、容量を確認し、ZIP memberを検証済みローカルファイルとバイト照合するようにした

## 確認結果

- `node scripts/check_structure.mjs` — `PASS check-structure: 401 checks`
- `node scripts/hooks/self_test.mjs` — `PASS agent-hook-policy`
- Claude互換hookランナー — 危険コマンドfixtureを共通ポリシーでブロックしPASS
- Node構文 — 6ファイルPASS
- Git Bash構文 — 2ファイルPASS
- UTF-8 BOM、CRLF、末尾改行、行末空白 — 対象77ファイルPASS
- `git diff --check` — PASS
- 構成・安全性・移植性・既存フローの独立再監査 — Critical / High / Medium / Low すべて0件
- `python`、`python3`、`py`、`uv` — 現環境では未検出。このため `python scripts/line_stamp.py self-test` は未実行
- `projects/*` の制作物は変更せず、追跡対象の説明用 `projects/README.md` だけを更新した

## レビュー

- 完了内容: 共通コアと薄い製品別アダプタ、安定CLI、安全hook、構造検査、状態/メタ/提出物の契約を一貫した構成で実装した
- 確認結果: Python実行を除く利用可能な検査はすべて合格し、独立再監査の未解決指摘は0件
- 残課題: Python 3.10以上と依存関係を導入した環境で `python scripts/line_stamp.py self-test` を実行する
- 学び: [workflow](../../.agents/learnings/workflow.md)、[pipeline](../../.agents/learnings/pipeline.md)、[publish](../../.agents/learnings/publish.md) に記録した
