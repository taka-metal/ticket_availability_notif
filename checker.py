#!/usr/bin/env python3
"""
ぴあ チケット空き通知スクリプト
Playwrightでチケットページを監視し、空きが出た際にGmailで通知する。
"""

import json
import os
import smtplib
import ssl
import sys
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# 定数
STATE_FILE = Path(__file__).parent / "state.json"
JST = timezone(timedelta(hours=9))

AVAILABLE_KEYWORDS = ["受付中", "購入する", "申し込む", "残りわずか"]
SOLDOUT_KEYWORDS = ["販売終了", "完売", "受付終了", "SOLDOUT", "sold out", "SOLD OUT"]


def load_state() -> dict:
    """state.jsonを読み込む。存在しない場合はデフォルト値を返す。"""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[WARN] state.json 読み込みエラー: {e}")
    return {
        "url": "",
        "last_checked": None,
        "available": None,
        "last_status_text": "",
    }


def save_state(state: dict) -> None:
    """state.jsonを保存する。"""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print(f"[INFO] state.json を更新しました: available={state['available']}")


def check_availability(url: str) -> tuple[bool | None, str, str]:
    """
    Playwrightでチケットページを開き、在庫状況を判定する。

    Returns:
        (available, status_text, page_title)
        available: True=在庫あり, False=売り切れ, None=判定不能
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="ja-JP",
        )
        page = context.new_page()

        try:
            print(f"[INFO] ページを開いています: {url}")
            page.goto(url, timeout=60000)
            page.wait_for_load_state("networkidle", timeout=30000)

            page_title = page.title()
            body_text = page.inner_text("body")
            print(f"[INFO] ページタイトル: {page_title}")
            print(f"[INFO] ページテキスト（先頭500文字）: {body_text[:500]}")

            # 売り切れ判定（優先）
            for keyword in SOLDOUT_KEYWORDS:
                if keyword in body_text:
                    print(f"[INFO] 売り切れキーワード検出: '{keyword}'")
                    return False, keyword, page_title

            # 在庫あり判定
            for keyword in AVAILABLE_KEYWORDS:
                if keyword in body_text:
                    print(f"[INFO] 在庫ありキーワード検出: '{keyword}'")
                    return True, keyword, page_title

            print("[WARN] 判定キーワードが見つかりませんでした")
            return None, "判定不能", page_title

        except PlaywrightTimeoutError as e:
            print(f"[ERROR] タイムアウト: {e}")
            raise
        finally:
            browser.close()


def send_email(
    gmail_user: str,
    gmail_app_password: str,
    notify_to: str,
    page_title: str,
    url: str,
    status_text: str,
) -> None:
    """Gmailで通知メールを送信する。"""
    subject = f"【チケット空き通知】{page_title} の空きが出ました！"
    now_jst = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")

    body = f"""\
チケットの空きが検出されました。

ページ名: {page_title}
URL: {url}
検出キーワード: {status_text}
確認時刻: {now_jst}

今すぐ確認してください:
{url}

---
このメールはチケット空き通知システムにより自動送信されました。
"""

    msg = MIMEMultipart()
    msg["From"] = gmail_user
    msg["To"] = notify_to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(gmail_user, gmail_app_password)
        server.sendmail(gmail_user, notify_to, msg.as_string())

    print(f"[INFO] メール送信完了: {notify_to}")


def main(force_notify: bool = False) -> None:
    """メイン処理。"""
    # 環境変数の読み込み
    ticket_url = os.environ.get("TICKET_URL", "").strip()
    gmail_user = os.environ.get("GMAIL_USER", "").strip()
    gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    notify_to = os.environ.get("NOTIFY_TO", "").strip()

    if not ticket_url:
        print("[ERROR] TICKET_URL が設定されていません")
        sys.exit(1)
    if not gmail_user or not gmail_app_password or not notify_to:
        print("[ERROR] Gmail設定 (GMAIL_USER, GMAIL_APP_PASSWORD, NOTIFY_TO) が不完全です")
        sys.exit(1)

    print(f"[INFO] 監視URL: {ticket_url}")
    print(f"[INFO] 開始時刻: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S JST')}")

    # 前回の状態を読み込む
    state = load_state()
    prev_available = state.get("available")

    # チケットページを確認
    try:
        available, status_text, page_title = check_availability(ticket_url)
    except Exception as e:
        print(f"[ERROR] チケット確認に失敗しました: {e}")
        print("[INFO] 誤通知防止のため、メール送信をスキップします")
        sys.exit(0)

    # 状態を更新
    now_iso = datetime.now(JST).isoformat()
    state.update(
        {
            "url": ticket_url,
            "last_checked": now_iso,
            "available": available,
            "last_status_text": status_text,
        }
    )
    save_state(state)

    # 通知判定: 「なし→あり」に変わった場合、または --force-notify フラグ
    should_notify = force_notify or (available is True and prev_available is not True)

    if should_notify:
        if force_notify:
            print("[INFO] --force-notify フラグにより強制通知します")
        else:
            print(f"[INFO] 状態変化を検出: {prev_available} → {available}")

        try:
            send_email(
                gmail_user=gmail_user,
                gmail_app_password=gmail_app_password,
                notify_to=notify_to,
                page_title=page_title,
                url=ticket_url,
                status_text=status_text,
            )
        except Exception as e:
            print(f"[ERROR] メール送信に失敗しました: {e}")
            sys.exit(1)
    else:
        print(
            f"[INFO] 通知不要: available={available}, prev_available={prev_available}"
        )

    print("[INFO] チェック完了")


if __name__ == "__main__":
    force_notify = "--force-notify" in sys.argv
    main(force_notify=force_notify)
