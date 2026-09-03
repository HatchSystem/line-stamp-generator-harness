# publish の学び

## 2026-09-03 registration declarations

- 事象: 申請メタが販売地域を2択として扱い、AI・写真使用やプレミアム参加を文字列または推測値で持つと、現行画面の選択内容を正確に再現できない
- 原因: 公開画面の法的同意、申告、参加設定と、作品メタを一つの曖昧な公開可否へまとめていた
- 対処: 販売エリアを `all|some|selected` と国コード一覧へ分離し、`ai_used`、`photo_used`、`premium_participation` を真偽値、ライセンス確認を `license_proof` として明示した。「同意します」と審査リクエストはユーザー本人だけが行う
- 再発防止: P6/P8で公式画面・ガイドラインを再確認し、画面値を推測しない。`check-publish-ready` は `publish: yes` のP7候補だけに使い、法的有効性を保証する表現を避ける。仕様差分はこのファイルと `references/line-specs.md` の両方へ記録する
