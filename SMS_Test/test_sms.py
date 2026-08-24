#!/usr/bin/env python3
import os
import sys
import json
import africastalking

# 1. Read API Key from api.txt in the same directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
API_KEY_PATH = os.path.join(SCRIPT_DIR, "api.txt")

if not os.path.exists(API_KEY_PATH):
    print(f"[ERROR] API key file not found at: {API_KEY_PATH}")
    sys.exit(1)

with open(API_KEY_PATH, "r") as f:
    api_key = f.read().strip()

if not api_key:
    print("[ERROR] api.txt is empty. Please add your Africa's Talking Sandbox API Key.")
    sys.exit(1)

# In sandbox, username is always 'sandbox'
username = "sandbox"

print("=" * 65)
print("  Africa's Talking Sandbox SMS Suite (Hospital Management System)")
print("=" * 65)
print(f"[INFO] Initializing SDK with username: '{username}'")

# 2. Initialize the SDK
africastalking.initialize(username, api_key)
sms = africastalking.SMS
application = africastalking.Application

def check_account_balance():
    """Fetch and display sandbox account user data & balance"""
    try:
        user_data = application.fetch_application_data()
        balance = user_data.get("UserData", {}).get("balance", "N/A")
        print(f"[ACCOUNT INFO] Sandbox Balance: {balance}")
        return balance
    except Exception as e:
        print(f"[WARNING] Could not fetch account info: {e}")
        return None

def send_single_sms(recipient_phone: str, message: str):
    """Send a single SMS message with a 30-second network timeout"""
    print(f"\n--- [1] Sending Single SMS ---")
    print(f"To:      {recipient_phone}")
    print(f"Message: {message}")
    
    try:
        # Increase timeout to 30 seconds for reliable sandbox network response
        response = sms.send(message, [recipient_phone], timeout=30)
        print("\n--- Response ---")
        print(json.dumps(response, indent=2))
        
        recipients_data = response.get("SMSMessageData", {}).get("Recipients", [])
        for r in recipients_data:
            status = r.get("status")
            cost = r.get("cost")
            number = r.get("number")
            msg_id = r.get("messageId")
            print(f"[RESULT] Number: {number} | Status: {status} | Cost: {cost} | ID: {msg_id}")
            
        return response
    except Exception as e:
        print(f"[ERROR] Failed to send single SMS: {e}")
        return None

def send_bulk_sms(recipients_list: list, message: str):
    """Send Bulk SMS to multiple patients / staff members"""
    print(f"\n--- [2] Sending Bulk SMS ({len(recipients_list)} recipients) ---")
    print(f"Recipients: {recipients_list}")
    print(f"Message:    {message}")
    
    try:
        response = sms.send(message, recipients_list, timeout=30)
        print("\n--- Response ---")
        print(json.dumps(response, indent=2))
        return response
    except Exception as e:
        print(f"[ERROR] Failed to send bulk SMS: {e}")
        return None

def fetch_inbox():
    """Fetch received messages from Africa's Talking Sandbox"""
    print(f"\n--- [3] Fetching Incoming SMS Messages (Inbox) ---")
    try:
        response = sms.fetch_messages(timeout=30)
        print(json.dumps(response, indent=2))
        return response
    except Exception as e:
        print(f"[ERROR] Failed to fetch messages: {e}")
        return None

if __name__ == "__main__":
    check_account_balance()
    
    # 1. Test Single SMS (Appointment confirmation)
    test_phone = sys.argv[1] if len(sys.argv) > 1 else "+254711082302"
    appointment_msg = "HMS Alert: Dear Patient, your doctor appointment is confirmed for tomorrow at 10:00 AM. Room 204."
    send_single_sms(test_phone, appointment_msg)
    
    # 2. Test Bulk SMS (Hospital Alert / Health campaign)
    bulk_numbers = [test_phone, "+254722000001", "+254733000002"]
    campaign_msg = "Hospital Notice: Free diabetes and blood pressure screening this Saturday from 8am."
    send_bulk_sms(bulk_numbers, campaign_msg)
    
    # 3. Test Fetching incoming inbox
    fetch_inbox()
    
    print("\n" + "=" * 65)
    print("  Testing Complete!")
    print(f"  Check the Africa's Talking Simulator with number {test_phone}")
    print("  URL: https://simulator.africastalking.com:15001/")
    print("=" * 65)
