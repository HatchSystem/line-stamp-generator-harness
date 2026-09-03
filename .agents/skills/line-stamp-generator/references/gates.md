# 承認ゲートと状態

## ゲート

| Gate | 成果物 | 次へ進む条件 |
|---|---|---|
| P0 | 受付情報 | 入力種別・素材・素材利用権・写真の本人許諾/成年・枚数・文字・キャラ名・申請意図が確定し、`confirm-p0` が P1 へ更新 |
| P1 | 特徴ロック（写真）／デザインシート（既存キャラ） | ユーザーが特徴を承認 |
| P2 | 正面・斜め・決めポーズの三面図 | ユーザーが同一キャラとして承認 |
| P3 | 全点のセリフ・表情・ポーズ表 | ユーザーが計画を承認 |
| P4 | stamp01の候補（1〜3枚）と採用案。`ai` は 01 の文字検査結果も | ユーザーがキャラ、誤字、切り抜き、文字装飾を承認 |
| P5 | 残りと版付き確認一覧。`ai` は全点の文字検査結果（`text-check-vNN.md`）も | ユーザーが一覧を承認し、`ai` は全点の文字を目視承認（`text_check: ok`） |
| P6 | main、tab、全スタンプ、検証ログ、ZIP | `self-test` PASS、`validate-pack` errors=0 |
| P7 | タイトル・説明・クリエイター名・コピーライト・価格・販売エリア・申告/参加設定案 | `check-publish-ready` errors=0、ユーザーがメタを承認 |
| P8 | Creators Market への登録内容（審査リクエスト直前） | ユーザー本人が同意事項を確認・同意し「審査をリクエスト」を押す |
| P9 | 審査結果の追跡とリリース案内 | 承認→ユーザーがリリース／却下→該当ゲートへ戻る |

「OK」「続けて」「いいね」「それで」は現在のゲートの承認として扱う。修正依頼では該当ゲートに留まり、修正版の成果物名に版番号を付ける。1ターンで複数ゲートを飛ばさない。承認は必ずメインエージェントがユーザーから受け取り、サブエージェントはゲートを進めない。質問の出し方は [dialogue.md](dialogue.md) に従う。

P6 は公開 CLI の `self-test` が PASS し、`validate-pack` が errors=0 になったときだけ完了する。結果を報告してそのターンを終了する。`publish: local-only` なら `submission: local-complete` として終了し、ローカル確認用成果物は LINE 上で配布・利用できないことを伝える。公開する場合、P7 は次のターンで始める。P7 は `check-publish-ready` が errors=0 で、ユーザーがメタを承認したときに `submission: drafted` として完了する。P8 に入るには `publish: yes`、`rights: own|licensed`、`validation: ok`、`submission: drafted` が必要で、写真では `consent: yes` と `adult: yes`、既存キャラクターでは両項目が `n/a` でなければならない。`text_mode: ai` では `text_check: ok` も必要である。P8 は登録入力とサマリ提示で停止し、ユーザー本人が同意事項を確認して「同意します」を選び、審査リクエストを押したと報告してから `submission: requested` に更新する。

## P0で確定する項目

既に分かっている項目は聞き直さない。

- 入力種別: `photo`（人物写真をキャラクター化）／`character`（既存キャラクターのデザインを踏襲）
- 素材。新規選択後に P0 プロジェクトを作り、正本にする1枚をその `refs/` に置いて `materials: received` とする。既存キャラなら設定画・正面画を優先
- `rights`: 写真・イラスト素材と既存キャラクターについて、ユーザーが著作権と商用利用権を保有する `own`、または明示的な商用ライセンスを持つ `licensed`。`unknown` なら制作を止める
- `consent`: 写真に写る本人の制作許諾。写真は申請意図にかかわらず `yes` が必須。既存キャラクターは `n/a`
- `adult`: 写真の被写体本人による成年の申告。外見から推測しない。`no|unknown` なら `publish: local-only` のみ。既存キャラクターは `n/a`
- 枚数: 8/16/24/32/40 のいずれか（LINE規定。他の数は受け付けない）
- 文字あり/なし
- 文字ありなら入れ方: `font`（埋め込みフォント。生成モデルによる文字崩れを避ける既定方式）／`ai`（生成AIに描かせる。誤字が出るため検査工程が入る）。`font` でも原文、欠字、可読性は P4/P5 で目視する
- キャラ名（申請時のタイトル・説明に使う表示名。実名は使わない）
- 01の候補生成数: 1〜3（既定1）
- `publish`: LINE へ審査申請する意図。`yes` または `local-only`（ローカル確認用成果物。LINE 上で配布・利用不可）

新規作成は P0 より前に `project ... new --slug <slug>` で隔離先だけを作る。全項目をユーザーへ復唱して承認を得た後、公開 CLI の `project ... confirm-p0` を使う。このコマンドだけが P0 の全項目を検証・保存して `gate: P1` へ進める。権利不明、写真の許諾なし、値の矛盾があれば無変更で停止する。

## SESSION

`projects/<slug>/SESSION.md` がプロジェクトの唯一の状態。他プロジェクトとは共有しない。

```text
schema_version / project / materials / source / count / text / text_mode / text_check / gate / character
rights / adult / consent / publish
lock / three_view / sample_candidates / sample / review_version
validation / submission / notes
```

- `schema_version`: 現行は `2`。欠落は旧 v1 とみなし、制作再開前に公開 CLI の `project --root . migrate` で診断する
- `text_mode`: `font` `ai` `none`（`text: no` のとき）
- `text_check`: `not-run` `ok` `failed` `n/a`（`ai` 以外は `n/a`。OCR だけで `ok` にせずユーザーの目視承認で更新）
- `materials`: `pending` `received`
- `rights`: 素材とキャラクターの著作権・商用利用権を表す `own` `licensed` `unknown`。`unknown` のまま制作しない
- `adult`: `yes` `no` `unknown` `n/a`（既存キャラクターは `n/a`）
- `consent`: `yes` `no` `unknown` `n/a`（写真は `yes` が制作条件、既存キャラクターは `n/a`）
- `publish`: LINE への審査申請意図を表す `yes` `local-only` `unknown`（`local-only` はローカル確認用で、LINE 上では配布・利用できない）
- `validation`: `not-run` `ok` `failed`
- `submission`: `not-started` `local-complete` `drafted` `requested` `approved` `rejected` `released`

ユーザーの承認、差し戻し理由、文字スタイル、検証結果、審査結果を `notes` に短く残す。被写体の実名はタイトル、説明、提出ファイル名へ使わない。

旧 v1 の移行は選択中プロジェクトだけを対象にし、既定を dry-run とする。ユーザーが変更予定を確認して `--apply` を明示した場合だけ、バックアップを作り、各ファイルを同一 filesystem 上で原子的に置換する。捕捉できる途中失敗は巻き戻す。欠落した `materials` は P0 なら `pending`、P1 以降なら `refs/` の読取可能な非空素材を確認できた場合だけ `received` にする。移行は権利・許諾を推測せず、`gate`、`validation`、`submission`、承認記録を進めない。移行対象フィールドの未知値・矛盾、または非標準数値・不正・重複キー JSON があれば、全ファイルを未変更のまま停止する。`publish: yes` で P7 へ進む場合の完全な公開準備検査は別途 `check-publish-ready` で行う。
