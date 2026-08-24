#!/usr/bin/env python3
import os
import sys
import json
import africastalking

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LIVE_API_KEY_PATH = os.path.join(SCRIPT_DIR, "live_api.txt")

if not os.path.exists(LIVE_API_KEY_PATH):
    print(f"[ERROR] live_api.txt not found at: {LIVE_API_KEY_PATH}")
    sys.exit(1)

with open(LIVE_API_KEY_PATH, "r") as f:
    live_api_key = f.read().strip()

if not live_api_key:
    print("[ERROR] live_api.txt is empty. Please add your Africa's Talking Live API Key.")
    sys.exit(1)

# Username for live production account.
# Note: On Africa's Talking, live username is your account/app username (not 'sandbox').
# Can be passed as 1st argument or set in live_username.txt / AFRICASTALKING_USERNAME env.
username = os.getenv("AFRICASTALKING_USERNAME")

USER_FILE = os.path.join(SCRIPT_DIR, "live_username.txt")
if not username and os.path.exists(USER_FILE):
    with open(USER_FILE, "r") as f:
        username = f.read().strip()

# Target phone number
target_phone = "+254713574168"
test_message = "HMS Live Test: Hello! This is a test message from your Hospital Management System."

if len(sys.argv) > 1 and sys.argv[1].startswith("+"):
    target_phone = sys.argv[1].replace(" ", "")
elif len(sys.argv) > 1 and not sys.argv[1].startswith("+"):
    username = sys.argv[1]

if len(sys.argv) > 2 and sys.argv[2].startswith("+"):
    target_phone = sys.argv[2].replace(" ", "")
elif len(sys.argv) > 2 and not sys.argv[2].startswith("+"):
    test_message = sys.argv[2]

if len(sys.argv) > 3:
    test_message = sys.argv[3]

print("=" * 60)
print("  Africa's Talking LIVE Production SMS Sender")
print("=" * 60)
print(f"Target Number: {target_phone}")
print(f"Message:       {test_message}")
print(f"Username:      {username if username else '(NOT SET - Live requires your Africa Talking username/app name)'}")

if not username:
    print("\n[IMPORTANT] Live Africa's Talking requires your account Username / App Name.")
    print("In your Africa's Talking dashboard, check the top-left or account dropdown for your App/Account Username.")
    print("Usage: python send_live_test.py <YOUR_USERNAME> \"+254713574168\"")
    sys.exit(1)

# Initialize SDK with Live credentials
africastalking.initialize(username, live_api_key)
sms = africastalking.SMS
application = africastalking.Application

try:
    print(f"\n[1] Fetching live account balance for user '{username}'...")
    app_data = application.fetch_application_data()
    balance = app_data.get("UserData", {}).get("balance", "N/A")
    print(f"Account Live Balance: {balance}")
except Exception as e:
    print(f"[WARNING] Could not retrieve balance: {e}")

try:
    print(f"\n[2] Sending Live SMS to {target_phone}...")
    response = sms.send(test_message, [target_phone], timeout=30)
    print("\n--- Live API Response ---")
    print(json.dumps(response, indent=2))
    
    recipients_data = response.get("SMSMessageData", {}).get("Recipients", [])
    for r in recipients_data:
        status = r.get("status")
        cost = r.get("cost")
        number = r.get("number")
        msg_id = r.get("messageId")
        print(f"\n[RESULT] Number: {number} | Status: {status} | Cost: {cost} | ID: {msg_id}")
        if status == "Success":
            print("\n[SUCCESS] Live SMS sent to the phone successfully!")
        else:
            print(f"\n[STATUS] {status}")
except Exception as e:
    print(f"\n[ERROR] Failed to send live SMS: {e}")
