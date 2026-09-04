# 歴史上の人物の権利チェック除外

## 目的

ユーザーが歴史上の人物を題材として明示した案件を、著作権・肖像権・パブリシティ権・本人許諾・ライセンス証明の内部確認と、著名人を理由とする受付拒否から除外する。

## 変更内容

- 共通規約と line-stamp-generator スキルへ歴史上の人物の例外を追加
- 現存著名人の拒否と歴史上の人物の受付を分離
- 対話、素材安全、既存キャラクター、公式仕様資料、READMEを同期
- P0〜P8で内部の権利確認を追加せず、LINE画面自体が資料を求めた場合はユーザーへ報告して停止する境界を明記
- 7つの正本で例外が欠落した場合に失敗する構成検査を追加

SESSION schema、CLI引数、画像処理、梱包処理には変更を加えていない。

## 確認結果

- `git diff --check`: PASS
- `node --check scripts/check_structure.mjs`: PASS
- `node scripts/check_structure.mjs`: PASS（516 checks）
- `node scripts/hooks/self_test.mjs`: PASS
- skill-creator の `quick_validate.py`: 未実行（ローカルにPythonランタイムなし）。Node構成検査でfrontmatter、参照、正本構造を検証済み

## レビュー

- 違反: なし
- 懸念: 歴史上の人物の内部チェック除外は、LINE公式審査や販売承認を保証しない
- 改善: 例外の適用条件を「ユーザーが歴史上の人物と明示」に固定し、公式審査との境界を同じ変更セットで記録した

## 残課題

なし。
