# CLAUDE.md — Claude Code アダプタ

@AGENTS.md

共通の行動規範、制作手順、役割定義は `AGENTS.md` と `.agents/` が正本である。このファイルには Claude Code で正本を発見・実行するための差分だけを書く。

## 読み込み

- LINE スタンプの依頼では `.agents/skills/line-stamp-generator/SKILL.md` を最初にすべて読む
- 計画またはレビューの依頼では、対応する `.agents/skills/<name>/SKILL.md` を読む
- 制作再開時は `.agents/learnings/index.md` と、選択中プロジェクトの `SESSION.md` を確認する
- `SKILL.md` から相対リンクされた資料は、そのスキルのディレクトリを基準に解決する

## コマンドアダプタ

`.claude/commands/` の次のファイルは、共通スキルを参照する薄いスラッシュコマンドである。手順本文をここへ複製しない。

- `/line-stamp-generator`
- `/plan`
- `/review`

## 対話

`AskUserQuestion` は必ず作業の区切り後にのみ使用する。共通対話ルールの区切り条件を満たしてからメインエージェントが質問し、回答を受けるまで次の作業を始めない。現在の環境・モードで利用できない場合は、通常のチャットの最終応答で質問してターンを終了する。具体的な提示方法と承認の記録は `AGENTS.md` と共通スキルの対話手順に従う。

## サブエージェント

`.claude/agents/` は `.agents/roles/` を参照するアダプタである。1タスク1役割とし、ゴール、入力、制約、期待する出力を自己完結したプロンプトで渡す。ユーザー承認と `SESSION.md` のゲート更新はメインエージェントだけが行う。

| Gate | role |
|---|---|
| P1〜P2 | `character-designer` |
| P4〜P5 | `stamp-producer` |
| P6 | `pack-validator` |
| P7〜P9 | `publisher` |

## hooks

`.claude/settings.json` は、ベンダー中立な `scripts/hooks/*.mjs` を呼び出してプロジェクト状態を注入し、破壊的コマンド、認証情報入力、LINE の法的同意・不可逆操作を検査する。互換性のため有効化している `.claude/hooks/` も同じ共通 hook を呼ぶ薄いラッパーであり、判定ロジックを持たない。hook に不具合があっても `AGENTS.md` の禁止事項を緩和しない。

Claude Code の個人設定や Auto memory は共有ルールの正本にしない。チームで再発防止すべき知見だけを `.agents/learnings/` に記録する。
