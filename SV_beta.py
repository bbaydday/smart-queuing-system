import csv
import datetime
import json
import os
import sys
from threading import Timer

import joblib
import numpy as np
import pandas as pd
from flask import Flask, jsonify, render_template, request, send_from_directory
from pywebpush import WebPushException, webpush

# ===== Environment Variable Configuration (NEW) =====
# Production မှာ VAPID keys တွေကို Environment Variables ကနေ ဖတ်ယူမယ်။
# os.getenv() ကိုသုံးဖို့ os module ကို import လုပ်ထားပြီးသားဖြစ်လို့ ထပ်လုပ်စရာမလို။
# local မှာ test လုပ်ရင် .env file (python-dotenv နဲ့) သုံးရပါမယ်။
# Render မှာတော့ Render dashboard ရဲ့ Environment Variables ထဲမှာ ထည့်သွင်းရပါမယ်။
VAPID_PUBLIC_KEY = os.getenv("BFQE_SsD83A8elK3yZWwtOEvK72UupklhnrpYDIo67C3k5t3ER1hU-0V2mtJ6B6_fKw73gRYCYsNOC5PDFXXgc4")
VAPID_PRIVATE_KEY = os.getenv("v3Ft3pCG86nc_xWveU-ZMkqdh_DPv06b4nVolljRtw8")
VAPID_CLAIMS_SUB = os.getenv({"sub":"mailto:bdbayday988@email.com"})

# ====== Application Setup ======
# static_folder ကို root folder ကနေ static လို့ သတ်မှတ်ထားတာက Render မှာ အဆင်ပြေဆုံးပါ။
app = Flask(__name__, template_folder="templates", static_folder="static")

# QR code folder path ကို ပိုပြီး ကောင်းအောင်လုပ်မယ်။
# Render မှာ /static/qr_display ကို တိုက်ရိုက် serve ပေးမှာမို့ /static ထည့်စရာမလိုတော့ဘူး။
# ဒါပေမယ့် app.py ထဲကနေ files တွေ save လုပ်ဖို့အတွက် folder path က အရေးကြီးတယ်။
QR_DISPLAY_FOLDER = os.path.join(app.static_folder, 'qr_display')
# ဖိုင်မရှိရင် folder ဖန်တီးပေးဖို့ သေချာပါစေ။
os.makedirs(QR_DISPLAY_FOLDER, exist_ok=True)
# QR code တွေအတွက် URL prefix ကို /static/qr_display အောက်မှာ ရှိတယ်လို့ Flask ကို ပြောထားဖို့
# Flask ရဲ့ static_url_path ကို သုံးနိုင်တယ်။ (ဒါပေမယ့် အများအားဖြင့် default က အလုပ်လုပ်ပါတယ်။)
# app.static_url_path = '/static' (ဒါက default မို့ ထပ်ရေးစရာမလိုပါဘူး)

# Log folder path ကို ပိုပြီး ကောင်းအောင်လုပ်မယ်။
DAILY_LOGS_FOLDER = "daily_logs"
os.makedirs(DAILY_LOGS_FOLDER, exist_ok=True)


latest_token_time = 0

# === Queue Data Structures ===
counter = 0
waiting_queue = []     # tokens called but waiting for confirm (countdown ongoing)
ready_queue = []       # tokens confirmed to be served next (after confirm button)
skipped_queue = []
now_serving = None
now_serving_start_time = None
served_tokens = {}     # token -> user_info + start_time
countdown_timers = {}  # token -> Timer object

# Push subscription storage
subscriptions = {} # This will also reset on server restart on Render's free tier

# AI model loading
MODEL_PATH = "linear_service_time3_model.pkl"
model = None

def load_model():
    global model
    # Render မှာ model file က app.py နဲ့ တူညီတဲ့ root directory မှာ ရှိနေရပါမယ်။
    # os.path.abspath(__file__) ကိုသုံးပြီး လက်ရှိ file ရဲ့ directory ကို ရယူပါမယ်။
    current_dir = os.path.dirname(os.path.abspath(__file__))
    model_filepath = os.path.join(current_dir, MODEL_PATH)

    if os.path.isfile(model_filepath):
        try:
            model = joblib.load(model_filepath)
            print("✅ AI Model loaded successfully")
        except Exception as e:
            print(f"⚠️ Error loading AI Model: {e}, using fallback")
            model = None
    else:
        print(f"⚠️ AI Model not found at {model_filepath}, using fallback")
        model = None

load_model()

# === Helper Functions ===

def save_daily_record(record):
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    # folder = "daily_logs" # already defined globally
    # os.makedirs(folder, exist_ok=True) # already created globally
    filename = os.path.join(DAILY_LOGS_FOLDER, f"{today}.csv")

    file_exists = os.path.isfile(filename)
    try:
        with open(filename, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=record.keys())
            if not file_exists:
                writer.writeheader()
            writer.writerow(record)
        print(f"📄 Record saved to {filename}")
    except IOError as e:
        print(f"❌ Error saving daily record to {filename}: {e}")

def predict_wait_time(position, queue_list):
    if model is None:
        # Fallback logic: 5 minutes per token ahead (position is 1-based, tokens_ahead for display is 0-based)
        # For prediction, if position is 1, no one is ahead, so wait is 0.
        # If position is 2, 1 person is ahead, so wait is 5.
        return max(0, (position - 1) * 5)
    
    # AI model က gender, patient_type ကို string တွေနဲ့ မျှော်လင့်နေနိုင်တယ်၊
    # ဒါမှမဟုတ် model train တုန်းက One-Hot Encoding သုံးထားရင် production မှာလည်း encoding လုပ်ပေးရမယ်။
    # မင်းရဲ့ model က One-Hot Encoding လုပ်ထားတယ်ဆိုရင် code ထပ်ထည့်ရမယ်။
    # အခုတော့ model က string တွေကို တိုက်ရိုက်လက်ခံတယ်လို့ ယူဆပြီး gender, patient_type ကို string အတိုင်း ထည့်မယ်။
    
    X_pred_data = []
    # queue_list က combined_queue ဖြစ်နေနိုင်ပြီး now_serving လည်း ပါဝင်နိုင်တယ်။
    # position က 1-based ဖြစ်တာကြောင့် model အတွက် (position - 1) ကို ယူပြီး loop ပတ်မယ်။
    # loop ပတ်တဲ့အခါ 0 ကနေစပြီး position-2 အထိ (ဆိုလိုတာက 0 ကနေ position-1 အထိ)
    for i in range(position - 1): 
        if i >= len(queue_list):
            break # Ensure we don't go out of bounds if queue_list is shorter than expected
        
        # entry က token or user_info dict ဖြစ်နိုင်တယ်။
        # prediction အတွက် user_info dict ကိုပဲ လိုချင်တယ်။
        # now_serving token က user_info ကို served_tokens ကနေ ရယူထားနိုင်လို့ ဒီလိုရေးလိုက်တာပါ။
        
        current_entry_user_info = queue_list[i].get("user_info", {}) 
        
        age = int(current_entry_user_info.get("age", 30))
        gender = current_entry_user_info.get("gender", "Male")
        patient_type = current_entry_user_info.get("patient_type", "New")

        X_pred_data.append({
            "age": age,
            "gender": gender,
            "patient_type": patient_type,
        })

    if X_pred_data:
        # DataFrame ဖန်တီးတဲ့အခါ model train တုန်းက column order နဲ့ data types တွေ အတူတူဖြစ်ဖို့ အရေးကြီးတယ်။
        # One-Hot Encoding လုပ်ထားရင် ဒီနေရာမှာလည်း Encoding လုပ်ပေးရမယ်။
        # ဥပမာ- gender_Male, gender_Female, patient_type_New, patient_type_FollowUp စသည်ဖြင့်။
        df_pred = pd.DataFrame(X_pred_data)
        
        # မင်းရဲ့ model က feature တွေကို ဘယ်လိုမျှော်လင့်လဲဆိုတာ မူတည်ပြီး
        # ဒီနေရာမှာ One-Hot Encoding လုပ်ရနိုင်ပါတယ်။
        # ဥပမာ: df_pred = pd.get_dummies(df_pred, columns=['gender', 'patient_type'], drop_first=True)
        # ဒါမှမဟုတ် မင်းရဲ့ model က Pipeline တစ်ခုဖြစ်ပြီး preprocessing လုပ်ပြီးသားဆိုရင် ဒီအတိုင်းထားနိုင်ပါတယ်။

        try:
            preds = model.predict(df_pred)
            return max(0, round(preds.sum(), 2))
        except Exception as e:
            print(f"❌ Error during model prediction: {e}")
            # Prediction error ဖြစ်ရင် fallback ကို ပြန်သွား
            return max(0, (position - 1) * 5)
    else:
        return 0

def start_countdown(token):
    """Start a 50-sec countdown timer for a token in waiting queue. Auto skip if no confirm."""
    def timeout_skip():
        print(f"⏰ Countdown expired, auto skipping token {token}")
        auto_skip_token(token)

    # countdown_timers က global dict ဖြစ်ကြောင်း သေချာပါစေ။
    timer = Timer(50, timeout_skip)
    timer.start()
    countdown_timers[token] = timer

def cancel_countdown(token):
    timer = countdown_timers.pop(token, None)
    if timer:
        timer.cancel()

def auto_skip_token(token):
    """Auto move token from waiting -> skipped after countdown expires"""
    global waiting_queue, skipped_queue # Global variables ကို ပြောင်းလဲဖို့
    # Remove from waiting queue
    idx = next((i for i, t in enumerate(waiting_queue) if t["token"] == token), None)
    if idx is None:
        return
    entry = waiting_queue.pop(idx)
    cancel_countdown(token)
    skipped_queue.append(entry)
    print(f"⏭️ Token {token} auto skipped due to no confirmation")

def insert_recall_token(token):
    """Recall skipped token and insert after now serving + 3 positions"""
    global skipped_queue, waiting_queue, ready_queue # Global variables ကို ပြောင်းလဲဖို့
    idx = next((i for i, t in enumerate(skipped_queue) if t["token"] == token), None)
    if idx is None:
        return False
    entry = skipped_queue.pop(idx)

    # Calculate insert position: after now serving + 3 positions in queue (count ready queue only)
    # waiting_queue က countdown စောင့်နေတာမို့ ready_queue ထဲ ထည့်တာ ပိုကောင်းတယ်။
    # 3 positions after the currently serving token if any, or after 3 tokens in the ready queue.
    insert_pos = 3 # This logic might need refinement based on exact business rules
    
    # Insert into ready queue at position insert_pos (or end if fewer tokens)
    if len(ready_queue) < insert_pos:
        ready_queue.append(entry)
    else:
        ready_queue.insert(insert_pos, entry)
    print(f"🔄 Token {token} recalled into Ready queue at position {insert_pos}")
    return True

def end_current_service():
    """Mark current token service as finished, log service duration"""
    global now_serving, now_serving_start_time, served_tokens # Global variables ကို ပြောင်းလဲဖို့
    if now_serving is None or now_serving_start_time is None:
        return
    end_time = datetime.datetime.now()
    duration_minutes = round((end_time - now_serving_start_time).total_seconds() / 60, 2)
    user_info = served_tokens.get(now_serving, {})
    record = {
        "token": now_serving,
        "name": user_info.get("name", ""),
        "contact": user_info.get("contact", ""),
        "age": user_info.get("age", ""),
        "gender": user_info.get("gender", ""),
        "patient_type": user_info.get("patient_type", ""),
        "position": 0, # This position is for the served token, might be irrelevant for log.
        "service_time": duration_minutes,
        "end_time": end_time.strftime("%Y-%m-%d %H:%M:%S") # Log the end time
    }
    save_daily_record(record)
    print(f"✅ Service ended for {now_serving}, duration: {duration_minutes} min")

    # Cleanup
    now_serving = None
    now_serving_start_time = None

# === Flask Routes ===

@app.route("/")
def index():
    return "✅ Smart Queue Server running. Access /token_info/<token> for status, /live_dashboard for admin."

@app.route('/check-new-token')
def check_new_token():
    global latest_token_time
    # QR_DISPLAY_FOLDER က app.static_folder ထဲမှာ ရှိတယ်ဆိုရင်၊ Render က web ပေါ်မှာ /static/qr_display ကို တိုက်ရိုက် serve ပေးမှာပါ။
    # Flask ရဲ့ send_from_directory ကိုသုံးပြီး QR image ကို serve လုပ်နိုင်ပါတယ်။
    filepath = os.path.join(QR_DISPLAY_FOLDER, 'latest_qr.png')
    if os.path.exists(filepath):
        last_modified = os.path.getmtime(filepath)
        return jsonify({"updated": last_modified})
    return jsonify({"updated": 0})

# NOTE: QR code generation.
# မင်းရဲ့ code မှာ QR code generate လုပ်တဲ့ အပိုင်းကို မတွေ့ရဘူး။
# အကယ်၍ QR code ကို server-side မှာ generate လုပ်ပြီး file အဖြစ်သိမ်းရင်၊
# ထို logic ကိုလည်း ထည့်သွင်းရပါမယ်။ (ဥပမာ: qrcode library ကိုသုံးပြီး image အဖြစ်သိမ်းတာ)
# `qrcode` library ကိုသုံးရင် `requirements.txt` ထဲမှာ ထည့်ရပါမယ်။
# server restart မှာ image ပျောက်မယ်ဆိုတာ သတိရပါ။

@app.route('/qr_display')
def show_qr_display():
    # ဒီ HTML က /static/qr_display/latest_qr.png ကို ညွှန်ပြနေမှာဖြစ်ပြီး Flask က အလိုအလျောက် serve ပေးပါလိမ့်မယ်။
    return render_template('qr_display.html')


@app.route("/generate_token", methods=["POST"])
def generate_token():
    global counter, waiting_queue
    data = request.get_json()
    user_info = data.get("user_info", {})

    counter += 1
    token = f"T-{counter}"
    timestamp = datetime.datetime.now()
    entry = {
        "token": token,
        "user_info": user_info,
        "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "waiting" # Add status for clarity
    }
    waiting_queue.append(entry)
    
    # Calculate position for wait time prediction
    # If now_serving is active, it's position 1.
    # ready_queue are next, waiting_queue are after ready_queue.
    # So, position is 1 (for now_serving) + len(ready_queue) + current token's index in waiting_queue + 1
    # For a newly generated token, its position is at the end of (now_serving + ready_queue + waiting_queue)
    position_for_prediction = (1 if now_serving else 0) + len(ready_queue) + len(waiting_queue) # this token is at the end
    
    # predict_wait_time က 1-based position ကို မျှော်လင့်တယ်၊ ပြီးတော့ queue_list ကို
    # (now_serving + ready_queue + waiting_queue) ပုံစံမျိုး လိုချင်တယ်။
    # combined_queue မှာ now_serving ပါဝင်ရင် user_info ကို served_tokens ကနေ ရယူနိုင်ဖို့ သေချာပါစေ။
    combined_queue_for_pred = []
    if now_serving:
        combined_queue_for_pred.append({"token": now_serving, "user_info": served_tokens.get(now_serving, {})})
    combined_queue_for_pred.extend(ready_queue)
    combined_queue_for_pred.extend(waiting_queue) # includes the newly added token

    predicted_wait = predict_wait_time(position_for_prediction, combined_queue_for_pred)

    return jsonify({
        "token": token,
        "position": position_for_prediction, # This position is for display (1-based total queue length)
        "predicted_wait": round(predicted_wait, 2)
    })

@app.route("/call_token", methods=["POST"])
def call_token():
    """Admin presses Call for next token: move token from waiting to ready + start countdown"""
    global waiting_queue, ready_queue # Global ကို သေချာ declare လုပ်ပါ။
    if not waiting_queue:
        return jsonify({"error": "No tokens in waiting"}), 400
    
    # waiting_queue ရဲ့ ပထမဆုံး token ကိုယူမယ်။
    entry_to_call = waiting_queue.pop(0)
    entry_to_call["status"] = "ready" # status ကို update လုပ်
    ready_queue.append(entry_to_call)

    # countdown စတင်မယ်။
    start_countdown(entry_to_call["token"])
    
    # Notify လုပ်မယ်။
    notify_users_before_turn()
    
    print(f"➡️ Token {entry_to_call['token']} called and moved to ready queue.")
    return jsonify({"called": entry_to_call["token"]})

@app.route("/confirm_token", methods=["POST"])
def confirm_token():
    """Admin presses Confirm when token arrives: move from ready to now_serving and start service timer"""
    global now_serving, now_serving_start_time, served_tokens, ready_queue

    data = request.get_json()
    token = data.get("token")
    
    # ready_queue ထဲမှာ token ကို ရှာမယ်။
    # entry ကို pop လုပ်ဖို့ idx ကို ရှာမယ်။
    idx = next((i for i, t in enumerate(ready_queue) if t["token"] == token), None)
    if idx is None:
        return jsonify({"error": "Token not in ready queue or already served"}), 404

    entry = ready_queue.pop(idx) # ready_queue ကနေ ဖယ်ရှား
    cancel_countdown(token) # countdown ကို ရပ်မယ်။

    # If previous token is being served, end its service time
    if now_serving:
        end_current_service()

    # Now serving token အသစ်ကို သတ်မှတ်မယ်။
    now_serving = entry["token"]
    now_serving_start_time = datetime.datetime.now()
    # served_tokens ထဲမှာ user_info ကို သိမ်းထားမယ်။
    served_tokens[now_serving] = entry["user_info"]
    print(f"🟢 Token {now_serving} is now serving.")
    return jsonify({"now_serving": now_serving})

@app.route("/skip_token", methods=["POST"])
def skip_token():
    global waiting_queue, ready_queue, skipped_queue # Global ကို သေချာ declare လုပ်ပါ။
    data = request.get_json()
    token = data.get("token")
    print(f"[DEBUG] skip_token received: {token}")

    # waiting_queue မှာ ရှာမယ်
    idx_wait = next((i for i, t in enumerate(waiting_queue) if t["token"] == token), None)
    if idx_wait is not None:
        entry = waiting_queue.pop(idx_wait)
        entry["status"] = "skipped" # status ကို update
        skipped_queue.append(entry)
        cancel_countdown(token) # waiting queue မှာ countdown ရှိနိုင်လို့ cancel လုပ်မယ်။
        print(f"⏭️ Token {token} skipped from waiting queue.")
        return jsonify({"skipped": token})

    # ready_queue မှာ ရှာမယ်
    idx_ready = next((i for i, t in enumerate(ready_queue) if t["token"] == token), None)
    if idx_ready is not None:
        entry = ready_queue.pop(idx_ready)
        entry["status"] = "skipped" # status ကို update
        skipped_queue.append(entry)
        cancel_countdown(token) # ready queue မှာ countdown ရှိနိုင်လို့ cancel လုပ်မယ်။
        print(f"⏭️ Token {token} skipped from ready queue.")
        return jsonify({"skipped": token})

    return jsonify({"error": "Token not found in waiting or ready"}), 404

@app.route("/recall_token", methods=["POST"])
def recall_token():
    global skipped_queue, waiting_queue, ready_queue # Global ကို သေချာ declare လုပ်ပါ။
    token = request.json.get("token")
    
    idx = next((i for i, t in enumerate(skipped_queue) if t["token"] == token), None)
    if idx is None:
        return jsonify({"error": "Token not found in skipped list"}), 404
        
    entry = skipped_queue.pop(idx)
    entry["status"] = "recalled" # status update
    
    # Find position to insert after top 2 waiting tokens or into ready queue
    # အရင် code က waiting_queue ထဲကို ပြန်ထည့်ထားတာတွေ့တယ်။
    # အကယ်၍ recall လုပ်ရင် ready_queue ထဲကို ဥပမာ 3rd position လိုမျိုး ထည့်ချင်ရင်
    # insert_pos_ready = min(3, len(ready_queue))
    # ready_queue.insert(insert_pos_ready, entry)
    # ဒါမှမဟုတ် အရင် code အတိုင်း waiting_queue ထဲကိုပဲ ထည့်မယ်ဆိုရင်
    insert_index = 2 if len(waiting_queue) >= 2 else len(waiting_queue)
    waiting_queue.insert(insert_index, entry)
    
    print(f"🔄 Token {token} recalled to Waiting queue at position {insert_index+1}.")
    return jsonify({"message": f"{token} recalled to Waiting queue at position {insert_index+1}."})


@app.route("/complete_current", methods=["POST"])
def complete_current():
    """Admin signals current token service complete"""
    global now_serving, now_serving_start_time

    if now_serving is None:
        return jsonify({"error": "No current serving token"}), 400

    end_current_service()
    # If there are tokens in ready_queue, the next one should automatically become now_serving
    # This logic is not in your original code, but often desired.
    # If you want this, you'll need to add:
    # if ready_queue:
    #     next_entry = ready_queue.pop(0)
    #     now_serving = next_entry["token"]
    #     now_serving_start_time = datetime.datetime.now()
    #     served_tokens[now_serving] = next_entry["user_info"]
    #     print(f"🟢 Token {now_serving} is now serving automatically after completion.")

    return jsonify({"completed": True})

@app.route("/current_token")
def current_token_route():
    return jsonify({"now_serving": now_serving or "None"})

@app.route("/all_queue")
def all_queue_route():
    # waiting_queue, ready_queue, skipped_queue တွေက Dict တွေဖြစ်တာကြောင့် ဒီအတိုင်း jsonify လုပ်လို့ရတယ်။
    return jsonify({
        "waiting": waiting_queue,
        "ready": ready_queue,
        "now_serving": now_serving, # or a dict like {"token": now_serving, "user_info": served_tokens.get(now_serving, {})}
        "skipped": skipped_queue
    })

@app.route("/skipped_list")
def skipped_list_route():
    return jsonify({"skipped": skipped_queue}) # Full entry ကို ပြန်ပေးတာ ပိုကောင်းပါတယ်၊ token ပဲ ပြန်ပေးရင်တော့ [t["token"] for t in skipped_queue] လို့ ပြန်ရေးပါ။


@app.route("/queue_status")
def queue_status():
    """Return all queues for dashboard/admin views"""
    data = {
        "waiting": [t["token"] for t in waiting_queue],
        "ready": [t["token"] for t in ready_queue],
        "now_serving": now_serving or "None",
        "skipped": [t["token"] for t in skipped_queue]
    }
    return jsonify(data)

@app.route("/ready_queue")
def ready_queue_route():
    return jsonify({"ready": ready_queue})


@app.route("/token_info/<token_id>")
def token_info(token_id):
    entry = None
    position_in_queue = 0
    # Search in all queues and now_serving
    if token_id == now_serving:
        user_info = served_tokens.get(token_id, {})
        entry = {"token": token_id, "user_info": user_info, "status": "serving"}
        position_in_queue = 0 # Serving token is always at position 0 (first)

    if not entry: # If not serving, search in other queues
        combined_q = ready_queue + waiting_queue + skipped_queue
        for i, t_entry in enumerate(combined_q):
            if t_entry["token"] == token_id:
                entry = t_entry
                # Position in queue only makes sense for waiting/ready.
                # If it's in ready_queue, position is `i` within ready_queue
                # If it's in waiting_queue, position is `len(ready_queue) + i` within waiting_queue
                # If it's in skipped, its position is not relevant for 'tokens_ahead'
                break
    
    if entry is None:
        return f"<h3>Token {token_id} not found.</h3>", 404

    # Calculate tokens ahead & estimated time
    # Combine now_serving (if any) + ready_queue + waiting_queue for calculation
    combined_queue_for_prediction = []
    if now_serving:
        combined_queue_for_prediction.append({"token": now_serving, "user_info": served_tokens.get(now_serving, {})})
    combined_queue_for_prediction.extend(ready_queue)
    combined_queue_for_prediction.extend(waiting_queue)

    tokens_ahead = 0
    calculation_position = 0
    
    # Find token's position in the combined queue for prediction
    for i, t in enumerate(combined_queue_for_prediction):
        if t["token"] == token_id:
            tokens_ahead = i # 0-based for display
            calculation_position = i + 1 # 1-based for prediction function
            break
    
    # If token is in skipped_queue or served_tokens, tokens_ahead might be 0 or irrelevant
    # For a served token, tokens_ahead is 0, as it is being served.
    if token_id in served_tokens and token_id == now_serving:
        tokens_ahead = 0
        calculation_position = 1 # It's the first one

    estimated_time = predict_wait_time(calculation_position, combined_queue_for_prediction)

    # VAPID Public Key ကို Environment Variable ကနေ တိုက်ရိုက် မခေါ်ဘူးဆိုရင် ဒီနေရာမှာ
    # Hardcode လုပ်ထားတာမျိုး ဒါမှမဟုတ် .env ကနေ load လုပ်တာမျိုး ထားနိုင်ပါတယ်။
    # Frontend JS က ဒီ key ကို လိုပါတယ်။
    # Render မှာ VAPID_PUBLIC_KEY Environment Variable အနေနဲ့ ထည့်ပြီး ဒီနေရာကနေ ခေါ်တာက ပိုကောင်းပါတယ်။
    # ဥပမာ: vapid_public_key=os.getenv("VAPID_PUBLIC_KEY", "YOUR_HARDCODED_PUBLIC_KEY_FALLBACK")
    # အခုတော့ မင်းရဲ့ code ထဲကအတိုင်းပဲ ထားလိုက်ပါမယ်။ ဒါပေမယ့် Frontend မှာ ဒီ key ရှိဖို့လိုပါတယ်။
    return render_template("token_info.html",
                           token=entry["token"],
                           name=entry["user_info"].get("name", "User"),
                           tokens_ahead=tokens_ahead,
                           estimated_time=estimated_time,
                           vapid_public_key=VAPID_PUBLIC_KEY)


@app.route("/token_info_json/<token_id>")
def token_info_json(token_id):
    entry = None
    # Search token in all queues
    for q in (waiting_queue, ready_queue, skipped_queue):
        entry = next((e for e in q if e["token"] == token_id), None)
        if entry:
            break

    if token_id == now_serving:
        user_info = served_tokens.get(token_id, {})
        # Ensure timestamp is available for now_serving
        entry = {
            "token": token_id,
            "user_info": user_info,
            "timestamp": user_info.get("timestamp", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")) # Provide a fallback
        }

    if entry is None:
        return jsonify({"error": "Token not found"}), 404

    # Build combined queue for prediction
    combined_queue_for_prediction = []
    if now_serving:
        combined_queue_for_prediction.append({"token": now_serving, "user_info": served_tokens.get(now_serving, {})})
    combined_queue_for_prediction.extend(ready_queue)
    combined_queue_for_prediction.extend(waiting_queue)

    tokens_ahead = 0
    calculation_position = 0
    found = False

    for i, t in enumerate(combined_queue_for_prediction):
        if t["token"] == token_id:
            tokens_ahead = i  # 0-based for display
            calculation_position = i + 1  # 1-based for calculation (matches generate_token)
            found = True
            break

    if not found and token_id not in served_tokens: # If not found and not a previously served token
         return jsonify({"error": "Token not in active queue"}), 404

    # If it was a served token that's not now_serving, it's not in combined_queue for prediction.
    # In this case, tokens_ahead and estimated_time should reflect it's done.
    if token_id in served_tokens and token_id != now_serving and not found:
        return jsonify({
            "token": entry["token"],
            "name": entry["user_info"].get("name", "User"),
            "contact": entry["user_info"].get("contact", ""),
            "age": entry["user_info"].get("age", ""),
            "gender": entry["user_info"].get("gender", ""),
            "patient_type": entry["user_info"].get("patient_type", ""),
            "timestamp": entry.get("timestamp", entry["user_info"].get("timestamp", "")),
            "tokens_ahead": "N/A",  # No longer in active queue
            "estimated_time": "Completed" # Or some other indicator
        })


    estimated_time = predict_wait_time(calculation_position, combined_queue_for_prediction)

    return jsonify({
        "token": entry["token"],
        "name": entry["user_info"].get("name", "User"),
        "contact": entry["user_info"].get("contact", ""),
        "age": entry["user_info"].get("age", ""),
        "gender": entry["user_info"].get("gender", ""),
        "patient_type": entry["user_info"].get("patient_type", ""),
        "timestamp": entry.get("timestamp", entry["user_info"].get("timestamp", "")),
        "tokens_ahead": tokens_ahead,
        "estimated_time": estimated_time
    })

@app.route("/save_subscription", methods=["POST"])
def save_subscription():
    data = request.get_json()
    token = data.get("token")
    subscription = data.get("subscription")

    if token and subscription:
        subscriptions[token] = subscription
        print(f"✅ Saved push subscription for {token}")
        return jsonify({"status": "success"})
    return jsonify({"error": "Invalid subscription data"}), 400

def notify_users_before_turn():
    """Notify next 2 tokens in waiting+ready about upcoming turn"""
    # VAPID keys တွေကို Environment Variables ကနေ ဖတ်ယူဖို့ ပြင်ဆင်ထားပါတယ်။
    if not VAPID_PRIVATE_KEY or not VAPID_CLAIMS_SUB:
        print("⚠️ VAPID_PRIVATE_KEY or VAPID_CLAIMS_SUB is not set. Cannot send push notifications.")
        return

    try:
        combined = ready_queue + waiting_queue # Call ready first, then waiting
        for i in range(min(2, len(combined))):
            token_entry = combined[i]
            token = token_entry["token"]
            sub = subscriptions.get(token)
            if sub:
                # Flask app ရဲ့ public URL ကို ဒီနေရာမှာ သုံးရပါမယ်။
                # Request context မရှိတဲ့အတွက် url_for ကို တိုက်ရိုက် သုံးမရပါဘူး။
                # ဒါပေမယ့် webpush notification ရဲ့ url က client-side JS ကနေ ဖွင့်မှာမို့
                # Render မှာ deploy ပြီးမှ ရလာမယ့် Public URL ကို ဒီမှာ hardcode လုပ်ထားရနိုင်ပါတယ်။
                # (သို့မဟုတ် client side ကနေ URL ကို push data မှာ ထည့်ပေးတာ ပိုကောင်းပါတယ်)
                # အခုတော့ /token_info/{token} ကို တိုက်ရိုက်သုံးလိုက်ပါမယ်။
                
                # Render မှာ Public URL ကို Environment Variable အဖြစ် ထည့်သွင်းပြီး ဒီနေရာမှာ ခေါ်သုံးနိုင်ပါတယ်။
                # BASE_URL = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:5001") # Render က auto inject လုပ်ပေးနိုင်တယ်။
                # full_url = f"{BASE_URL}/token_info/{token}"
                
                webpush(
                    subscription_info=sub,
                    data=json.dumps({
                        "title": "⏰ Almost your turn!",
                        "body": f"Your token {token} will be called soon.",
                        "url": f"/token_info/{token}" # Client-side JS က ဒါကို Handle လုပ်ရပါမယ်။
                    }),
                    vapid_private_key=VAPID_PRIVATE_KEY, # Environment variable
                    vapid_claims={"sub": VAPID_CLAIMS_SUB} # Environment variable
                )
                print(f"🔔 Sent push to {token}")
    except WebPushException as e:
        print(f"⚠️ Push error: {e}")
        # WebPushException ကနေ error details တွေကို ထုတ်ယူနိုင်ပါတယ်။
        if e.response and hasattr(e.response, 'text'):
            print(f"Push Error Details: {e.response.status_code} - {e.response.text}")
        else:
            print(f"Push Error Details: {e}")
    except Exception as e:
        print(f"⚠️ An unexpected error occurred during push notification: {e}")


@app.route("/service-worker.js")
def service_worker():
    return send_from_directory(app.static_folder, "service-worker.js")

@app.route("/live_dashboard")
def live_dashboard():
    return render_template("live_dashboard.html")

@app.route('/find_token', methods=['GET', 'POST'])
def find_token():
    if request.method == 'POST':
        phone = request.form.get('phone')
        matched_entry = None

        # Search in active queues (now_serving, ready_queue, waiting_queue)
        combined_active_queue = []
        if now_serving:
            combined_active_queue.append({"token": now_serving, "user_info": served_tokens.get(now_serving, {})})
        combined_active_queue.extend(ready_queue)
        combined_active_queue.extend(waiting_queue)


        for entry in combined_active_queue:
            user_info = entry.get('user_info', {})
            if user_info.get('contact') == phone:
                matched_entry = entry
                break

        if matched_entry:
            # Calculate tokens ahead & estimated time for the found token
            tokens_ahead = combined_active_queue.index(matched_entry) # 0-based for display
            calculation_position = tokens_ahead + 1 # 1-based for prediction function

            estimated_time = predict_wait_time(calculation_position, combined_active_queue)
            
            return render_template('found_token.html',
                                   token=matched_entry,
                                   estimated_time=estimated_time,
                                   tokens_ahead=tokens_ahead)
        else:
            # Check if token was recently served
            found_in_served = False
            for token_id, user_info in served_tokens.items():
                if user_info.get('contact') == phone:
                    # Found in served, but not active.
                    return render_template('found_token.html', error=f"✅ Token for this phone number has already been served.")
            
            return render_template('found_token.html', error="❌ No active token found for this phone number.")

    # GET request: show form
    return render_template('find_token.html')


# The `if __name__ == "__main__":` block should be removed or changed for Render.
# Render (and Gunicorn) will call your 'app' instance directly, not run this block.
# So, the `app.run()` line is for local development only.
# Render မှာ deployment လုပ်တဲ့အခါ ဒီအောက်က code ကို မပါဝင်စေသင့်ပါဘူး။
# os.makedirs("templates", exist_ok=True) # templates folder ကို ဖန်တီးဖို့ မလိုပါဘူး။ static_folder ကိုလည်း ထပ်ဖန်တီးဖို့ မလိုပါဘူး။
# if __name__ == "__main__":
#     os.makedirs("templates", exist_ok=True) # templates folder ကို Flask က သိပြီးသား
#     app.run(host="0.0.0.0", port=5001)

# For Render deployment, Gunicorn will run the app using `gunicorn app:app`
# So, no need for if __name__ == "__main__": block for production.
