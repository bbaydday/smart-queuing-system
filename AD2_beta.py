import os
import tkinter as tk
from tkinter import ttk, messagebox
import requests
import csv
import datetime
from Voice import play_voice
SERVER_URL = "http://192.168.20.77:5001"
CSV_FILE = "token.beta.csv"

class AdminWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Admin2 Interface - Smart Queue")
        self.geometry("1100x700")
        self.configure(bg="#ecf0f1")

        tk.Label(self, text=" Admin2 Dashboard", font=("Segoe UI", 20, "bold"), bg="#ecf0f1").pack(pady=10)

        # Buttons Frame
        btn_frame = tk.Frame(self, bg="#ecf0f1")
        btn_frame.pack(pady=5)

        self.call_btn = ttk.Button(btn_frame, text="📢 Call Next Token", command=self.call_next)
        self.call_btn.grid(row=0, column=0, padx=10)

        self.confirm_btn = ttk.Button(btn_frame, text="✅ Confirm Arrival", command=self.confirm_token)
        self.confirm_btn.grid(row=0, column=1, padx=10)

        self.skip_btn = ttk.Button(btn_frame, text="⏭ Skip Token", command=self.skip_selected)
        self.skip_btn.grid(row=0, column=2, padx=10)

        self.recall_btn = ttk.Button(btn_frame, text="🔁 Recall Skipped Token", command=self.recall_token)
        self.recall_btn.grid(row=0, column=3, padx=10)

        self.current_label = tk.Label(self, text="Now Serving: None", font=("Segoe UI", 34, "bold"), fg="#2980b9", bg="#ecf0f1")
        self.current_label.pack(pady=10)

        self.status_label = tk.Label(self, text="Server: Waiting...", font=("Segoe UI", 20), fg="#7f8c8d", bg="#ecf0f1")
        self.status_label.pack(pady=5)

        # Countdown label
        self.countdown_label = tk.Label(self, text="", font=("Segoe UI", 24, "bold"), fg="#e74c3c", bg="#ecf0f1")
        self.countdown_label.pack(pady=5)

        # Token Queues Display
        queue_frame = tk.Frame(self, bg="#ecf0f1")
        queue_frame.pack(pady=10, fill="both", expand=True)

        # Waiting Queue Treeview
        tk.Label(queue_frame, text="Waiting Queue (Called but not Ready)", font=("Segoe UI", 12, "bold"), bg="#ecf0f1").grid(row=0, column=0, sticky="w", padx=10)
        tk.Label(queue_frame, text="Ready Queue", font=("Segoe UI", 12, "bold"), bg="#ecf0f1").grid(row=0, column=1,sticky="w", padx=10)
        waiting_cols = ("Token", "Name", "Contact", "Age", "Gender", "Patient Type", "Timestamp")
        self.waiting_tree = ttk.Treeview(queue_frame, columns=waiting_cols, show="headings", height=7)
        for col in waiting_cols:
            self.waiting_tree.heading(col, text=col)
            self.waiting_tree.column(col, width=120, anchor="center")
        self.waiting_tree.grid(row=1, column=0, padx=10, pady=5)

        # Same for Ready Queue

        # Show only one column in Ready Queue
        ready_cols = ["Token No"]  # Replace with the column name you want to show
        self.ready_tree = ttk.Treeview(queue_frame, columns=ready_cols, show="headings", height=7)

        for col in ready_cols:
            self.ready_tree.heading(col, text=col)
            self.ready_tree.column(col, width=120, anchor="center")

        self.ready_tree.grid(row=1, column=1, padx=10, pady=5)
        # Skipped Tokens Listbox
        # Skipped Tokens Section
        skipped_frame = tk.Frame(self, bg="#ecf0f1")
        skipped_frame.pack(pady=10, fill="x")

        tk.Label(skipped_frame, text="Skipped Tokens", font=("Segoe UI", 12, "bold"), bg="#ecf0f1").pack(anchor="w",
                                                                                                         padx=10)

        self.skipped_listbox = tk.Listbox(skipped_frame, height=5, selectmode=tk.SINGLE)
        self.skipped_listbox.pack(padx=10, fill="x")

        # Fix for first click selection
        self.skipped_listbox.bind("<Button-1>", lambda e: self.skipped_listbox.focus_set())

        # Store previous serving token and start time for service duration logging
        self.previous_token = None
        self.call_start_time = None

        # Countdown timer variables
        self.countdown_seconds = 0
        self.countdown_token = None
        self.countdown_job = None  # after job id

        # Start periodic refresh
        self.refresh_status()

    def call_next(self):
        try:
            res = requests.post(f"{SERVER_URL}/call_token", timeout=5)
            res.raise_for_status()
            result = res.json()
            called = result.get("called")

            if not called:
                messagebox.showinfo("Info", "No tokens in waiting queue.")
                return

            # If previous token is now serving, record service duration before moving on
            if self.previous_token and self.call_start_time:
                call_end_time = datetime.datetime.now()
                duration = (call_end_time - self.call_start_time).total_seconds() / 60
                info = self._get_token_info(self.previous_token)
                if info:
                    self._append_to_csv({
                        "token": self.previous_token,
                        "name": info.get("Name", ""),
                        "contact": info.get("Contact", ""),
                        "age": info.get("Age", ""),
                        "gender": info.get("Gender", ""),
                        "patient_type": info.get("Patient Type", ""),
                        "service_time": round(duration, 2)
                    })

            self.previous_token = None
            self.call_start_time = None

            # Start countdown for the called token automatically
            self.countdown_token = called
            self.countdown_seconds = 50
            self.update_countdown()

            self.refresh_status()
            if called and called != "None":
                try:
                    token_number = int(called.split("-")[-1])
                    play_voice(token_number,mode="next")
                except Exception as e:
                    print(f"[Voice Error] {e}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to call next token:\n{e}")

    def update_countdown(self):
        if self.countdown_seconds > 0:
            self.countdown_label.config(text=f"Time left to confirm arrival: {self.countdown_seconds} seconds")
            self.countdown_seconds -= 1
            self.countdown_job = self.after(1000, self.update_countdown)
        else:
            # Time up, auto skip the token
            self.countdown_label.config(text="Time expired! Token auto-skipped.")
            self.auto_skip_countdown_token()

    def auto_skip_countdown_token(self):
        if self.countdown_token:
            try:
                res = requests.post(f"{SERVER_URL}/skip_token", json={"token": self.countdown_token}, timeout=5)
                res.raise_for_status()
                messagebox.showinfo("Auto Skipped", f"Token {self.countdown_token} was skipped due to no arrival confirmation.")
                # SkipVoice
                try:
                    token_number = int(self.countdown_token.split("-")[-1])
                    play_voice(token_number, mode="skip")
                except Exception as e:
                    print(f"[Voice Error] {e}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to auto-skip token:\n{e}")
            finally:
                self.countdown_token = None
                self.countdown_label.config(text="")
                self.refresh_status()


    def confirm_token(self):
        if not self.countdown_token:
            messagebox.showwarning("No Token Ready", "There is no token currently in Ready queue to confirm.")
            return

        token = self.countdown_token
        try:
            res = requests.post(f"{SERVER_URL}/confirm_token", json={"token": token}, timeout=5)
            res.raise_for_status()
            result = res.json()
            now_serving = result.get("now_serving")
            if now_serving:
                self.previous_token = now_serving
                self.call_start_time = datetime.datetime.now()

                # Stop countdown timer
                if self.countdown_job:
                    self.after_cancel(self.countdown_job)
                    self.countdown_job = None
                self.countdown_token = None
                self.countdown_label.config(text="")

                messagebox.showinfo("Confirmed", f"Token {now_serving} is now serving.")
                self.refresh_status()
                # ConfirmVoice
                if now_serving and now_serving != "None":
                    try:
                        token_number = int(now_serving.split("-")[-1])
                        play_voice(token_number, mode="serve")
                    except Exception as e:
                        print(f"[Voice Error] {e}")
            else:
                messagebox.showerror("Error", "Failed to confirm token.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to confirm token:\n{e}")

    def skip_selected(self):
        # Skip selected token from waiting or ready queue
        selected_waiting = self.waiting_tree.selection()
        selected_ready = self.ready_tree.selection()

        token = None
        if selected_waiting:
            token = self.waiting_tree.item(selected_waiting[0], "values")[0]
        elif selected_ready:
            token = self.ready_tree.item(selected_ready[0], "values")[0]
        else:
            messagebox.showwarning("Select Token", "Please select a token from Waiting or Ready queue to skip.")
            return

        # If skip token is the countdown token, cancel countdown
        if token == self.countdown_token:
            if self.countdown_job:
                self.after_cancel(self.countdown_job)
                self.countdown_job = None
            self.countdown_token = None
            self.countdown_label.config(text="")

        try:
            res = requests.post(f"{SERVER_URL}/skip_token", json={"token": token}, timeout=5)
            res.raise_for_status()
            messagebox.showinfo("Skipped", f"Token {token} moved to Skipped queue.")
            self.refresh_status()
            # SkipVoice
            try:
                token_number = int(token.split("-")[-1])
                play_voice(token_number, mode="skip")
            except Exception as e:
                print(f"[Voice Error] {e}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to skip token:\n{e}")

    def recall_token(self):
        # Recall a token from skipped queue to ready queue at position after now serving +3
        selected = self.skipped_listbox.curselection()
        if not selected:
            messagebox.showwarning("Select Token", "Please select a skipped token to recall.")
            return
        token = self.skipped_listbox.get(selected[0])

        try:
            res = requests.post(f"{SERVER_URL}/recall_token", json={"token": token}, timeout=5)
            res.raise_for_status()
            messagebox.showinfo("Recalled", f"Token {token} recalled to Ready queue.")
            self.refresh_status()
            # RecallVoice
            try:
                token_number = int(token.split("-")[-1])
                play_voice(token_number, mode="recall")
            except Exception as e:
                print(f"[Voice Error] {e}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to recall token:\n{e}")

    def _get_token_info(self, token):
        # Look in all queues to get token info for CSV logging
        for tree in [self.waiting_tree, self.ready_tree]:
            for child in tree.get_children():
                vals = tree.item(child, "values")
                if vals and vals[0] == token:
                    return {
                        "Name": vals[1],
                        "Contact": vals[2],
                        "Age": vals[3],
                        "Gender": vals[4],
                        "Patient Type": vals[5],

                    }
        return None

    def _append_to_csv(self, data):
        write_header = not os.path.isfile(CSV_FILE)
        with open(CSV_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=["token", "name", "contact", "age", "gender", "patient_type", "service_time"])
            if write_header:
                writer.writeheader()
            writer.writerow(data)

    def refresh_status(self):
        try:
            res = requests.get(f"{SERVER_URL}/current_token", timeout=5)
            now_serving = res.json().get("now_serving", "None")
            self.current_label.config(text=f"Now Serving: {now_serving}")
            self.status_label.config(text="Server: Connected")
        except:
            self.status_label.config(text="Server: Disconnected")

        try:
            res = requests.get(f"{SERVER_URL}/queue_status", timeout=5)
            data = res.json()

            self.waiting_tree.delete(*self.waiting_tree.get_children())
            for token in data.get("waiting", []):
                info_res = requests.get(f"{SERVER_URL}/token_info_json/{token}", timeout=3)
                if info_res.status_code == 200:
                    info = info_res.json()
                    self.waiting_tree.insert("", "end", values=(
                        info.get("token"),
                        info.get("name"),
                        info.get("contact", ""),
                        info.get("age", ""),
                        info.get("gender", ""),
                        info.get("patient_type", ""),
                        info.get("timestamp", "")
                    ))

            self.ready_tree.delete(*self.ready_tree.get_children())
            for token in data.get("ready", []):
                info_res = requests.get(f"{SERVER_URL}/token_info_json/{token}", timeout=3)
                if info_res.status_code == 200:
                    info = info_res.json()
                    self.ready_tree.insert("", "end", values=(
                        info.get("token"),
                        info.get("name"),
                        info.get("contact", ""),
                        info.get("age", ""),
                        info.get("gender", ""),
                        info.get("patient_type", ""),
                        info.get("timestamp", "")
                    ))

            self.skipped_listbox.delete(0, tk.END)
            for token in data.get("skipped", []):
                self.skipped_listbox.insert(tk.END, token)

        except Exception as e:
            print(f"Error refreshing queues: {e}")

        self.after(5000, self.refresh_status)


if __name__ == '__main__':
    app = AdminWindow()
    app.mainloop()
