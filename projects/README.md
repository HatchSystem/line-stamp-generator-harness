# projects/

スタンプセット（1申請パッケージ）1つにつき1プロジェクト。リポジトリルートで `python scripts/line_stamp.py project --root . new --slug <slug>` を実行すると P0 の隔離先が作られ、`ACTIVE` に選択中の slug が入る。素材を `refs/` に置き、P0 承認後に `project ... confirm-p0` で確定状態を保存する。
このディレクトリは写真と SESSION を含むため `README.md` 以外は Git 管理外。

```
projects/
├── ACTIVE                 # 選択中の slug（1行）
└── <slug>/
    ├── SESSION.md         # 状態の正本（gate / count / rights / submission ...）
    ├── plan.md            # P3 で承認したセリフ・表情・ポーズ表
    ├── refs/              # 提供写真・原作画像・特徴ロック・三面図（提出しない）
    ├── raw/               # 生成モデルの出力
    ├── characters/        # 前処理済みキャラクター
    ├── character-layers/  # 文字合成前のキャラ層
    ├── text-layers/       # `font` の透明文字層（`ai` は生成画像へ焼き込み、`none` は空）
    ├── fonts/             # 利用許諾を確認した合成用フォント（提出しない）
    ├── stamps/            # 合成済みスタンプ
    ├── review/            # review-vNN.png（差し戻しごとに版を上げる）
    ├── submit/            # main.png / tab.png / stampNN.png / ZIP / 検証ログ
    └── meta/              # submission.json / ai-provenance.md（AI使用時）
```

- slug は `^[a-z0-9][a-z0-9-]{1,39}$`（2〜40文字、先頭は英小文字または数字）に合わせ、被写体の実名は使わない
- 他プロジェクトのファイルを参照・変更しない
- 旧形式は対象を `use` した後、`project --root . migrate` で診断し、確認後だけ `--apply` する
- 不要になったプロジェクトはエージェントに削除させず、自分で `tmp/` へ移動する
