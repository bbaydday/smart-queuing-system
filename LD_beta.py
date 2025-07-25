import tkinter as tk
from tkinter import ttk
import requests
import time

SERVER_URL = "http://192.168.20.77:5001"  # Replace with your server IP

class LiveDashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🏥 Live Dashboard - Smart Queue")
        self.geometry("900x700")
        self.configure(bg="#f5f6fa")

        tk.Label(self, text="🏥 ABC Clinic - Live Queue Display", font=("Segoe UI", 20, "bold"),
                 bg="#f5f6fa", fg="#2c3e50").pack(pady=15)

        self.now_serving_label = tk.Label(self, text="Now Serving: ---", font=("Segoe UI", 18),
                                          bg="#dff9fb", fg="#130f40", width=40)
        self.now_serving_label.pack(pady=10)

        self.up_next_label = tk.Label(self, text="Be Ready: ---", font=("Segoe UI", 16),
                                      bg="#f6e58d", fg="#7f8c8d", width=40)
        self.up_next_label.pack(pady=10)

        self.countdown_label = tk.Label(self, text="", font=("Segoe UI", 16, "bold"),
                                        bg="#f5f6fa", fg="#27ae60")
        self.countdown_label.pack(pady=5)

        self.queue_frame = ttk.LabelFrame(self, text="📋 Upcoming Tokens", padding=10)
        self.queue_frame.pack(pady=10, padx=20, fill="x")
        self.queue_list = tk.Label(self.queue_frame, text="Loading...", font=("Segoe UI", 14),
                                   bg="white", justify="left", anchor="w")
        self.queue_list.pack(fill="x")

        self.skip_frame = ttk.LabelFrame(self, text="⚠️ Skipped Tokens", padding=10)
        self.skip_frame.pack(pady=5, padx=20, fill="x")
        self.skip_list = tk.Label(self.skip_frame, text="None", font=("Segoe UI", 14),
                                  bg="white", justify="left", anchor="w")
        self.skip_list.pack(fill="x")

        self.message_bar = tk.Label(self, text="🔊 Please listen carefully for your token number...",
                                    font=("Segoe UI", 12), bg="#dcdde1", fg="#2d3436", pady=10)
        self.message_bar.pack(side="bottom", fill="x")

        self.current_ready_token = None
        self.ready_start_time = None
        self.countdown_active = False

        self.refresh()

    def refresh(self):
        try:
            # Get all queue data in a single try-except block
            now_res = requests.get(f"{SERVER_URL}/current_token", timeout=2)
            ready_res = requests.get(f"{SERVER_URL}/ready_queue", timeout=2)
            queue_res = requests.get(f"{SERVER_URL}/all_queue", timeout=2)
            skip_res = requests.get(f"{SERVER_URL}/skipped_list", timeout=2)

            now_token = now_res.json().get("now_serving", "None")
            ready_queue = ready_res.json().get("ready", [])
            queue = queue_res.json().get("queue", [])
            skipped = skip_res.json().get("skipped", [])

            # Update now serving display
            self.now_serving_label.config(text=f"Now Serving: {now_token if now_token != 'None' else '---'}")

            # Process ready queue
            # Process ready queue
            if ready_queue:
                first_ready = ready_queue[0]
                ready_token = first_ready['token'] if isinstance(first_ready, dict) else first_ready

                # Skip showing Be Ready if same as Now Serving
                if first_ready == now_token or first_ready.get('token') == now_token:
                    self.up_next_label.config(text="Be Ready: ---", fg="#7f8c8d")
                    self.reset_countdown()
                    self.current_ready_token = None  # Clear last tracked ready token
                else:
                    self.up_next_label.config(text=f"Be Ready: {ready_token}", fg="#e67e22")

                    if self.current_ready_token != ready_token:
                        self.current_ready_token = ready_token
                        self.ready_start_time = time.time()
                        self.countdown_active = True
                        self.update_countdown()
            else:
                self.up_next_label.config(text="Be Ready: ---", fg="#7f8c8d")
                self.reset_countdown()
                self.current_ready_token = None

            # Process upcoming queue
            # Process upcoming queue - FILTER out Now Serving token
            upcoming_tokens = []
            for entry in queue:
                token_value = entry.get('token') if isinstance(entry, dict) else str(entry)

                if token_value == now_token:
                    continue

                upcoming_tokens.append(token_value)

                if len(upcoming_tokens) >= 5:
                    break

            self.queue_list.config(
                text="  •  " + "    •  ".join(upcoming_tokens) if upcoming_tokens else "No upcoming tokens"
            )

            # Process skipped tokens with better error handling
            skipped_tokens = []
            if isinstance(skipped, list):
                for item in skipped:
                    if isinstance(item, dict):
                        skipped_tokens.append(item.get('token', '?'))
                    else:
                        skipped_tokens.append(str(item))

            self.skip_list.config(
                text="  •  " + "    •  ".join(skipped_tokens) if skipped_tokens else "No skipped tokens"
            )

        except requests.exceptions.RequestException as e:
            self.handle_connection_error()
        except Exception as e:
            print(f"[ERROR] Unexpected error: {e}")
            self.handle_connection_error()

        self.after(5000, self.refresh)

    def update_countdown(self):
        if self.current_ready_token and self.ready_start_time and self.countdown_active:
            elapsed = int(time.time() - self.ready_start_time)
            remaining = max(0, 50 - elapsed)

            if remaining > 0:
                self.countdown_label.config(text=f"⏳ Please arrive in: {remaining} sec", fg="#27ae60")
                self.after(1000, self.update_countdown)
            else:
                self.countdown_label.config(fg="#c0392b", text="⏱ Time Up!")

                try:
                    # Skip the token and immediately refresh the display
                    skip_response = requests.post(
                        f"{SERVER_URL}/skip_token",
                        json={"token": self.current_ready_token},
                        timeout=3
                    )

                    if skip_response.status_code == 200:
                        print(f"[INFO] Token {self.current_ready_token} auto-skipped after timeout.")
                        # Force immediate refresh to update skipped list
                        self.after(100, self.refresh)
                    else:
                        print(f"[ERROR] Failed to skip token. Status: {skip_response.status_code}")
                        self.countdown_label.config(text="Skip Failed!", fg="red")

                except requests.exceptions.RequestException as e:
                    print(f"[ERROR] Connection error while skipping token: {e}")
                    self.countdown_label.config(text="Connection Error", fg="red")
                    # Schedule a retry
                    self.after(3000, self.update_countdown)
                    return
                except Exception as e:
                    print(f"[ERROR] Unexpected error while skipping token: {e}")
                    self.countdown_label.config(text="Error", fg="red")

                # Reset countdown state
                self.reset_countdown()

    def reset_countdown(self):
        self.countdown_label.config(text="")
        self.current_ready_token = None
        self.ready_start_time = None
        self.countdown_active = False

    def handle_connection_error(self):
        self.now_serving_label.config(text="Now Serving: --- (Offline)")
        self.up_next_label.config(text="Be Ready: ---")
        self.queue_list.config(text="Server Unreachable - Please check connection")
        self.skip_list.config(text="---")
        self.countdown_label.config(text="Connection Lost", fg="red")
        self.reset_countdown()


if __name__ == "__main__":
    app = LiveDashboard()
    app.mainloop()