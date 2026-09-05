# 制作完了境界と品質証跡の強化

## 完了内容

- 制作PhaseをP0〜P8へ限定し、P8の登録入力・保存・プレビュー確認を `production-complete` とした。審査リクエスト、審査追跡、リリースを現行ゲートから除外し、指定の制作完了文を公開CLIから完全一致で表示する
- P8開始時にアカウント名、販売者ID、登録先を保存し、完了時に同じ3項目を再入力して照合する。`--preview-confirmed` がなければ完了しない
- P1の髪形、数値頭身、服装、HEX配色、目、固定装飾、背景透過、参考画像を版付きMarkdown/PNG/JSONへ固定し、P2三面図を現在のP1証跡へ結び付けた。P1変更時はP2以降の状態を無効化する
- AI文字はTesseractを優先し、利用不能時だけ独立画像認識JSONを使用する。自動経路がなければP6をブロックし、最終画像と同寸の版付き文字領域マスクを作る
- AI文字の穴検査を全体省略せず、二値・60%以下の文字領域マスク内に完全に収まる穴だけを除外する。可視内容は12px以上、目標16pxへ自動調整する
- P5確認一覧を全点・番号順・白/濃色背景の証跡として固定した。`validate_pack.py` の未定義 `found_names` 参照も修正した
- 新規・移行プロジェクトへ `LEARNINGS.md` を作り、問題・教訓を安全に追記する公開CLIと、改善依頼時の読み取り・提案・承認・昇格手順を追加した
- SESSIONをschema v4へ更新し、submission schema v3と分離した。旧P9と審査後状態は元値をnotesへ残して制作完了へ移行する

## 確認結果

- `git diff --check`: PASS
- `node --check scripts/check_structure.mjs`: PASS
- `node scripts/check_structure.mjs`: PASS（544 checks）
- `node scripts/hooks/self_test.mjs`: PASS
- `python scripts/line_stamp.py self-test`: 未実行。作業環境に `python`、`python3`、`py` が存在しないため。Python 3.10/3.14のCI検証対象として残す

## /review

- 違反: なし。禁止された削除、force push、不可逆なCreators Market操作、認証情報の読み取り・保存は行っていない
- 懸念: ローカルPython不在のため、Python自己診断の実行証跡はない。独立画像認識証跡の実運用は利用環境の画像認識手段に依存する
- 改善案: CIでPython 3.10/3.14の自己診断を必須のまま維持し、実案件のP4前にTesseractまたは独立画像認識の可用性を確認する

## 学び

実制作で判明した6件を `.agents/learnings/{workflow,pipeline,publish}.md` に「事象・原因・対処・再発防止」で記録し、索引へ追加した。
