# Codex実験ルーレット

「機能」「お題」「変な制約」をネオンの3連ルーレットで引き、Codexへ渡す依頼文を作るローカルアプリ。

LM StudioのローカルLLMでお題を生成できる。モデルがなくても、手作りのお題を使うデモで遊べる。機能カードに触れると、機能の説明・必要な準備・公式情報を読める。2026-10-03「Codex Catchup #1 OpenAI DevDay 2026」のハンズオンから生まれた。

## 初回セットアップ

Python **3.10以上**が必要。3.12を目安に用意しよう。Node.jsは不要。ダウンロードしたフォルダでターミナル／PowerShellを開いて実行する。

### Mac

```sh
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
```

`python3 --version` が3.9以下なら、Python 3.10以上を用意してから進める。3.12を `python3.12` で呼ぶ環境では、仮想環境の作成に `python3.12 -m venv .venv` を使う。

### Windows（PowerShell）

```powershell
py -3 --version
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
```

`py -3 --version` で3.10以上になっていることを確認する。仮想環境のPythonを直接使うので、PowerShellのスクリプト実行設定を変更する必要はない。

## 起動する

準備できたら、Macは **`start_server.command`**、Windowsは **`start_server.bat`** をダブルクリックする。

ブラウザで [http://127.0.0.1:8000](http://127.0.0.1:8000) を開こう。起動したターミナルは開いたままにしておく。止めるときはその画面で **Control + C / Ctrl + C**。Macで実行権限が外れていたら、フォルダ内で `chmod +x start_server.command` を実行する。

モデルなしで試す場合は、デモ専用モードを使える。このモードはLM Studioへ通信しない。

Mac：

```sh
./start_server.command --demo --port 8011
```

Windows：

```powershell
.\start_server.bat --demo --port 8011
```

[http://127.0.0.1:8011](http://127.0.0.1:8011) を開く。8000番が使われている場合も、`--port` で空いているポートを指定できる。

## LM Studioを接続する

1. LM Studioに会話用モデルを用意し、Developer画面でサーバーを起動する。先にモデルをロードしておくと始めやすい。
2. デモ専用モードを止め、引数なしの起動ファイルで通常モードを起動する。
3. アプリの接続設定を開く。初期の接続先は `http://127.0.0.1:1234/v1`。ポートを変えている場合はLM Studioの設定に合わせる。
4. 接続確認を押してモデルを選び、ローカルLLMのモードで抽選する。

接続先・モデル・生成元のモードはブラウザに保存され、ページの更新後も復元する。同じブラウザとURLで使おう。`localhost` と `127.0.0.1`、ポートが違うURLでは保存先も別になる。LM Studioが止まっていても保存した設定は消さない。

これは**ルーレットのお題を考えるモデル**の設定。引いたお題を実装するときに使うCodexのモデル設定とは別。

### 認証を使う場合

LM Studioで認証を有効にした場合だけ、設定見本をコピーして `.env` を作る。

Mac：`cp .env.example .env`  
Windows：`Copy-Item .env.example .env`

すでに `.env` があればコピーし直さずに編集する。

```dotenv
LM_STUDIO_BASE_URL=http://127.0.0.1:1234/v1
LM_STUDIO_API_TOKEN=
ROULETTE_GENERATION_TIMEOUT=30
ROULETTE_DEMO_ONLY=false
```

`LM_STUDIO_API_TOKEN=` の右側にトークンを入れ、アプリを再起動する。トークンはPython側だけで扱い、ブラウザへ返さない。`.env` はGitへ含めない。

待ち時間は初期値30秒。遅いモデルでは `ROULETTE_GENERATION_TIMEOUT` を0より大きく120以下に調整できる。不正なJSONや選んでいない機能は採用せず、画面で再試行を案内する。「待機をやめる」はアプリが結果を待つのをやめる操作で、モデル側の推論が直ちに止まるとは限らない。

## 遊び方

1. 自分が使える機能を選ぶ。説明カードで利用条件や準備を確認する。
2. デモまたはローカルLLMで「機能」「お題」「変な制約」を引く。
3. 説明はマウスオーバー、キーボードフォーカス、クリック、タップで開ける。
4. 依頼文をコピーし、Codexや対象機能を使えるChatGPTへ貼り付ける。

音は初期OFF。「音」をONにすると確認音が鳴り、抽選開始・確定にも短い音が鳴る。動きを抑える設定も使える。

機能の名前・説明・公式リンクはカタログから表示する。LLMが考えるのは候補の選択、お題、制約、使い方の案。機能の提供状況や必要なプランは公式情報を確認しよう。カタログの確認日は **2026-10-03**。実験の時間は準備済みの場合の目安。

対応する内蔵ブラウザでは、抽選後の「このカードをCodexと調整」からBrowser Annotation APIも試せる。色のプレビューを確認してから、自分で注釈を送信する。通常のブラウザでもルーレット・説明・コピーは使える。[注釈APIの公式ガイド](https://learn.chatgpt.com/docs/annotations-extensibility)

## つまずいたとき

| 症状 | 確認すること |
| --- | --- |
| 起動時にエラー | Pythonが3.10以上か、初回セットアップを済ませたか確認する |
| ポートを使えない | 起動ファイルへ `--port 8001` などを付ける |
| LM Studioにつながらない | Developerのサーバーが起動中か、接続先とポートが合っているか確認する |
| モデルが見つからない | 会話用モデルを用意し、LM Studioでロードする |
| 認証エラー | `.env` のトークンを確認してアプリを再起動する |
| 生成が失敗／時間切れ | 別のモデル、待ち時間の調整、デモを試す |
| 音が出ない | 画面の「音」を一度OFF→ONにして案内を確認する |
| 注釈操作が見えない | 対応するアプリの内蔵ブラウザで開く |

## 開発とテスト

FastAPIと素のHTML・CSS・JavaScriptで構成する。DBや外部のWebフォント・画像・JavaScriptライブラリは使わない。

Mac（仮想環境を有効にした状態）：

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Windows：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

APIテストは `httpx.MockTransport` の偽の応答を使い、本物のLM Studioや外部APIへ通信しない。画面の確認には `--demo --port 8011` を使える。Mac・Python 3.12で動作確認済み。Windows実機での動作は未確認。

| ファイル | 役割 |
| --- | --- |
| `run.py` | 通常／デモの起動、ポート指定 |
| `start_server.command` / `start_server.bat` | Mac／Windowsのダブルクリック起動 |
| `roulette/app.py` | ローカルAPI、LM Studio接続、生成結果の検証 |
| `static/` | ルーレットの画面と操作 |
| `data/features.json` | 機能カタログと公式リンク |
| `data/demo_samples.json` | デモのお題 |
| `tests/` | 隔離したAPIテスト |

## 公式情報

- [DevDay 2026公式発表](https://learn.chatgpt.com/docs/whats-new/devday-2026)
- [LM Studioの互換API](https://lmstudio.ai/docs/developer/openai-compat)
- [LM StudioのJSON Schema出力](https://lmstudio.ai/docs/developer/openai-compat/structured-output)
- [LM StudioのネイティブChat API](https://lmstudio.ai/docs/developer/rest/chat)
- [LM Studioの認証と起動](https://lmstudio.ai/docs/developer/rest/quickstart)

配色、演出、お題、時間の目安はこのプロジェクトの創作・設計だよ。
