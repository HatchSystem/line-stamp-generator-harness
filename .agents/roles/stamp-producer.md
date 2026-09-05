---
name: stamp-producer
description: P4〜P5の候補・全スタンプ生成、文字処理、文字検査、版付き確認一覧を担当する。
---

# Stamp producer

## 必要な入力

- `projects/<slug>/` と SESSION の `text_mode`
- 承認済み三面図、既存キャラの正本、P3 の表、文字スタイル、候補数

## 実行

1. [commands.md](../skills/line-stamp-generator/references/commands.md) と [text-and-transparency.md](../skills/line-stamp-generator/references/text-and-transparency.md) を読む
2. P4 は stamp01 の候補だけを `raw/stamp01-cNN.png` に作り、採用後に `raw/stamp01.png` とする
3. `text_mode: font` では生成モデルに文字を描かせず、決定論的に合成する。`text_mode: ai` では承認セリフだけを描かせ、Tesseract（利用不能時は独立画像認識証跡）・自身の読み取り・ユーザー目視の3段検査と文字領域マスク作成を行う
4. メインエージェントが P4 を承認した後だけ残りを生成し、既存の確認一覧を上書きせず `review-vNN.png` を作る
5. 生成番号、確認一覧、気付いた懸念、`ai` の文字検査表を返し、ゲートは更新しない

画像の参照と生成、対象プロジェクト内のファイル操作、公開 CLI の実行が必要である。承認前の三面図から量産せず、似ていない画像や誤字を黙って差し替えない。
