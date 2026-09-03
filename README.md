# line-stamp-generator-harness

人物写真のキャラクター化、または既存オリジナルキャラクターのデザイン踏襲で、静止画 LINE スタンプを AI エージェントと対話しながら制作し、LINE Creators Market の登録入力まで進めるためのハーネスです。ハーネス本体と制作物を分けたモノレポ構成で、複数のスタンプをプロジェクト単位で並行して制作できます。

## 設計思想

1. **ハーネスと制作物の分離**: `AGENTS.md` `.claude/` `scripts/` がハーネス本体。制作物は `projects/<slug>/` に隔離し、制作中にハーネスを壊さない
2. **単一情報源**: 行動規範は `AGENTS.md` に一元化。`CLAUDE.md` は Claude Code 用アダプタで、`@AGENTS.md` を読み込むだけ
3. **指示は文書、強制は hooks**: 「守ってほしいこと」は Markdown、「必ず守らせること」（破壊的コマンド、審査リクエスト・リリースのクリック、認証情報の入力、プロジェクト未選択での制作開始）は hooks で機械的に扱う
4. **選択肢で進める**: 選べる項目はエージェントが選択肢を提示し、ユーザーは選ぶだけ
5. **不可逆操作はユーザーが行う**: 「審査をリクエスト」「リリース」はユーザー本人が押す
6. **学びの蓄積**: ミス・仕様差異・審査却下理由を `.claude/learnings/` に記録し共有

## フォルダ構成

```
line-stamp-generator-harness/
├── AGENTS.md                      # 単一情報源: 目的・原則・P0〜P9・品質基準・禁止事項
├── CLAUDE.md                      # Claude Code アダプタ（@AGENTS.md + 読み込みマップ + 固有運用）
├── README.md / requirements.txt / .gitignore / .env.example
├── .claude/                       # ハーネス本体
│   ├── settings.json              # permissions + hooks
│   ├── settings.local.json.example
│   ├── hooks/
│   │   ├── session-start.sh       # SessionStart: プロジェクト一覧と ACTIVE を注入
│   │   ├── gate-reminder.sh       # UserPromptSubmit: 選択中プロジェクトの現在ゲートを注入
│   │   ├── block-dangerous.py     # PreToolUse(Bash): rm -rf, force push, projects/ 削除, ZIP への写真混入
│   │   └── guard-submit.py        # PreToolUse(MCP): 審査リクエスト・リリース・削除のクリック、認証情報入力
│   ├── rules/                     # 常時読み込みルール
│   ├── agents/                    # サブエージェント（character-designer / stamp-producer / pack-validator / publisher）
│   ├── skills/
│   │   ├── line-stamp-generator/  # 制作本体: SKILL.md + references + scripts（project.py を含む）
│   │   ├── plan/                  # /plan → tasks/todo.md
│   │   └── review/                # /review → ルール適合レビュー
│   ├── learnings.md               # 学びの索引
│   └── learnings/
├── scripts/check-refs.sh          # ドキュメント参照パスの整合チェック
├── tasks/                         # todo.md（.gitignore）・todo.md.template・history/・subagents/
└── projects/                      # 制作物（.gitignore）
    ├── README.md
    ├── ACTIVE                     # 選択中の slug
    └── <slug>/                    # SESSION.md / plan.md / refs / raw / ... / submit / meta
```

## セットアップ

```bash
pip install -r requirements.txt
# 生成AIで文字を入れる場合のみ（OCR 照合）: tesseract 本体と日本語データも必要
pip install pytesseract
cp .env.example .env                                   # 任意
cp .claude/settings.local.json.example .claude/settings.local.json   # 任意
bash scripts/check-refs.sh                             # 参照整合性
python3 .claude/skills/line-stamp-generator/scripts/self_test.py     # PASS が出れば OK
```

hooks の動作確認:

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf projects"}}' | python3 .claude/hooks/block-dangerous.py
echo '{"tool_name":"mcp__browser__click","tool_input":{"element":"審査をリクエスト","url":"https://creator.line.me/"}}' | python3 .claude/hooks/guard-submit.py
CLAUDE_PROJECT_DIR=. bash .claude/hooks/session-start.sh
```

前2つは `"permissionDecision": "deny"` を含む JSON、3つ目はプロジェクト一覧が出れば正常です。

## 使い方

1. Claude Code をリポジトリのルートで起動し、「この写真でLINEスタンプを作りたい」などと依頼する
2. 進行中のプロジェクトがあれば「続ける / 別を選ぶ / 新規作成」の選択肢が出るので選ぶ
3. 新規なら P0 の質問（素材の種類・枚数・文字・文字の入れ方・キャラ名・公開予定）に選択肢で答える。文字の入れ方は「埋め込みフォント（推奨・誤字ゼロ）」か「生成AI（手書き風など。誤字検査あり）」。エージェントが `projects/<slug>/` を作る
4. P1〜P7 で特徴ロック → 三面図 → セリフ表 → stamp01 → 全点 → 検証 → メタ案を順に承認する。生成AIで文字を入れる場合は stamp01 と全点の段階で「OCR 照合 → エージェントが各画像の文字を読み上げ → あなたが『全点正しい / 誤字あり』を選ぶ」検査が入る
5. P8 でエージェントが Creators Market に登録入力し、サマリを提示して止まる。内容を確認して**自分で**「審査をリクエスト」を押す
6. 承認されたら**自分で**「リリース」を押す。却下ならエージェントが理由を分類して該当ゲートへ戻る

別のスタンプを作るときは新規プロジェクトを作るだけです。既存プロジェクトの画像や SESSION には影響しません。

ログインは自分で済ませ、ログイン済みの画面をエージェントに渡してください。エージェントは ID・パスワード・認証コードを入力しません。

## プロジェクト管理コマンド

```bash
python3 .claude/skills/line-stamp-generator/scripts/project.py list
python3 .claude/skills/line-stamp-generator/scripts/project.py new --slug usagi --source photo --count 16 --text yes
python3 .claude/skills/line-stamp-generator/scripts/project.py use usagi
python3 .claude/skills/line-stamp-generator/scripts/project.py status
```

## 他の AI エージェントで使う場合

`AGENTS.md` と `.claude/skills/line-stamp-generator/` は純粋な Markdown と Python なので、Codex・Cursor などでもそのまま使えます。hooks がない環境では、開始時に `project.py list` を自分で実行してプロジェクトを確定し、`AGENTS.md` の「ツール固有機能の扱い」に従って破壊的コマンドと不可逆操作を実行前に自己確認してください。ブラウザ操作の手段は固定していません。実行環境で使えるものを使い、`references/publish.md` の手順に従ってください。

## LINE の規約について

枚数（8/16/24/32/40）、画像サイズ、テキスト制限、審査基準は `.claude/rules/line-compliance.md` にまとめていますが、公式の制作ガイドライン・審査ガイドラインが常に優先です。P6 と P8 で公式ページを確認し、差異があれば `.claude/learnings/publish.md` に記録してルールを更新してください。
