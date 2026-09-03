# CLAUDE.md — Claude Code アダプタ

@AGENTS.md

行動規範は上記 AGENTS.md がすべてである。このファイルは Claude Code 固有の読み込みマップと運用だけを書く。

## セッション開始時

1. `session-start.sh` hook が `projects/` の一覧と `ACTIVE` を注入する。制作依頼を受けたら、進行中があれば「続ける / 別を選ぶ / 新規作成」を `AskUserQuestion` で提示し、`project.py use` または `new` で確定する。確定した `projects/<slug>/SESSION.md` の `gate` から再開する
2. 制作依頼を受けたら `/line-stamp-generator` スキルを読む（`.claude/skills/line-stamp-generator/SKILL.md`）
3. `.claude/learnings.md` を読み、過去のミスを繰り返さない

## オンデマンド読み込みマップ

| 場面 | 読むファイル |
|---|---|
| ゲートの条件・SESSION 形式 | @.claude/rules/gates.md |
| 質問の出し方・承認語 | @.claude/rules/dialogue.md |
| 画像処理・文字合成の不変条件 | @.claude/rules/image-processing.md |
| 文字入れ方式と文字検査手順 | .claude/skills/line-stamp-generator/references/text-and-transparency.md, commands.md |
| LINE 仕様・審査・テキスト制限 | @.claude/rules/line-compliance.md |
| 写真・権利・ログイン情報の扱い | @.claude/rules/privacy-security.md |
| 学びの記録方法 | @.claude/rules/learnings-policy.md |
| 写真からの特徴固定 | .claude/skills/line-stamp-generator/references/portrait.md |
| 既存キャラの踏襲 | .claude/skills/line-stamp-generator/references/character-base.md |
| コマンドと manifest | .claude/skills/line-stamp-generator/references/commands.md |
| 申請メタ・登録入力・審査追跡 | .claude/skills/line-stamp-generator/references/application.md, publish.md |

`.claude/rules/*.md` は自動読み込みされるため、上の @ 参照は重複読み込みしない。

## スラッシュコマンド（スキル）

- `/plan` — 実行サイクル Step 1。`tasks/todo.md` を作る
- `/review` — 実装・成果物のルール適合レビュー（P5 の確認一覧、P7 のメタ案にも使う）
- `/line-stamp-generator` — 制作本体
- コンテキスト使用量が 50% に達したら `/compact` を実行する。SESSION が正なので圧縮しても再開できる

## サブエージェント

| ゲート | エージェント | 渡すもの |
|---|---|---|
| P1〜P2 | `character-designer` | 素材パス、入力種別、P0 の確定事項 |
| P4〜P5 | `stamp-producer` | 承認済み三面図、P3 の表、文字スタイル |
| P6 | `pack-validator` | プロジェクトディレクトリ、count |
| P7〜P9 | `publisher` | SESSION、submit ZIP、meta/submission.json |

- 1タスク1サブエージェント。ゴール・前提・出力形式を自己完結したプロンプトで渡す（親の文脈は引き継がれない）
- ユーザー承認はメインエージェントが取る。サブエージェントはゲートを進めない
- サブエージェントの TODO は `tasks/subagents/<agent>-<topic>.md` に分離する

## hooks（`.claude/settings.json`）

| フック | 役割 |
|---|---|
| `hooks/session-start.sh` (SessionStart) | `project.py list` の結果と `ACTIVE` を注入し、プロジェクト選択を促す |
| `hooks/block-dangerous.py` (PreToolUse: Bash) | `rm -rf`、`git push --force`、`projects/` `submit/` の削除、提出 ZIP への写真混入をブロック |
| `hooks/guard-submit.py` (PreToolUse: MCP ツール全般) | 「審査をリクエスト」「リリース」「削除」等のクリック、パスワード入力をブロック |
| `hooks/gate-reminder.sh` (UserPromptSubmit) | 選択中プロジェクトの現在ゲートを注入し、飛ばしを防ぐ。未選択なら選択を促す |

ブロックされたら回避策を探さず、ユーザーに操作を依頼する。

## Auto memory と learnings/ の棲み分け

- Auto memory: 個人の好み・環境固有の気づき
- `.claude/learnings/`: Git 管理されるチーム共有の知見。実行サイクル Step 7 の記録先は必ずこちら

## 選択肢の提示

選べる項目（プロジェクト、素材種別、枚数、文字有無、文字の入れ方 font/ai、候補数、公開予定、採用番号、差し戻し箇所、文字検査の結果 全点正しい/誤字あり）は `AskUserQuestion` で選択肢を出す。自由記述が必要なもの（キャラ名、セリフの差し替え）だけ文章で聞く。

## 行数制約

`AGENTS.md` `CLAUDE.md` は各 100 行前後、最大 200 行。超える場合は `.claude/rules/` へ分割する。
