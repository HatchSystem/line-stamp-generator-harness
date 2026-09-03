# projects/

スタンプ1つにつき1プロジェクト。`project.py new --slug <slug> ...` で作成し、`ACTIVE` に選択中の slug が入る。
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
    ├── text-layers/       # 文字層
    ├── stamps/            # 合成済みスタンプ
    ├── review/            # review-vNN.png（差し戻しごとに版を上げる）
    ├── submit/            # main.png / tab.png / stampNN.png / ZIP / 検証ログ
    └── meta/              # submission.json
```

- slug は英小文字・数字・ハイフンのみ。被写体の実名は使わない
- 他プロジェクトのファイルを参照・変更しない
- 不要になったプロジェクトはエージェントに削除させず、自分で `tmp/` へ移動する
