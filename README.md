# チケット空き通知システム

ぴあ (pia.jp) の特定チケットページを30分ごとに監視し、空きが出た際にGmailで通知します。

## 仕組み

- **GitHub Actions** が30分ごとに自動実行
- **Playwright (Chromium)** でJSレンダリング後のページを取得
- 在庫ありキーワード (`受付中`, `購入する` など) を検出したら即座にメール送信
- `state.json` で前回の状態を管理し、「売り切れ→空きあり」の変化時のみ通知

## セットアップ

### 1. リポジトリを GitHub にプッシュ

```bash
cd チケット空き通知
git init
git add .
git commit -m "initial commit"
git remote add origin https://github.com/<your-username>/<repo-name>.git
git push -u origin main
```

### 2. Gmail アプリパスワードを発行

1. [Google アカウント](https://myaccount.google.com/) → **セキュリティ**
2. 2段階認証を有効化（未設定の場合）
3. **アプリパスワード** → アプリを選択: 「メール」、デバイス: 「その他」→ 生成
4. 表示された16桁のパスワードをコピー

### 3. GitHub Secrets を設定

**GitHub リポジトリ** → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| シークレット名 | 設定値 |
|---|---|
| `TICKET_URL` | 監視するぴあのチケットURL |
| `GMAIL_USER` | 送信元Gmailアドレス (例: `you@gmail.com`) |
| `GMAIL_APP_PASSWORD` | 手順2で発行したアプリパスワード |
| `NOTIFY_TO` | 通知先メールアドレス |

### 4. 動作確認

**Actions タブ** → **チケット空き確認** → **Run workflow**

- `force_notify: false` → 通常実行（状態変化時のみ通知）
- `force_notify: true` → 強制メール送信テスト

## 実行スケジュール

日本時間 9:00〜23:00 の間、30分ごとに実行されます（深夜帯はスキップ）。

GitHub Actions 無料枠:
- **パブリックリポジトリ**: 無料（制限なし）
- **プライベートリポジトリ**: 月2,000分まで無料

## ファイル構成

```
.
├── .github/
│   └── workflows/
│       └── check_ticket.yml  # GitHub Actions 定義
├── checker.py                # メインスクリプト
├── requirements.txt          # Python 依存パッケージ
├── state.json                # 前回チェック時の状態（自動更新）
└── .env.example              # 環境変数テンプレート
```

## ローカルテスト

```bash
pip install -r requirements.txt
playwright install chromium

# .env.example をコピーして実際の値を設定
cp .env.example .env
# .env を編集してシークレットを設定

# 環境変数を読み込んで実行
export $(cat .env | grep -v '^#' | xargs)
python checker.py

# 強制通知テスト
python checker.py --force-notify
```

## 注意事項

- ぴあの利用規約の範囲内で個人利用としてご使用ください
- bot検知強化により動作しなくなる場合があります
- アプリパスワードは `.env` ファイルに保存し、絶対にリポジトリにコミットしないでください
