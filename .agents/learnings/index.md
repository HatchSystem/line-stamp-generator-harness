# Learnings 索引

| 日付 | 要約 | 詳細 |
|---|---|---|
| 2026-09-03 | 新規プロジェクト作成とP0確定を分け、素材実体と全回答の検証後だけP1へ進める | [workflow.md](workflow.md#2026-09-03-p0-state-transition) |
| 2026-09-03 | 提出PNGの可視性・DPI・境界値とZIP内バイトまで検証し、同一filesystemで安全に梱包する | [pipeline.md](pipeline.md#2026-09-03-submit-pack-validation) |
| 2026-09-03 | 販売地域、AI・写真使用、ライセンス確認、参加設定を明示メタとして法的同意から分離する | [publish.md](publish.md#2026-09-03-registration-declarations) |
| 2026-09-03 | 永続状態の列挙値を変えると旧案件が停止する。schema version と dry-run 既定の原子的移行を同時に用意する | [workflow.md](workflow.md#2026-09-03-project-schema-migration) |
| 2026-09-03 | 共通資産を製品固有ディレクトリに置くと参照がドリフトする。正本・薄いアダプタ・安定 CLI を分離して自動検査する | [workflow.md](workflow.md#2026-09-03-multi-agent-source-of-truth) |
| 2026-09-03 | Windows では `python` と `bash` が PATH にない場合がある。実行環境を先に確認し、Git Bash は絶対パスで呼ぶ | [workflow.md](workflow.md#2026-09-03-windows-runtime-discovery) |
| 2026-09-01 | /bin/sh はブレース展開に非対応。mkdir が失敗して rules が意図しない場所に書かれた | [workflow.md](workflow.md#2026-09-01-brace-expansion) |
