# workflow の学び

## 2026-09-03 Windows runtime discovery

- 事象: Windows 環境で `python` と `bash` を PATH 経由で実行できず、初回の検証コマンドが失敗した
- 原因: Python は未導入で、Git Bash はインストール済みだが PATH に登録されていなかった
- 対処: Git Bash を `C:\Program Files\Git\bin\bash.exe` の絶対パスで呼び、参照整合性と Shell 構文を検証した。Python のセルフテストは未実行として明記した
- 再発防止: Windows では検証前に `Get-Command` でランタイムを確認する。Git Bash は既知の絶対パスへフォールバックし、Python がなければ勝手にインストールせず確認を取る

## 2026-09-01 brace expansion

- 事象: `mkdir -p .claude/{hooks,rules,...}` が `/bin/sh` で展開されず、`{hooks,rules,...}` という名前のディレクトリが作られた。続く `cd` が失敗し、rules ファイルがカレントディレクトリ（/）に書かれた
- 原因: 実行シェルが bash ではなく sh だった
- 対処: ディレクトリを個別に列挙して作成し、誤配置ファイルを移動
- 再発防止: 複数ディレクトリ作成はブレースを使わず明示列挙する。ファイル生成前に `pwd` と `ls` で場所を確認する
