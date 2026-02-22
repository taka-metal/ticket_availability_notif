#!/usr/bin/env python3
"""
TBSチケット MUNDO PIXAR TOKYO 空き通知スクリプト
カレンダーAPIを直接チェックし、空き日程が出た際にGmailで通知する。
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

import requests

# 定数
STATE_FILE = Path(__file__).parent / "state.json"
JST = timezone(timedelta(hours=9))

CALENDAR_API_URL = "https://tickets.tbs.co.jp/tbs/json/pixarCalender.json"
TICKET_PAGE_URL = "https://tickets.tbs.co.jp/mundopixar/rsv/"

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    "Referer": TICKET_PAGE_URL,
}


def load_state() -> dict:
    """state.jsonを読み込む。存在しない場合はデフォルト値を返す。"""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[WARN] state.json 読み込みエラー: {e}")
    return {
        "last_checked": None,
        "last_available_dates": [],
    }


def save_state(state: dict) -> None:
    """state.jsonを保存する。"""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print(f"[INFO] state.json を更新しました")


def get_current_jst_str() -> str:
    """現在の日本時間をYYYYMMDDHHmmss形式で返す。"""
    return datetime.now(JST).strftime("%Y%m%d%H%M%S")


def fetch_available_dates() -> list[dict]:
    """
    カレンダーAPIから空きのある日程を取得する。

    Returns:
        空きのある日程のリスト (ZANSEKI > 0 かつ予約受付期間内)
    """
    print(f"[INFO] カレンダーAPIにアクセス: {CALENDAR_API_URL}")
    response = requests.get(CALENDAR_API_URL, headers=REQUEST_HEADERS, timeout=30)
    response.raise_for_status()

    now_str = get_current_jst_str()
    available = []

    for line in response.text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue

        joen_date = record.get("JOEN_DATE", "")
        zanseki = int(record.get("ZANSEKI", 0))
        yoyaku_st = record.get("YOYAKU_STDATE", "")
        yoyaku_ed = record.get("YOYAKU_EDDATE", "")
        min_ryokin = record.get("MIN_RYOKIN", "")

        # 残席あり、かつ予約受付期間内
        if zanseki > 0 and yoyaku_st <= now_str <= yoyaku_ed:
            date_str = f"{joen_date[:4]}-{joen_date[4:6]}-{joen_date[6:8]}"
            available.append({
                "joen_date": joen_date,
                "date": date_str,
                "zanseki": zanseki,
                "min_ryokin": min_ryokin,
            })
            print(f"[INFO] 空きあり: {date_str} (残席: {zanseki}席, 料金: ¥{min_ryokin}～)")

    return available


def send_email(
    gmail_user: str,
    gmail_app_password: str,
    notify_to: str,
    available_dates: list[dict],
    ticket_url: str,
    is_test: bool = False,
) -> None:
    """Gmailで通知メールを送信する。"""
    if is_test and not available_dates:
        subject = "【チケット空き通知】テスト送信（現在空きなし）"
        body = f"""\
これはテスト送信です。

現在、空きのある日程はありません（全日程 × または予約期間外）。

確認URL:
{ticket_url}

確認時刻: {datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")}

---
このメールはチケット空き通知システムにより自動送信されました。
"""
    else:
        subject = "【チケット空き通知】MUNDO PIXAR TOKYO の空きが出ました！"
        dates_text = "\n".join(
            f"  ・{d['date']}（残席: {d['zanseki']}席, 料金: ¥{d['min_ryokin']}～）"
            for d in available_dates
        )
        body = f"""\
チケットの空きが検出されました。

空きのある日程:
{dates_text}

確認時刻: {datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")}

今すぐ予約してください:
{ticket_url}

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
    gmail_user = os.environ.get("GMAIL_USER", "").strip()
    gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    notify_to = os.environ.get("NOTIFY_TO", "").strip()
    ticket_url = os.environ.get("TICKET_URL", TICKET_PAGE_URL).strip()

    if not gmail_user or not gmail_app_password or not notify_to:
        print("[ERROR] Gmail設定 (GMAIL_USER, GMAIL_APP_PASSWORD, NOTIFY_TO) が不完全です")
        sys.exit(1)

    print(f"[INFO] 開始時刻: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S JST')}")

    state = load_state()
    prev_available_dates = set(state.get("last_available_dates", []))

    try:
        available_dates = fetch_available_dates()
    except Exception as e:
        print(f"[ERROR] カレンダー取得に失敗しました: {e}")
        print("[INFO] 誤通知防止のため、メール送信をスキップします")
        sys.exit(0)

    current_available_dates = {d["joen_date"] for d in available_dates}
    newly_available = [d for d in available_dates if d["joen_date"] not in prev_available_dates]

    print(f"[INFO] 空き日程数: {len(available_dates)} 件")

    now_iso = datetime.now(JST).isoformat()

    if force_notify:
        print("[INFO] --force-notify フラグにより強制通知します")
        try:
            send_email(
                gmail_user=gmail_user,
                gmail_app_password=gmail_app_password,
                notify_to=notify_to,
                available_dates=available_dates,
                ticket_url=ticket_url,
                is_test=True,
            )
        except Exception as e:
            print(f"[ERROR] メール送信に失敗しました: {e}")
            sys.exit(1)
    elif newly_available:
        print(f"[INFO] 新たな空き日程を検出: {[d['date'] for d in newly_available]}")
        try:
            send_email(
                gmail_user=gmail_user,
                gmail_app_password=gmail_app_password,
                notify_to=notify_to,
                available_dates=newly_available,
                ticket_url=ticket_url,
            )
        except Exception as e:
            print(f"[ERROR] メール送信に失敗しました: {e}")
            sys.exit(1)
    else:
        if not available_dates:
            print("[INFO] 通知不要: 空き日程なし（全日程 × または予約期間外）")
        else:
            print(f"[INFO] 通知不要: 新規空き日程なし（前回から変化なし）")

    state.update({
        "last_checked": now_iso,
        "last_available_dates": sorted(current_available_dates),
    })
    save_state(state)
    print("[INFO] チェック完了")


if __name__ == "__main__":
    force_notify = "--force-notify" in sys.argv
    main(force_notify=force_notify)
