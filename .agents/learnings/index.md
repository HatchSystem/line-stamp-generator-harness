# Learnings 索引

| 日付 | 要約 | 詳細 |
|---|---|---|
| 2026-09-05 | クロスプラットフォームfixtureは正規化済み期待値と有効入力を使い、最低Python・最新Python・OS差を重複なくCIで分担する | [workflow.md](workflow.md#2026-09-05-cross-platform-ci-fixtures) |
| 2026-09-05 | P1/P2を版付き証跡で固定し、変更時に下流承認を無効化する | [workflow.md](workflow.md#2026-09-05-versioned-design-contract) |
| 2026-09-05 | AI文字は自動検査の代替経路と文字領域マスクを持ち、安全余白と全点一覧を機械検査する | [pipeline.md](pipeline.md#2026-09-05-image-quality-evidence) |
| 2026-09-05 | P8開始時のアカウント確認を永続化し、登録入力とプレビューで制作を完了する | [publish.md](publish.md#2026-09-05-production-completion-boundary) |
| 2026-09-05 | 制作固有の問題はプロジェクト内へ先に記録し、承認済み改善だけを共有ハーネスへ反映する | [workflow.md](workflow.md#2026-09-05-project-learning-promotion) |
| 2026-09-05 | 内部成果物名と外部サービスの提出名を分離し、梱包・検証・公開前検査で同じ境界契約を使う | [pipeline.md](pipeline.md#2026-09-05-submission-filename-boundary) |
| 2026-09-05 | 歴史上の人物は内部の著作権・肖像権等の確認と著名人理由の受付拒否から除外し、公式審査とは分離する | [workflow.md](workflow.md#2026-09-05-historical-figure-exception) |
| 2026-09-05 | 共通層は構造化選択の能力契約、製品アダプタは具体的ツール名を持ち、受付項目の廃止は schema migration と同時に行う | [workflow.md](workflow.md#2026-09-05-structured-intake-contract) |
| 2026-09-05 | 申請時の追加資料は通常の必須確認から外し、外部から要求された場合の任意情報としてだけ検証する | [publish.md](publish.md#2026-09-05-optional-supporting-evidence) |
| 2026-09-03 | 新規プロジェクト作成とP0確定を分け、素材実体と全回答の検証後だけP1へ進める | [workflow.md](workflow.md#2026-09-03-p0-state-transition) |
| 2026-09-03 | 提出PNGの可視性・DPI・境界値とZIP内バイトまで検証し、同一filesystemで安全に梱包する | [pipeline.md](pipeline.md#2026-09-03-submit-pack-validation) |
| 2026-09-03 | 販売地域、AI・写真使用、ライセンス確認、参加設定を明示メタとして法的同意から分離する | [publish.md](publish.md#2026-09-03-registration-declarations) |
| 2026-09-03 | 永続状態の列挙値を変えると旧案件が停止する。schema version と dry-run 既定の原子的移行を同時に用意する | [workflow.md](workflow.md#2026-09-03-project-schema-migration) |
| 2026-09-03 | 共通資産を製品固有ディレクトリに置くと参照がドリフトする。正本・薄いアダプタ・安定 CLI を分離して自動検査する | [workflow.md](workflow.md#2026-09-03-multi-agent-source-of-truth) |
| 2026-09-03 | Windows では `python` と `bash` が PATH にない場合がある。実行環境を先に確認し、Git Bash は絶対パスで呼ぶ | [workflow.md](workflow.md#2026-09-03-windows-runtime-discovery) |
| 2026-09-01 | /bin/sh はブレース展開に非対応。mkdir が失敗して rules が意図しない場所に書かれた | [workflow.md](workflow.md#2026-09-01-brace-expansion) |
