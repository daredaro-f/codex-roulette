@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0"
if errorlevel 1 goto directory_error

if not exist ".venv\Scripts\python.exe" goto missing_environment

echo サーバーを起動するよ。止めるときは、この画面で Ctrl + C。
".venv\Scripts\python.exe" run.py %*
set "server_exit_code=%errorlevel%"
echo.
if not "%server_exit_code%"=="0" echo 起動できなかったよ。上のエラーとREADME.mdの「つまずいたとき」を確認してね。
pause
popd
exit /b %server_exit_code%

:missing_environment
echo アプリ用のPython環境が見つからないよ。
echo README.mdの「初回セットアップ → Windows」で初回の準備をしてね。
echo 準備が終わったら、このファイルをもう一度ダブルクリックしよう。
pause
popd
exit /b 1

:directory_error
echo プロジェクトのフォルダを開けなかったよ。このファイルの保存場所を確認してね。
pause
exit /b 1
