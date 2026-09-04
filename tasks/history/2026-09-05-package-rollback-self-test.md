# 梱包ロールバック自己診断の修正

## 目的

画像変更後のレビュー証跡不一致で自己診断が早期終了する問題を修正し、梱包トランザクションのロールバック処理を正しく試験できるようにする。

## 変更内容

- `stamp01.png` の変更後に、変更後ハッシュを持つ `review-v02` を生成する
- SESSIONの `review_version` を2へ更新してから再梱包する
- `review-v01.json` が上書きされていないことを検証する
- 模擬配置エラーの注入回数へ到達したことを検証する

製品コードの `package_static.py` とレビュー証跡のハッシュ検証には変更を加えていない。

## 確認結果

- `git diff --check`: PASS
- `node --check scripts/check_structure.mjs`: PASS
- `node scripts/check_structure.mjs`: PASS（507 checks）
- `node scripts/hooks/self_test.mjs`: PASS
- `python scripts/line_stamp.py self-test`: 未実行（ローカルにPythonランタイムなし）

## レビュー

- 採用: 指摘どおり、古いレビュー証跡が後段のロールバック試験を遮断していた
- 懸念: 同じレビュー版を再生成すると追記専用契約を破る
- 改善: 新しいレビュー版を追加し、旧版不変と障害注入地点への到達をassertで固定した

## 残課題

CI上のPython自己診断で最終確認する。
