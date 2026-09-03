# 承認ゲートと状態

## ゲート

| Gate | 成果物 | 次へ進む条件 |
|---|---|---|
| P0 | 受付情報 | 入力種別・素材・権利・枚数・文字・キャラ名・公開予定/許諾が確定 |
| P1 | 特徴ロック（写真）／デザインシート（既存キャラ） | ユーザーが特徴を承認 |
| P2 | 正面・斜め・決めポーズの三面図 | ユーザーが同一キャラとして承認 |
| P3 | 全点のセリフ・表情・ポーズ表 | ユーザーが計画を承認 |
| P4 | stamp01の候補（1〜3枚）と採用案。`ai` は 01 の文字検査結果も | ユーザーがキャラ、誤字、切り抜き、文字装飾を承認 |
| P5 | 残りと版付き確認一覧。`ai` は全点の文字検査結果（`text-check-vNN.md`）も | ユーザーが一覧を承認し、`ai` は全点の文字を目視承認（`text_check: ok`） |
| P6 | main、tab、全スタンプ、検証ログ、ZIP | 検証エラー0 |
| P7 | タイトル・説明・クリエイター名・コピーライト・価格・販売地域案 | ユーザーがメタを承認 |
| P8 | Creators Market への登録内容（審査リクエスト直前） | ユーザー本人が「審査をリクエスト」を押す |
| P9 | 審査結果の追跡とリリース案内 | 承認→ユーザーがリリース／却下→該当ゲートへ戻る |

「OK」「続けて」「いいね」は現在のゲートの承認として扱う。修正依頼では該当ゲートに留まり、修正版の成果物名に版番号を付ける。1ターンで複数ゲートを飛ばさない。質問の出し方は [dialogue.md](dialogue.md) に従う。

## P0で確定する項目

既に分かっている項目は聞き直さない。

- 入力種別: `photo`（人物写真をキャラクター化）／`character`（既存キャラクターのデザインを踏襲）
- 素材。複数なら正本にする1枚。既存キャラなら設定画・正面画を優先
- 権利: 写真は本人または許諾済み、既存キャラはユーザー自身が権利を持つもの（二次創作・他社IPは受けない）
- 枚数: 8/16/24/32/40 のいずれか（LINE規定。他の数は受け付けない）
- 文字あり/なし
- 文字ありなら入れ方: `font`（埋め込みフォント。誤字ゼロ、既定）／`ai`（生成AIに描かせる。誤字が出るため検査工程が入る）
- キャラ名（申請時のタイトル・説明に使う表示名。実名は使わない）
- 01の候補生成数: 1〜3（既定1）
- 公開申請の予定。予定ありなら本人許諾（`consent: yes`）と被写体が成年であること

## SESSION

`projects/<slug>/SESSION.md` がプロジェクトの唯一の状態。他プロジェクトとは共有しない。

```text
project / source / count / text / text_mode / text_check / gate / character
rights / adult / consent / publish
lock / three_view / sample_candidates / sample / review_version
validation / submission
```

- `text_mode`: `font` `ai` `none`（`text: no` のとき）
- `text_check`: `not-run` `ok` `failed` `n/a`（`ai` 以外は `n/a`。OCR だけで `ok` にせずユーザーの目視承認で更新）
- `rights`: `own` `licensed` `unknown`
- `adult`: `yes` `no` `unknown`
- `consent`: `yes` `no` `unknown`
- `publish`: `yes` `no` `private`（私的お試しのみ）
- `validation`: `not-run` `ok` `failed`
- `submission`: `not-started` `drafted` `requested` `approved` `rejected` `released`

ユーザーの承認、差し戻し理由、文字スタイル、検証結果、審査結果を `notes` に短く残す。被写体の実名はタイトル、説明、提出ファイル名へ使わない。
