import tkinter as tk
from tkinter import ttk, messagebox
import requests
import qrcode
from PIL import Image, ImageTk

SERVER_URL = "https://ready-squids-open.loca.lt"  # Change to your actual server URL if different

class UserWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Admin1 Interface - Smart Queue")
        self.geometry("600x750")
        self.configure(bg="#ecf0f1")

        ttk.Label(self, text="🎟 Generate Your Token", font=("Segoe UI", 18, "bold")).pack(pady=20)

        form_frame = ttk.Frame(self)
        form_frame.pack(pady=10)

        ttk.Label(form_frame, text="Full Name:").grid(row=0, column=0, sticky="e", padx=5, pady=5)
        self.name_entry = ttk.Entry(form_frame)
        self.name_entry.grid(row=0, column=1, padx=5)

        ttk.Label(form_frame, text="Contact:").grid(row=1, column=0, sticky="e", padx=5, pady=5)
        self.contact_entry = ttk.Entry(form_frame)
        self.contact_entry.grid(row=1, column=1, padx=5)

        ttk.Label(form_frame, text="Age:").grid(row=2, column=0, sticky="e", padx=5, pady=5)
        self.age_entry = ttk.Entry(form_frame)
        self.age_entry.grid(row=2, column=1, padx=5)

        ttk.Label(form_frame, text="Gender:").grid(row=3, column=0, sticky="e", padx=5, pady=5)
        self.gender_combo = ttk.Combobox(form_frame, values=["Male", "Female", "Other"])
        self.gender_combo.grid(row=3, column=1, padx=5)
        self.gender_combo.current(0)

        ttk.Label(form_frame, text="Patient Type:").grid(row=4, column=0, sticky="e", padx=5, pady=5)
        self.patient_type_combo = ttk.Combobox(form_frame, values=["New", "Follow Up"])
        self.patient_type_combo.grid(row=4, column=1, padx=5)
        self.patient_type_combo.current(0)



        self.generate_btn = ttk.Button(self, text="Generate Token", command=self.generate_token)
        self.generate_btn.pack(pady=15)

        self.result_label = ttk.Label(self, text="", font=("Segoe UI", 12), background="#ecf0f1", foreground="#2c3e50")
        self.result_label.pack(pady=5)

        self.qr_canvas = tk.Canvas(self, width=200, height=200, bg="white", highlightthickness=0)
        self.qr_canvas.pack(pady=10)

        self.token_info_label = ttk.Label(self, text="", font=("Segoe UI", 10), background="#ecf0f1", foreground="#34495e")
        self.token_info_label.pack(pady=10)

    def generate_token(self):
        name = self.name_entry.get().strip()
        contact = self.contact_entry.get().strip()
        age = self.age_entry.get().strip()
        gender = self.gender_combo.get()
        patient_type = self.patient_type_combo.get()


        if not name or not contact or not age:
            messagebox.showwarning("Input Error", "Please fill in all fields.")
            return

        payload = {
            "user_info": {
                "name": name,
                "contact": contact,
                "age": age,
                "gender": gender,
                "patient_type": patient_type,

            }
        }

        try:
            res = requests.post(f"{SERVER_URL}/generate_token", json=payload, timeout=5)
            res.raise_for_status()
            result = res.json()
        except requests.exceptions.RequestException as e:
            messagebox.showerror("Connection Error", f"Failed to contact server:\n{e}")
            return

        token = result["token"]
        predicted = result["predicted_wait"]
        position = result["position"]
        minutes = int(predicted)
        seconds = int(round((predicted - minutes) * 60))

        self.result_label.config(
            text=f"✅ Your Token: {token}\nEstimated Wait: {minutes} min {seconds} sec\nPosition: {position}"
        )

        # Generate QR code that points to token info page
        qr_url = f"{SERVER_URL}/token_info/{token}"
        qr_img = qrcode.make(qr_url)
        qr_img = qr_img.resize((200, 200), Image.LANCZOS)

        self.qr_tk_img = ImageTk.PhotoImage(qr_img)
        self.qr_canvas.create_image(0, 0, anchor="nw", image=self.qr_tk_img)

        self.token_info_label.config(text="📱 Scan QR to view token info")
        # ✅ ALSO: Save a copy to latest_qr.png for the website display
        try:
            img_for_web = qr_img
            img_for_web.save("static/qr_display/latest_qr.png")  # Must exist or create this folder

            # ✅ Notify Flask to update token
            requests.post(f"{SERVER_URL}/update-token", json={"token": token})

        except Exception as e:
            print("❌ Failed to update shared QR/token:", e)
        # Clear inputs for next entry
        self.name_entry.delete(0, tk.END)
        self.contact_entry.delete(0, tk.END)
        self.age_entry.delete(0, tk.END)
        self.gender_combo.current(0)
        self.patient_type_combo.current(0)



if __name__ == "__main__":
    app = UserWindow()
    app.mainloop()
