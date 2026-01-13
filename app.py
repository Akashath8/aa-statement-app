import os
import requests
from flask import Flask, request, jsonify, redirect, render_template_string
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# ================= CONFIG =================
BASE_URL = os.getenv("CRIF_BASE_URL")
USERNAME = os.getenv("CRIF_USERNAME")
PASSWORD = os.getenv("CRIF_PASSWORD")
CALLBACK_BASE = os.getenv("CALLBACK_BASE_URL")

TEMPLATE_CODE = "UW001"   # ✅ CONFIRMED

# 🔴 Static FIP list (CRIF UAT – replace ONLY if CRIF gave others)
FIP_LIST = [
    "HDFC-UAT-FIP",
    "ICICI-UAT-FIP",
    "SBI-UAT-FIP",
    "IBFIP",
    "UBI-FIP",
    "YESB-UAT-FIP",
    "PNB-UAT-FIP"

]

# In-memory store (POC only)
STATE = {}

# ================= UTILS =================
def get_token():
    resp = requests.post(
        f"{BASE_URL}/public/api-user/token",
        json={"userName": USERNAME, "password": PASSWORD}
    )
    resp.raise_for_status()
    return resp.json()["access_token"]

# ================= UI =================
@app.route("/")
def home():
    return render_template_string("""
        <h2>Fetch Bank Statement</h2>
        <form method="post" action="/start">
            <input name="mobile" placeholder="Mobile Number" required />
            <button type="submit">Continue</button>
        </form>
    """)

# ================= START FLOW =================
@app.route("/start", methods=["POST"])
def start():
    mobile = request.form["mobile"]

    token = get_token()
    tracking_id = f"track-{mobile}"

    STATE[tracking_id] = {
        "token": token,
        "mobile": mobile
    }

    print("\n===== CONSENT INITIATE START =====")
    print("Tracking ID:", tracking_id)
    print("Template:", TEMPLATE_CODE)

    for fip in FIP_LIST:
        payload = {
            "templateCode": TEMPLATE_CODE,
            "trackingId": tracking_id,
            "phoneNumber": mobile,
            "redirectionBackUrl": f"{CALLBACK_BASE}/callback",
            "fipId": [fip]
        }

        print("\nTrying FIP:", fip)
        print("Payload:", payload)

        resp = requests.post(
            f"{BASE_URL}/fiu-ws/consent/initiate",
            json=payload,
            headers={"Authorization": f"Bearer {token}"}
        )

        print("Status:", resp.status_code)
        print("Response:", resp.text)

        if resp.status_code == 200:
            data = resp.json()["data"]
            STATE[tracking_id]["referenceId"] = data["consents"][0]["referenceId"]
            STATE[tracking_id]["fipId"] = fip

            print("✅ Consent initiated successfully for", fip)
            return redirect(data["redirectionUrl"])

    print("❌ Consent initiation failed for all FIPs")
    return "Consent initiation failed for all FIPs. Check server logs.", 400

# ================= CALLBACK =================
@app.route("/callback", methods=["POST"])
def callback():
    data = request.json

    print("\n===== CALLBACK RECEIVED =====")
    print(data)

    tracking_id = data["trackingId"]

    STATE[tracking_id]["sessionId"] = data["sessionId"]
    STATE[tracking_id]["accountId"] = data["accounts"][0]["accountId"]

    return """
        <h3>Consent completed successfully.</h3>
        <p>You may close this window.</p>
    """

# ================= FETCH JSON =================
@app.route("/statement/<tracking_id>")
def fetch_statement(tracking_id):
    ctx = STATE.get(tracking_id)
    if not ctx:
        return "Invalid trackingId", 404

    print("\n===== FETCH JSON =====")
    print("Tracking ID:", tracking_id)

    resp = requests.post(
        f"{BASE_URL}/fiu-ws/fetch/JSON",
        json={
            "trackingId": tracking_id,
            "referenceId": ctx["referenceId"],
            "sessionId": ctx["sessionId"],
            "accountId": ctx["accountId"]
        },
        headers={"Authorization": f"Bearer {ctx['token']}"}
    )

    print("Status:", resp.status_code)
    print("Response:", resp.text)

    return jsonify(resp.json())

# ================= RUN =================
app = app
