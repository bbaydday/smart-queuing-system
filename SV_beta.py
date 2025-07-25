import csv
import datetime
import json
import os
from threading import Timer

import joblib
import numpy as np
import pandas as pd
from flask import Flask, jsonify, render_template, request, send_from_directory
from pywebpush import WebPushException, webpush

app = Flask(__name__, template_folder="templates", static_folder="static")
qr_folder = os.path.join('static', 'qr_display')
latest_token_time = 0



@app.route('/check-new-token')
def check_new_token():
    global latest_token_time
    filepath = os.path.join(qr_folder, 'latest_qr.png')
    if os.path.exists(filepath):
        last_modified = os.path.getmtime(filepath)
        return jsonify({"updated": last_modified})
    return jsonify({"updated": 0})


@app.route('/qr_display')
def show_qr_display():
    return render_template('qr_display.html')
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
subscriptions = {}

# AI model loading
MODEL_PATH = "linear_service_time3_model.pkl"
model = None

def load_model():
    global model
    if os.path.isfile(MODEL_PATH):
        model = joblib.load(MODEL_PATH)
        print("✅ AI Model loaded successfully")
    else:
        print("⚠️ AI Model not found, using fallback")

load_model()

# === Helper Functions ===

def save_daily_record(record):
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    folder = "daily_logs"
    os.makedirs(folder, exist_ok=True)
    filename = os.path.join(folder, f"{today}.csv")

    file_exists = os.path.isfile(filename)
    with open(filename, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=record.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(record)

def predict_wait_time(position, queue_list):
    if model is None:
        return max(0, (position - 1) * 5)  # fallback: 5 min per token ahead
    X_pred_list = []
    for i in range(position - 1):
        if i >= len(queue_list):
            break
        p = queue_list[i]["user_info"]
        age = int(p.get("age", 30))
        gender = p.get("gender", "Male")
        patient_type = p.get("patient_type", "New")

        X_pred_list.append({
            "age": age,
            "gender": gender,
            "patient_type": patient_type,

        })
    if X_pred_list:
        df_pred = pd.DataFrame(X_pred_list)
        preds = model.predict(df_pred)
        return max(0, round(preds.sum(), 2))
    else:
        return 0

def start_countdown(token):
    """Start a 50-sec countdown timer for a token in waiting queue. Auto skip if no confirm."""
    def timeout_skip():
        print(f"⏰ Countdown expired, auto skipping token {token}")
        auto_skip_token(token)

    timer = Timer(50, timeout_skip)
    timer.start()
    countdown_timers[token] = timer

def cancel_countdown(token):
    timer = countdown_timers.pop(token, None)
    if timer:
        timer.cancel()

def auto_skip_token(token):
    """Auto move token from waiting -> skipped after countdown expires"""
    global waiting_queue, skipped_queue
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
    global skipped_queue, waiting_queue, ready_queue
    idx = next((i for i, t in enumerate(skipped_queue) if t["token"] == token), None)
    if idx is None:
        return False
    entry = skipped_queue.pop(idx)

    # Calculate insert position: after now serving + 3 in queue (count waiting + ready queues)
    insert_pos = 3  # after current now serving, next 3 tokens
    # Insert into ready queue at position insert_pos (or end if fewer tokens)
    if len(ready_queue) < insert_pos:
        ready_queue.append(entry)
    else:
        ready_queue.insert(insert_pos, entry)
    print(f"🔄 Token {token} recalled into Ready queue at position {insert_pos}")
    return True

def end_current_service():
    """Mark current token service as finished, log service duration"""
    global now_serving, now_serving_start_time, served_tokens
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
        "position": 0,
        "service_time": duration_minutes
    }
    save_daily_record(record)
    print(f"✅ Service ended for {now_serving}, duration: {duration_minutes} min")

    # Cleanup
    now_serving = None
    now_serving_start_time = None

# === Flask Routes ===

@app.route("/")
def index():
    return "✅ Smart Queue Server running"

@app.route("/generate_token", methods=["POST"])
def generate_token():
    global counter
    data = request.get_json()
    user_info = data.get("user_info", {})

    counter += 1
    token = f"T-{counter}"
    timestamp = datetime.datetime.now()
    entry = {
        "token": token,
        "user_info": user_info,
        "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
    }
    waiting_queue.append(entry)  # New tokens start in waiting (not ready)
    position = len(waiting_queue) + len(ready_queue) + (1 if now_serving else 0)

    predicted_wait = predict_wait_time(position, waiting_queue + ready_queue)

    return jsonify({
        "token": token,
        "position": position,
        "predicted_wait": round(predicted_wait, 2)
    })

@app.route("/call_token", methods=["POST"])
def call_token():
    """Admin presses Call for next token: move token from waiting to ready + start countdown"""
    if not waiting_queue:
        return jsonify({"error": "No tokens in waiting"}), 400
    entry = waiting_queue.pop(0)
    entry["status"] = "ready"  # <-- ဒီလိုသတ်မှတ်ပေးရတယ်
    ready_queue.append(entry)

    start_countdown(entry["token"])
    notify_users_before_turn()
    return jsonify({"called": entry["token"]})

@app.route("/confirm_token", methods=["POST"])
def confirm_token():
    """Admin presses Confirm when token arrives: move from ready to now_serving and start service timer"""
    global now_serving, now_serving_start_time, served_tokens

    data = request.get_json()
    token = data.get("token")
    idx = next((i for i, t in enumerate(ready_queue) if t["token"] == token), None)
    if idx is None:
        return jsonify({"error": "Token not in ready queue"}), 404

    entry = ready_queue.pop(idx)
    cancel_countdown(token)

    # If previous token is being served, end its service time
    if now_serving:
        end_current_service()

    now_serving = entry["token"]
    now_serving_start_time = datetime.datetime.now()
    served_tokens[now_serving] = entry["user_info"]

    return jsonify({"now_serving": now_serving})

@app.route("/skip_token", methods=["POST"])
def skip_token():
    data = request.get_json()
    token = data.get("token")
    print(f"[DEBUG] skip_token received: {token}")

    # waiting_queue ရှာပြီး token ရှိရင် pop လုပ်ပြီး skipped_queue ထဲ တိတိကျကျ entry ထည့်မယ်
    idx_wait = next((i for i, t in enumerate(waiting_queue) if t["token"] == token), None)
    if idx_wait is not None:
        entry = waiting_queue.pop(idx_wait)
        skipped_queue.append(entry)  # user_info မပျောက်အောင် တိတိကျကျထည့်မယ်
        return jsonify({"skipped": token})

    # ready_queue ရှာပြီး token ရှိရင် cancel countdown လုပ်ပြီး skip ထည့်မယ်
    idx_ready = next((i for i, t in enumerate(ready_queue) if t["token"] == token), None)
    if idx_ready is not None:
        cancel_countdown(token)
        entry = ready_queue.pop(idx_ready)
        skipped_queue.append(entry)  # user_info မပျောက်အောင် တိတိကျကျထည့်မယ်
        return jsonify({"skipped": token})

    return jsonify({"error": "Token not found in waiting or ready"}), 404

@app.route("/recall_token", methods=["POST"])
def recall_token():
    token = request.json.get("token")
    for t in skipped_queue:
        if t["token"] == token:
            skipped_queue.remove(t)

            # Find position to insert after top 2 waiting tokens
            insert_index = 2 if len(waiting_queue) >= 2 else len(waiting_queue)
            waiting_queue.insert(insert_index, t)

            return jsonify({"message": f"{token} recalled to Waiting queue at position {insert_index+1}."})
    return jsonify({"error": "Token not found in skipped list"}), 404

@app.route("/complete_current", methods=["POST"])
def complete_current():
    """Admin signals current token service complete"""
    global now_serving, now_serving_start_time

    if now_serving is None:
        return jsonify({"error": "No current serving token"}), 400

    end_current_service()

    return jsonify({"completed": True})

@app.route("/current_token")
def current_token_route():
    return jsonify({"now_serving": now_serving or "None"})
@app.route("/all_queue")
def all_queue_route():
    return jsonify({"queue": waiting_queue + ready_queue})

@app.route("/skipped_list")
def skipped_list_route():
    return jsonify({"skipped": [t["token"] for t in skipped_queue]})


@app.route("/queue_status")
def queue_status():
    """Return all queues for dashboard/admin views"""
    # Combine all tokens with their state for clarity
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
    # Search in all queues and now_serving
    entry = None
    for q in (waiting_queue, ready_queue, skipped_queue):
        entry = next((e for e in q if e["token"] == token_id), None)
        if entry:
            break
    if token_id == now_serving:
        user_info = served_tokens.get(token_id, {})
        entry = {"token": token_id, "user_info": user_info}

    if entry is None:
        return f"<h3>Token {token_id} not found.</h3>", 404

    # Calculate tokens ahead & estimated time
    # Combine waiting + ready queues as the 'ahead' queue except current token
    combined_queue = waiting_queue + ready_queue
    if now_serving:
        combined_queue = [ {"token": now_serving, "user_info": served_tokens.get(now_serving, {})} ] + combined_queue

    tokens_ahead = None
    for i, t in enumerate(combined_queue):
        if t["token"] == token_id:
            tokens_ahead = i
            break
    if tokens_ahead is None:
        tokens_ahead = 0

    estimated_time = predict_wait_time(tokens_ahead, combined_queue)

    return render_template("token_info.html",
                           token=entry["token"],
                           name=entry["user_info"].get("name", "User"),
                           tokens_ahead=tokens_ahead,
                           estimated_time=estimated_time,
                           vapid_public_key="BFQE_SsD83A8elK3yZWwtOEvK72UupklhnrpYDIo67C3k5t3ER1hU-0V2mtJ6B6_fKw73gRYCYsNOC5PDFXXgc4")


@app.route("/token_info_json/<token_id>")
def token_info_json(token_id):
    # Search token in all queues
    entry = None
    for q in (waiting_queue, ready_queue, skipped_queue):
        entry = next((e for e in q if e["token"] == token_id), None)
        if entry:
            break

    if token_id == now_serving:
        user_info = served_tokens.get(token_id, {})
        entry = {
            "token": token_id,
            "user_info": user_info,
            "timestamp": user_info.get("timestamp", "")
        }

    if entry is None:
        return jsonify({"error": "Token not found"}), 404

    # Build combined queue in same order as generate_token
    combined_queue = waiting_queue + ready_queue
    if now_serving:
        combined_queue = [{"token": now_serving, "user_info": served_tokens.get(now_serving, {})}] + combined_queue

    # Find both the display position (tokens_ahead) and calculation position
    tokens_ahead = 0
    calculation_position = 0
    found = False

    for i, t in enumerate(combined_queue):
        if t["token"] == token_id:
            tokens_ahead = i  # 0-based for display
            calculation_position = i + 1  # 1-based for calculation (matches generate_token)
            found = True
            break

    if not found:
        return jsonify({"error": "Token not in queue"}), 404

    # Use same calculation as generate_token
    estimated_time = predict_wait_time(calculation_position, combined_queue)

    return jsonify({
        "token": entry["token"],
        "name": entry["user_info"].get("name", "User"),
        "contact": entry["user_info"].get("contact", ""),
        "age": entry["user_info"].get("age", ""),
        "gender": entry["user_info"].get("gender", ""),
        "patient_type": entry["user_info"].get("patient_type", ""),
        "timestamp": entry.get("timestamp", entry["user_info"].get("timestamp", "")),
        "tokens_ahead": tokens_ahead,  # 0-based for display
        "estimated_time": estimated_time  # Matches AD1 calculation
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
    try:
        combined = waiting_queue + ready_queue
        for i in range(min(2, len(combined))):
            token = combined[i]["token"]
            sub = subscriptions.get(token)
            if sub:
                webpush(
                    subscription_info=sub,
                    data=json.dumps({
                        "title": "⏰ Almost your turn!",
                        "body": f"Your token {token} will be called soon.",
                        "url": f"/token_info/{token}"
                    }),
                    vapid_private_key="v3Ft3pCG86nc_xWveU-ZMkqdh_DPv06b4nVolljRtw8",
                    vapid_claims={"sub": "mailto:your@email.com"}
                )
                print(f"🔔 Sent push to {token}")
    except WebPushException as e:
        print(f"⚠️ Push error: {e}")

@app.route("/service-worker.js")
def service_worker():
    return send_from_directory("static", "service-worker.js")
@app.route("/live_dashboard")
def live_dashboard():
    return render_template("live_dashboard.html")

@app.route('/find_token', methods=['GET', 'POST'])
def find_token():
    if request.method == 'POST':
        phone = request.form.get('phone')
        matched = None
        token_entry = None
        estimated_time = None
        tokens_ahead = None

        # Search only active queues (not served)
        combined_queue = waiting_queue + ready_queue

        for entry in combined_queue:
            user_info = entry.get('user_info', {})
            if user_info.get('contact') == phone:
                matched = True
                token_entry = entry
                break

        if matched:
            # Calculate tokens ahead & estimated time
            tokens_ahead = combined_queue.index(token_entry)
            estimated_time = predict_wait_time(tokens_ahead, combined_queue)
            return render_template('found_token.html',
                                   token=token_entry,
                                   estimated_time=estimated_time,
                                   tokens_ahead=tokens_ahead)
        else:
            return render_template('found_token.html', error="❌ No active token found for this phone number.")

    # GET request: show form
    return render_template('find_token.html')



if __name__ == "__main__":
    os.makedirs("templates", exist_ok=True)
    app.run(host="0.0.0.0", port=5001)
