# arXivApp

A Slack App using Bolt for Python that shows arXiv abstract and DeepL translations.

[Slack](https://slack.com/) で [arXiv](https://arxiv.org/) の URL を書くとタイトルやアブストラクト等を通知するボット.

[DeepL API](https://www.deepl.com/docs-api/introduction/) での翻訳にも対応しています.

![image](https://user-images.githubusercontent.com/1632335/88476721-ae437080-cf75-11ea-8518-f60d164cc034.png)

ここでは, まずローカル環境でテストして, その後, 本番環境として [Heroku](https://www.heroku.com/) で arXivApp をホスティングする方法を説明します.


## Slack App の設定(前半)

以下のページを参考に Slack App を作成して Bot User OAuth Access Token を生成するところまで設定します.

https://qiita.com/seratch/items/a001985ee1dccaf95727#slack-%E3%82%A2%E3%83%97%E3%83%AA%E3%82%92%E4%BD%9C%E6%88%90

まず, 以下のページから Slack App を作成します.

https://api.slack.com/apps?new_app=1

以下のように入力して `Create App` します.

```
App Name: arXivApp
Development Slack Workspace: (ワークスペース)
```

左のメニューから,

Features > OAuth & Permissions

Scopes > Bot Token Scopes > Add an OAuth Scope

で以下を追加します.

```
channels:history
groups:history
chat:write
```

左のメニューから,

Features > App Home

App Display Name > Edit

```
Display Name (Bot Name): arXivApp
Default username: arxivapp
```

して `Save` を押します. その下の以下項目を ON にしておきます.

```
Always Show My Bot as Online: ON
Show Tabs > Home Tab: ON
```

左のメニューから

Settings > Install App > Install App to Workspace

`Allow` を押します.

Bot User OAuth Access Token (`xoxb-nnn...`) をメモしておきます.


同様に 左のメニューから

Settings > Basic Information > App Credentials > Signing Secret > Show

Signing Secret もメモしておきます.


Slackの設定は一旦ここまでやっておいて, 後で残りの設定をします.


## Slack App の招待

作った Slack App をテスト用の Slack チャンネルに招待しておきます.

例: ボットの名前を arXivApp にした場合, 招待したいチャンネルで,

```
/invite @arXivApp
```


## ローカルの環境の設定

上記でメモした Slack App の API Token を環境変数 `SLACK_BOT_TOKEN` に, Signing Secret を `SLACK_SIGNING_SECRET` に設定しておきます.

ローカルでテストする場合は, 環境変数を ~/.zshrc に書いておいて `source ~/.zshrc` しておきます.

```sh
export SLACK_BOT_TOKEN="xoxb-nnn..."
```

```sh
export SLACK_SIGNING_SECRET="xxx..."
```

DeepL API を使う場合は, 同様に `DEEPL_AUTH_KEY` も設定しておきます.


ローカル環境の設定と動作確認を以下のようにします. ngrok が必要です.

```sh
# ngrok をインストールしていない場合は以下でインストール(Macの場合)
# brew cask install ngrok
git clone git@github.com:susumuota/arXivApp.git
cd arXivApp
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python run.py
# 別ターミナルで
ngrok http 3000
```

ngrok のアドレスをメモしておきます.

## Slack App の設定(後半)

Slack App の画面に戻って, 左のメニューから,

Features > Event Subscriptions

Enable Events > Request URL

先程メモしておいた ngrok のアドレスの末尾に `/slack/events` を追加して入力します.

```
https://xxx.ngrok.io/slack/events
```

Verified と表示されれば OK です.

すぐ下の,

Subscribe to bot events > Add Bot User Event

```
message.channels
message.groups
```

を追加して下の `Save Changes` を押します( **忘れがち** ).

Slack の arXivApp を招待したチャンネルで `https://arxiv.org/abs/2005.05960` と発言してみてボットの返答がスレッドでつけばローカル環境でのテストは完了です.

テストが終わったらngrok と run.py を Ctrl-C で終了しておきます.


## Heroku での設定

ローカル環境でのテストが十分できたら Heroku にデプロイする設定をします.


### Heroku アカウントの作成と CLI のインストール

以下のチュートリアルを参考に, Heroku アカウントの作成から CLI のインストールまで済ませておきます(Postgres をインストールする必要はありません).

https://devcenter.heroku.com/articles/getting-started-with-python


### Heroku アプリ作成

Heroku のアプリ作成を以下のようにします.

```sh
heroku login
heroku create (任意のアプリ名)
git remote -v  # heroku が追加されているか確認
```

以下のページから, 作成したアプリ名をクリック,

https://dashboard.heroku.com/apps

Settings > Buildpacks > Add buildpack

以下を追加して `Save changes`.

```
heroku/python
```


### Heroku 環境変数設定

以前メモした Slack App の 設定を環境変数 `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET` で設定しておきます. DeepL API を使う場合は, 同様に `DEEPL_AUTH_KEY` も設定しておきます.

以下ページを参考に, Heroku 側での環境変数を設定します.

https://devcenter.heroku.com/articles/config-vars

CLI のコマンドか Web で設定できますが, CLI だとシェルのヒストリに残ってしまうので Web で設定した方が良いかもしれません.

https://devcenter.heroku.com/articles/config-vars#using-the-heroku-dashboard


### Heroku へのデプロイ

Heroku へのデプロイは以下のようにします.

```sh
git push heroku master  # Heroku にコードをアップロード
```


### Heroku ログ確認

別ターミナルを開いて, ログを確認しておきます.

```
heroku logs --tail
```


### Heroku アプリ起動

ブラウザから以下のページにアクセスして `Hello!` と表示されれば Flask まで起動しています. ログでも確認しておきます.

https://(任意のアプリ名).herokuapp.com/


## Slack App の設定(本番用)

Slack App の画面に戻って, 左のメニューから,

Features > Event Subscriptions

Enable Events > Request URL > Change

Heroku のアドレスの末尾に `/slack/events` を追加して入力します.

```
https://(任意のアプリ名).herokuapp.com/slack/events
```

Verified と表示されれば OK です. 下の `Save Changes` を押します( **忘れがち** ).

Slack の arXivApp を招待したチャンネルで `https://arxiv.org/abs/2005.05960` と発言してみてボットの返答がスレッドでつけば本番環境でのテストは完了です.


## 開発サイクル

以下のようなサイクルで開発しています.

```sh
# ローカルでテスト
# コードを変更
python run.py
ngrok http 3000
# Slack App の設定で Features > Event Subscriptions, Enable Events > Request URL を ngrok の URL に変更
# Slack で動作確認
# ローカルでテストが済んだら以下のように Heroku にデプロイ
git add
git commit
git push heroku master # Heroku にアップロードされてコードが更新
# Slack App の設定で Features > Event Subscriptions, Enable Events > Request URL を Heroku の URL に変更
# Slack で動作確認
```


## TODO

- app.json
- Bolt for Python


## 参考

- https://api.slack.com/bot-users
- https://github.com/slackapi/python-slack-events-api
- https://www.deepl.com/docs-api/introduction/
- https://devcenter.heroku.com/articles/getting-started-with-python
- https://qiita.com/seratch/items/a001985ee1dccaf95727
- https://qiita.com/akabei/items/ec5179794f9e4e1df203
- https://qiita.com/nsuhara/items/76ae132734b7e2b352dd
- https://github.com/dev-hato/hato-bot/issues/146


## 作者

Susumu OTA

