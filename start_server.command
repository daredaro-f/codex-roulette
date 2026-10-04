#!/bin/bash
# Finderから開いても、必ずこのファイルのあるフォルダで起動する。
finish() {
    local server_exit_code="$1"
    if [ -t 0 ]; then
        printf '\nEnterキーでこの起動スクリプトを終了するよ。'
        read -r
    fi
    exit "$server_exit_code"
}

cd -- "$(dirname -- "$0")" || finish 1

if [ ! -x ".venv/bin/python" ]; then
    printf '%s\n' \
        'アプリ用のPython環境が見つからないよ。' \
        'README.mdの「初回セットアップ → Mac」で初回の準備をしてね。' \
        '準備が終わったら、このファイルをもう一度ダブルクリックしよう。'
    finish 1
fi

printf '%s\n' 'サーバーを起動するよ。止めるときは、この画面で Control + C。'
".venv/bin/python" run.py "$@"
server_exit_code=$?
if [ "$server_exit_code" -ne 0 ] && [ "$server_exit_code" -ne 130 ]; then
    printf '%s\n' '起動できなかったよ。上のエラーとREADME.mdの「つまずいたとき」を確認してね。'
fi
finish "$server_exit_code"
