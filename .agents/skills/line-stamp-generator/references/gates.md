# 承認ゲートと状態

`P` は Phase（制作フェーズ）の略である。制作プロセスは P0〜P8 とし、審査リクエスト、審査追跡、リリースは含めない。

## ゲート

| Gate | 成果物 | 次へ進む条件 |
|---|---|---|
| P0 | 受付情報 | 入力種別・素材・枚数・文字・キャラ名・候補数・申請意図が確定し、`confirm-p0` が P1 へ更新 |
| P1 | 髪形、数値の頭身、服装、HEX配色、目、固定装飾、背景透過、参考画像を示す版付きデザインシート | ユーザー承認後、`confirm-design` で画像・仕様・参考画像のハッシュを固定 |
| P2 | 現在のP1証跡に結び付いた正面・斜め・決めポーズの版付き三面図 | ユーザー承認後、`confirm-three-view` で固定 |
| P3 | 全点のセリフ・表情・ポーズ表 | ユーザーが計画を承認 |
| P4 | stamp01の候補（1〜3枚）と採用案。`ai` は 01 の文字検査結果も | ユーザーがキャラ、誤字、切り抜き、文字装飾を承認 |
| P5 | 残りと全画像を1枚に載せた版付き確認一覧。`ai` は自動文字検査と文字領域マスクも | ユーザーが一覧を承認し、`ai` は三段階検査を完了（`text_check: ok`、`text_mask_version: N`） |
| P6 | main、tab、全スタンプ、検証ログ、ZIP | `self-test` PASS、`validate-pack` errors=0 |
| P7 | タイトル・説明・クリエイター名・コピーライト・価格・販売エリア・申告/参加設定案 | `check-publish-ready` errors=0、ユーザーがメタを承認 |
| P8 | 確認済みアカウントへの Creators Market 登録内容とプレビュー | アカウント名・販売者ID・登録先を記録し、入力サマリ確認後に `complete-production` を実行 |

「OK」「続けて」「いいね」「それで」は現在のゲートの承認として扱う。修正依頼では該当ゲートに留まり、修正版の成果物名に版番号を付ける。1ターンで複数ゲートを飛ばさない。承認は必ずメインエージェントがユーザーから受け取り、サブエージェントはゲートを進めない。質問の出し方は [dialogue.md](dialogue.md) に従う。

P6 は公開 CLI の `self-test` が PASS し、`validate-pack` が errors=0 になったときだけ完了する。結果を報告してそのターンを終了する。`publish: local-only` なら `submission: local-complete` として終了し、ローカル確認用成果物は LINE 上で配布・利用できないことを伝える。公開する場合、P7 は次のターンで始める。P7 は `check-publish-ready` が errors=0 で、ユーザーがメタを承認したときに `submission: drafted` として完了する。P8 に入るには `publish: yes`、`validation: ok`、`submission: drafted` が必要である。`text_mode: ai` では `text_check: ok` と正の `text_mask_version` も必要である。P8 は登録入力とプレビュー確認を終えて `submission: production-complete` に更新し、「制作が完了しました。問題なければ審査リクエストを実施してください。」と表示して終了する。

## P0で確定する項目

既に分かっている項目は聞き直さない。

- 入力種別: `photo`（人物写真をキャラクター化）／`character`（既存キャラクターのデザインを踏襲）
- 素材。新規選択後に P0 プロジェクトを作り、正本にする1枚をその `refs/` に置いて `materials: received` とする。既存キャラなら設定画・正面画を優先
- 枚数: 8/16/24/32/40 のいずれか（LINE規定。他の数は受け付けない）
- 文字あり/なし
- 文字ありなら入れ方: `font`（埋め込みフォント。生成モデルによる文字崩れを避ける既定方式）／`ai`（生成AIに描かせる。誤字が出るため検査工程が入る）。`font` でも原文、欠字、可読性は P4/P5 で目視する
- キャラ名（申請時のタイトル・説明に使う表示名。実名は使わない）
- 01の候補生成数: 1〜3（既定1）
- `publish`: LINE へ審査申請する意図。`yes` または `local-only`（ローカル確認用成果物。LINE 上で配布・利用不可）

新規作成は P0 より前に `project ... new --slug <slug>` で隔離先だけを作る。全項目をユーザーへ復唱して承認を得た後、公開 CLI の `project ... confirm-p0` を使う。このコマンドだけが P0 の全項目を検証・保存して `gate: P1` へ進める。値の矛盾があれば無変更で停止する。`adult`、`consent`、`rights` は質問・保存・ゲート判定を行わない。

## SESSION

`projects/<slug>/SESSION.md` がプロジェクトの唯一の状態。他プロジェクトとは共有しない。

```text
schema_version / project / materials / source / count / text / text_mode / text_check / text_mask_version / gate / character
publish
lock / design_version / design_evidence / three_view / three_view_version / sample_candidates / sample / review_version
validation / submission / notes
account_name / seller_id / registration_target / account_confirmed_at
```

- `schema_version`: 現行は `4`。旧形式は制作再開前に公開 CLI の `project --root . migrate` で診断する
- `text_mode`: `font` `ai` `none`（`text: no` のとき）
- `text_check`: `not-run` `ok` `failed` `n/a`（`ai` 以外は `n/a`。自動検査だけで `ok` にせず、エージェントの読み上げとユーザー承認後に更新）
- `text_mask_version`: `ai` のP6では最終 `text-check-vNN` と一致する正の版番号。それ以外は `0`
- `materials`: `pending` `received`
- `publish`: LINE への審査申請意図を表す `yes` `local-only` `unknown`（`local-only` はローカル確認用で、LINE 上では配布・利用できない）
- `validation`: `not-run` `ok` `failed`
- `submission`: `not-started` `local-complete` `drafted` `production-complete`

ユーザーの承認、差し戻し理由、文字スタイル、検証結果を `notes` に短く残す。制作中の問題・原因・対処・改善候補は `LEARNINGS.md` へ追記する。被写体の実名はタイトル、説明、提出ファイル名へ使わない。

旧形式の移行は選択中プロジェクトだけを対象にし、既定を dry-run とする。ユーザーが変更予定を確認して `--apply` を明示した場合だけ、バックアップを作り、各ファイルを同一 filesystem 上で原子的に置換する。捕捉できる途中失敗は巻き戻す。v4 への移行では新しい証跡・アカウント項目を未確認値で追加し、旧P9をP8へ、旧 `requested|approved|rejected|released` を `production-complete` へ意味を保って移す。廃止済みの `adult`、`consent`、`rights` と、空の既定値だった `license_proof` は削除し、ユーザーが提示済みの任意資料は維持する。欠落した `materials` は P0 なら `pending`、P1 以降なら `refs/` の読取可能な非空素材を確認できた場合だけ `received` にする。未知値・矛盾、不正・重複キー JSON、未来バージョンがあれば、全ファイルを未変更のまま停止する。
