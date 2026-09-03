# ゲート運用ルール

- ゲートは P0→P9 の順に進め、1ターンで複数ゲートを飛ばさない。現在地は選択中プロジェクト（`projects/ACTIVE`）の `projects/<slug>/SESSION.md` にある `gate` が正
- 「OK」「続けて」「いいね」「それで」は現在ゲートの承認。差し戻しでは該当ゲートに留まり、成果物名の版番号を上げる
- 承認は必ずメインエージェントがユーザーから取る。サブエージェントはゲートを進めない
- `text_mode: ai` は P4 で 01、P5 で全点の文字検査（`verify_text.py` ＋ エージェント読み取り ＋ ユーザー目視承認）を通し、P5 の完了条件に `text_check: ok` を加える。OCR 結果だけで ok にしない
- P6 は `validate_pack.py` errors=0、P7 は `check_publish_ready.py` errors=0 が完了条件
- P8 に入る条件: `publish: yes` `consent: yes` `adult: yes` `rights: own|licensed` `validation: ok`（`ai` は `text_check: ok` も）がすべて揃い、P7 のメタが承認済み
- P8 は登録入力とサマリ提示で停止。審査リクエストはユーザーが押し、報告を受けて `submission: requested` に更新する
- P9 で却下されたら理由を転記し、対応表（skill references/publish.md）で戻り先を決める

## SESSION の必須フィールド

```text
project / source(photo|character) / count(8|16|24|32|40) / text(yes|no) / text_mode(font|ai|none) / text_check(not-run|ok|failed|n/a) / gate / character
rights(own|licensed|unknown) / adult(yes|no|unknown) / consent(yes|no|unknown) / publish(yes|no|private)
lock / three_view / sample_candidates(1-3) / sample / review_version
validation(not-run|ok|failed) / submission(not-started|drafted|requested|approved|rejected|released)
notes
```

SESSION はプロジェクトごとに1つだけ。他プロジェクトの SESSION を読み書きしない。承認・差し戻し理由・文字スタイル・検証結果・審査結果を `notes` に短く残す。

詳細表と P0 の質問項目: `.claude/skills/line-stamp-generator/references/gates.md`
