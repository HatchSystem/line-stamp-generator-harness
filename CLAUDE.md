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

プロジェクト選択、素材種別、枚数、文字方式、候補、採用案、差し戻し箇所、文字検査結果など、有限の選択肢で答えられる質問には `AskUserQuestion` を使う。関連する質問は1回に最大3問までまとめ、推奨案を先頭に置き、相互排他的な短い選択肢と選択時の影響を示す。`AskUserQuestion` を利用できない環境だけ、同じ順序の番号付き選択肢へフォールバックする。キャラクター名やセリフ差し替えのように自由記述が必要な質問だけ文章で聞く。

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
