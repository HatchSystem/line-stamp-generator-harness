# Creators Market 提出ファイル名境界の修正

## 目的

内部正本 `stamps/stamp01.png`〜`stampNN.png` を維持しながら、Creators Market が認識する `01.png`〜`NN.png` を提出ディレクトリとZIPに生成する。

## 変更内容

- 内部名と提出名の共有命名関数を追加
- `package-static` で番号対応の変換を行い、ZIP memberを `main.png`、`tab.png`、`01.png`〜`NN.png` に限定
- P6とP7を共通の提出名検証へ統合し、提出 `NN.png` をレビュー済み `stamps/stampNN.png` とバイト比較
- 旧 `submit/stampNN.png` を削除せず警告し、新ZIPから除外
- 自己診断へ5種類の許可枚数、欠品、余剰、旧名、大文字拡張子、改ざん、ロールバックの回帰試験を追加
- AGENTS、スキル、役割、コマンド、申請手順、仕様メモ、README、構造検査を同じ契約へ同期

## 確認結果

- `git diff --check`: PASS
- `node --check scripts/check_structure.mjs`: PASS
- `node scripts/check_structure.mjs`: PASS（521 checks）
- `node scripts/hooks/self_test.mjs`: PASS
- `python scripts/line_stamp.py self-test`: 未実行（ローカルに `python`、`python3`、`py`、`uv` がないため）。Ubuntu / Windows × Python 3.10 / 3.14 のCIで実行される構成と回帰試験コードは確認済み

## レビュー

- 違反: なし
- 懸念: Python自己診断はこの端末では実行できておらず、実動確認はCI結果が必要
- 改善: 外部提出境界だけで改名し、P6/P7の検査を共通化した。旧提出物は破壊せず、誤って再利用されないよう警告とZIP完全一致検査を追加した

## 残課題

- CIのUbuntu / Windows × Python 3.10 / 3.14で `python scripts/line_stamp.py self-test` がPASSすることを確認する
