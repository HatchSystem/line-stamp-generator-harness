# line-stamp-generator-harness

Claude Code、Codex、Cursor などの AI エージェントから、同じ手順と安全要件で静止画 LINE スタンプを制作するためのハーネスです。人物写真のキャラクター化、またはオリジナルキャラクターのデザイン踏襲から、検証済み ZIP、申請メタ、LINE Creators Market の登録入力までを P0〜P8 の承認ゲートで進めます。P は Phase（制作フェーズ）の略です。

入力とプレビュー確認で制作プロセスは終了します。「審査をリクエスト」と、その後の追跡・「リリース」はユーザー本人が行います。

## 設計

- **Portable core** — `AGENTS.md` と `.agents/` が唯一の共通正本です。ワークフロー、参照資料、実装、役割、学びを製品別ディレクトリへ複製しません
- **Thin adapters** — `.claude/` `.codex/` `.cursor/` には各製品が正本を発見・実行するための最小設定だけを置きます
- **Stable entry points** — Python 実装の物理パスを外部へ漏らさず、`scripts/line_stamp.py` から呼びます
- **Isolated projects** — 1つのスタンプセット（1申請パッケージ）を `projects/<slug>/` に隔離し、`SESSION.md` と `projects/ACTIVE` で再開可能にします。写真や提出物は Git 管理しません
- **Defense in depth** — `AGENTS.md` の禁止事項を第一の境界とし、利用可能な環境では共通 hook でも破壊的・不可逆操作を止めます
- **Verified structure** — リンク、正本とアダプタの依存方向、役割集合、設定構文を Node の検査で継続的に確認します

## 構成

```text
.
├── AGENTS.md                         # 全エージェント共通の入口・安全規約
├── CLAUDE.md                         # Claude Code の薄い読み込みアダプタ
├── .agents/                          # ベンダー中立な正本
│   ├── skills/
│   │   ├── line-stamp-generator/     # SKILL.md、references、assets、Python 実装
│   │   ├── plan/
│   │   └── review/
│   ├── roles/                        # 4つの役割本文
│   └── learnings/                    # チーム共有の索引・知見・記録方針
├── .claude/                          # commands、agents、settings/hooks アダプタ
├── .codex/                           # agents、hooks アダプタ
├── .cursor/                          # agents、hooks アダプタ
├── scripts/
│   ├── line_stamp.py                 # 安定した公開 CLI
│   ├── check_structure.mjs           # 構成・参照・境界検査
│   └── hooks/                        # 共通ポリシーと製品別出力アダプタ
├── tasks/                            # ハーネス変更の計画・履歴
└── projects/<slug>/                  # SESSION、LEARNINGS、素材、text-masks、review、submit、meta
```

依存方向は常に「製品別アダプタ → `AGENTS.md` / `.agents/` / `scripts/`」です。`.agents/` から `.claude/` `.codex/` `.cursor/` を参照しません。Windows でも扱いやすいよう、symlink は使いません。

## 対応環境

| エージェント | 共通指示・スキル | 製品別アダプタ |
|---|---|---|
| Claude Code | `CLAUDE.md` の `@AGENTS.md` と `.agents/skills/` | `.claude/commands/`、`.claude/agents/`、`.claude/settings.json` と共通 hook への互換ラッパー |
| Codex | `AGENTS.md` と `.agents/skills/` | `.codex/agents/*.toml`、`.codex/hooks.json` |
| Cursor | `AGENTS.md` と `.agents/skills/` | `.cursor/agents/`、`.cursor/hooks.json` |
| その他 | `AGENTS.md` を入口に `.agents/skills/` を直接読む | 必要な場合だけ薄いアダプタを追加 |

hook の有効化や信頼確認は各ツール側の仕様に従います。hook が使えない環境でも `AGENTS.md` の禁止事項は変わりません。

## 必要環境

- Python 3.10 以上と `requirements.txt` の依存関係（画像処理・プロジェクト CLI）
- Node.js 24 以上（構成検査と共通 hook）
- 対応 OS は Ubuntu、Windows、macOS。CI は最低 Python 3.10 を Ubuntu で、最新 Python 3.14 を3 OSで検証
- `text_mode: ai` はTesseract、日本語データ、`pytesseract`を推奨。利用不能時は独立した画像認識モデルの版付き証跡が必要
- P1〜P5 には画像を参照・生成または編集できるエージェント機能、P8 にはログイン済みページを扱えるブラウザ機能

`python` というコマンド名は環境により `python3` または `py` に読み替えてください。

画像機能がない場合はユーザーが用意した画像を各ゲートで確認し、画像生成工程を完了したことにしません。ブラウザ機能がない場合は P8 の入力チェックリストと値を提示し、ユーザーが入力します。どちらの場合も承認ゲートと不可逆操作の境界は維持します。

## セットアップと検証

リポジトリルートで実行します。

```powershell
python -m pip install -r requirements.txt
node scripts/check_structure.mjs
node scripts/hooks/self_test.mjs
python scripts/line_stamp.py self-test
```

期待結果は各検査の `PASS` です。Python がまだ導入されていない環境でも、Node による構成・hook 検査は独立して実行できます。

GitHub Actions は、Ubuntu + Python 3.10 で全品質検査を1回実行し、Ubuntu / Windows / macOS + Python 3.14 で公開Python CLIのOS互換性を検査します。最低・最新Python版と主要3 OSを4ジョブで分担し、Node検査の重複と過剰な直積を避けます。同じrefの古い実行は自動キャンセルし、外部 Action は検証済みコミット SHA に固定します。

依存関係のインストールはエージェントへ自動許可していません。内容を確認したユーザーが上のコマンドを実行してください。秘密情報は `.env` や個人設定に置き、リポジトリへコミットせず、エージェントにも読み取らせません。

## 使い方

1. 対応する AI エージェントをリポジトリルートで起動し、「この写真で LINE スタンプを作りたい」などと依頼します
2. 進行中のプロジェクトがあれば「続ける / 別を選ぶ / 新規作成」から選びます
3. 新規なら隔離された P0 プロジェクトを先に作って素材を `refs/` に置き、P0 で素材種別、枚数、セリフ、文字方式、候補数、LINE への申請意図を確定します。成年、本人許諾、著作権／ライセンスは質問しません。歴史上の人物と明示された題材は著作権・肖像権などの確認対象外です。`confirm-p0` が一括保存して P1 へ進めます
4. P1で髪形、数値の頭身、服装、配色、目、装飾、背景透過、参考画像を版付きデザイン証跡へ固定し、P2〜P5で三面図、セリフ表、`stamp01`、全点を順に承認します。P5では全画像を1枚にした確認一覧を必ず提示します
5. P6 で内部の `stampNN.png` を Creators Market 用の `NN.png` へ変換して梱包し、画像とZIPの検証を通します。`publish: yes` の場合だけ P7 へ進み、申請メタを検証・承認します。`local-only` は P6 で終了します
6. P8開始時にアカウント名、販売者ID、登録先を確認・記録し、入力直前にも再照合します。登録入力とプレビューのサマリを確認すると制作完了になり、「制作が完了しました。問題なければ審査リクエストを実施してください。」と表示されます

`text_mode: font` は生成画像と文字を分離し、フォントで決定論的に合成する推奨方式です。`text_mode: ai` はP4とP5で「Tesseract（利用不能時は独立画像認識）→ エージェントの目視読み上げ → ユーザー確認」を必須にします。文字領域マスクにより文字内の穴だけを除外し、キャラクター領域の微小穴検査は省略しません。

ログインはユーザー自身で済ませてください。エージェントは ID、パスワード、認証コードを入力しません。

## プロジェクト管理

```powershell
python scripts/line_stamp.py project --root . list
python scripts/line_stamp.py project --root . new --slug usagi
python scripts/line_stamp.py project --root . confirm-p0 --materials received --source photo --count 16 --text yes --text-mode font --character-name ハッチくん --sample-candidates 1 --publish yes
python scripts/line_stamp.py project --root . confirm-design --image refs/design-v01.png --reference refs/source.png --hairstyle "短い髪" --head-ratio 2.2 --clothing "青い上着" --color "#1A2B3C" --eyes "丸い目" --accessories "なし"
python scripts/line_stamp.py project --root . confirm-three-view --image refs/three-view-v01.png
python scripts/line_stamp.py project --root . record-learning --gate P5 --kind problem --summary "余白不足" --impact "検証停止" --cause "上端へ寄り過ぎ" --resolution "自動縮小" --candidate "生成時に安全余白を固定"
python scripts/line_stamp.py project --root . confirm-account --account-name "表示名" --seller-id "販売者ID" --registration-target "新規スタンプ登録"
python scripts/line_stamp.py project --root . complete-production --account-name "表示名" --seller-id "販売者ID" --registration-target "新規スタンプ登録" --preview-confirmed
python scripts/line_stamp.py project --root . use usagi
python scripts/line_stamp.py project --root . status
```

slug は小文字英数字とハイフンの2〜40文字で、実名、Windows の予約デバイス名、ハーネス予約名 `active` を使いません。

画像処理、文字検査、確認一覧、梱包、公開前検査の全コマンドは [commands.md](.agents/skills/line-stamp-generator/references/commands.md) を参照してください。スキル内部の `.py` は直接実行しません。公開 CLI は `projects/ACTIVE` と実処理パスがこのリポジトリの同じプロジェクトを指すことを検証し、ACTIVE の変更と同一プロジェクトの状態・成果物更新を協調ロックで直列化します。別エージェントが更新中なら失敗終了するため、完了後に再実行してください。

### 旧プロジェクトの移行

従来形式のプロジェクトは、先に `use <slug>` で選択してから診断します。既定では読み取りだけで、変更予定を表示します。

```powershell
python scripts/line_stamp.py project --root . migrate
python scripts/line_stamp.py project --root . migrate --apply
```

`--apply` を明示した場合だけ、同じプロジェクト内にバックアップを作り、各ファイルを同一 filesystem 上で原子的に置換します。捕捉できる途中失敗はバックアップから巻き戻します。SESSION schema v4 への移行ではP1/P2証跡、文字マスク、P8アカウントの項目を未確認状態で追加し、旧P9と審査後状態を制作完了へ意味を保って移します。旧 `adult`、`consent`、`rights` と空の既定値だった `license_proof` は削除します。未知値、不正・重複キー JSON、未来バージョンがある場合は一切書き換えません。

## 別のエージェントを追加する

1. その製品が `AGENTS.md` と `.agents/skills/` を直接検出できるか確認します
2. 自動検出できない部分だけ、製品固有ディレクトリに薄い参照アダプタを追加します
3. サブエージェント機能がある場合は `.agents/roles/` の4役を参照し、本文をコピーしません
4. PreToolUse 相当の hook がある場合は `scripts/hooks/pre_tool_use.mjs` に製品名を渡します。互換用の製品別 hook ファイルが必要でも、その中では共通 hook を呼ぶだけにし、判定ロジックを再実装しません
5. `node scripts/check_structure.mjs` と `node scripts/hooks/self_test.mjs` を通します

製品固有の機能を共通要件として書かないこと、共通層から製品固有層への逆参照を作らないことが追加時の基準です。

## LINE の仕様

サイズ、枚数、申請テキスト、審査条件は [line-specs.md](.agents/skills/line-stamp-generator/references/line-specs.md) に整理しています。ただし、LINE Creators Market の現行公式ガイドラインを常に優先します。P6 と P8 で公式ページを再確認し、差分は `.agents/learnings/publish.md` に記録します。
