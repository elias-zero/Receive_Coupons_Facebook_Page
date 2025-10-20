#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Post next coupon to Facebook page.
Designed to be run by GitHub Actions every 2 hours.
Saves published coupon ids to state.json and commits it back to repo.
"""

import os
import sys
import json
import subprocess
from datetime import datetime, timezone
from time import sleep

import requests
from dateutil import parser as date_parser

# Config (can override via env)
API_URL = os.getenv("COUPONS_API_URL", "https://receivecoupons.com/api/my_api.php")
STATE_FILE = os.getenv("STATE_FILE", "state.json")
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
FACEBOOK_ACCESS_TOKEN = os.getenv("FACEBOOK_ACCESS_TOKEN")
GIT_COMMIT_NAME = "github-actions[bot]"
GIT_COMMIT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"

REQUESTS_TIMEOUT = 15  # seconds
FACEBOOK_MESSAGE_MAX = 60000  # Facebook allows much longer posts

if not FACEBOOK_PAGE_ID or not FACEBOOK_ACCESS_TOKEN:
    print("ERROR: FACEBOOK_PAGE_ID and FACEBOOK_ACCESS_TOKEN must be provided in env.", file=sys.stderr)
    sys.exit(2)

def load_state(path):
    if not os.path.exists(path):
        return {"published_ids": [], "last_run": None}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(path, state):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def git_commit_and_push(path, message="Update state.json"):
    try:
        subprocess.check_call(["git", "config", "user.name", GIT_COMMIT_NAME])
        subprocess.check_call(["git", "config", "user.email", GIT_COMMIT_EMAIL])
        subprocess.check_call(["git", "add", path])
        subprocess.check_call(["git", "commit", "-m", message])
        subprocess.check_call(["git", "push"])
        print("State committed and pushed.")
    except subprocess.CalledProcessError as e:
        print("Git commit/push failed:", e, file=sys.stderr)

def fetch_coupons():
    try:
        r = requests.get(API_URL, timeout=REQUESTS_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            if "data" in data and isinstance(data["data"], list):
                return data["data"]
            for v in data.values():
                if isinstance(v, list):
                    return v
            return []
        elif isinstance(data, list):
            return data
        else:
            return []
    except Exception as e:
        print("Failed to fetch coupons:", e, file=sys.stderr)
        return []

def is_valid_coupon(coupon):
    try:
        if int(coupon.get("is_visible", 0)) != 1:
            return False
        expires = coupon.get("expires_at")
        if not expires:
            return True
        dt = date_parser.parse(expires)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt > datetime.now(timezone.utc)
    except Exception as e:
        print("Error checking coupon expiry:", e, file=sys.stderr)
        return False

def make_message(c):
    """Create Facebook post message"""
    parts = []
    
    # العنوان
    title = c.get("title") or ""
    if title:
        parts.append(f"🎉 {title}")
        parts.append("")
    
    # نص الخصم
    discount_text = c.get("discount_text") or ""
    if discount_text:
        parts.append(f"🔥 {discount_text}")
        parts.append("")
    
    # الكوبون
    code = c.get("code") or ""
    if code:
        parts.append(f"🎁 الكوبون: {code}")
        parts.append("")
    
    # الدول
    countries = c.get("countries") or ""
    if countries:
        parts.append(f"🌍 صالح لـ: {countries}")
        parts.append("")
    
    # الملاحظة
    note = c.get("note") or ""
    if note:
        parts.append(f"📌 ملاحظة: {note}")
        parts.append("")
    
    # تاريخ الانتهاء
    expires = c.get("expires_at") or ""
    if expires:
        try:
            dt = date_parser.parse(expires)
            expires_formatted = dt.strftime("%d-%m-%Y")
        except:
            expires_formatted = expires
        parts.append(f"⏳ ينتهي في: {expires_formatted}")
        parts.append("")
    
    # رابط الشراء
    link = c.get("purchase_link") or ""
    if link:
        parts.append(f"🛒 رابط الشراء: {link}")
        parts.append("")
    
    # رابط الموقع
    parts.append("💎 لمزيد من الكوبونات زوروا موقعنا:")
    parts.append("https://receivecoupons.com/")
    
    message = "\n".join(parts).strip()

    # truncate if too long
    if len(message) > FACEBOOK_MESSAGE_MAX:
        message = message[: FACEBOOK_MESSAGE_MAX - 3] + "..."
    return message

def post_to_facebook_with_photo(photo_url, message):
    """Post to Facebook page with photo"""
    url = f"https://graph.facebook.com/v21.0/{FACEBOOK_PAGE_ID}/photos"
    
    payload = {
        "url": photo_url,
        "message": message,
        "access_token": FACEBOOK_ACCESS_TOKEN
    }
    
    try:
        r = requests.post(url, data=payload, timeout=REQUESTS_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print("Failed to post photo to Facebook:", e, file=sys.stderr)
        if hasattr(e, 'response') and e.response is not None:
            print("Response:", e.response.text, file=sys.stderr)
        return None

def post_to_facebook_text_only(message):
    """Post to Facebook page (text only)"""
    url = f"https://graph.facebook.com/v21.0/{FACEBOOK_PAGE_ID}/feed"
    
    payload = {
        "message": message,
        "access_token": FACEBOOK_ACCESS_TOKEN
    }
    
    try:
        r = requests.post(url, data=payload, timeout=REQUESTS_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print("Failed to post to Facebook:", e, file=sys.stderr)
        if hasattr(e, 'response') and e.response is not None:
            print("Response:", e.response.text, file=sys.stderr)
        return None

def main():
    state = load_state(STATE_FILE)
    published_ids = set(state.get("published_ids", []))

    coupons = fetch_coupons()
    if not coupons:
        print("No coupons fetched. Exiting.")
        sys.exit(0)

    # keep only valid coupons
    valid = [c for c in coupons if is_valid_coupon(c)]
    if not valid:
        print("No valid (visible and not expired) coupons found.")
        sys.exit(0)

    # Sort by created_at
    def sort_key(c):
        try:
            return date_parser.parse(c.get("created_at") or c.get("expires_at") or "1970-01-01")
        except:
            return datetime.now(timezone.utc)

    valid_sorted = sorted(valid, key=sort_key)

    # find next unposted coupon
    next_coupon = None
    for c in valid_sorted:
        cid = int(c.get("coupon_id") or c.get("id") or 0)
        if cid not in published_ids:
            next_coupon = c
            break

    # If all coupons published, reset and start over
    if next_coupon is None:
        print("All coupons already published. Resetting published list and selecting first coupon.")
        published_ids = set()
        state["published_ids"] = []
        next_coupon = valid_sorted[0]

    if not next_coupon:
        print("No coupon to post. Exiting.")
        sys.exit(0)

    # Get photo URL from store logo or direct logo_url
    photo_url = next_coupon.get("store", {}).get("logo_url") or next_coupon.get("logo_url") or ""
    message = make_message(next_coupon)

    # Post to Facebook
    if photo_url:
        resp = post_to_facebook_with_photo(photo_url, message)
    else:
        resp = post_to_facebook_text_only(message)

    if resp and ("id" in resp or "post_id" in resp):
        # mark as published
        try:
            cid = int(next_coupon.get("coupon_id") or next_coupon.get("id") or 0)
            published_ids.add(cid)
            state["published_ids"] = sorted(list(published_ids))
            state["last_run"] = datetime.now(timezone.utc).isoformat()
            save_state(STATE_FILE, state)
            print(f"Posted coupon {cid} successfully to Facebook.")
            # commit state file back to repo
            git_commit_and_push(STATE_FILE, message=f"chore: mark coupon {cid} as published")
        except Exception as e:
            print("Failed updating state after post:", e, file=sys.stderr)
    else:
        print("Facebook API did not return success. Response:", resp, file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
