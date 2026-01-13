import os
import requests
from flask import Flask, request, redirect, render_template_string, jsonify
from dotenv import load_dotenv

load_dotenv()

print("🔥 APP STARTED 🔥", flush=True)

app = Flask(__name__)

# ================= CONFIG =================
BASE_URL = "https://flex-uat.crif.com/orchestrator"
USERNAME = os.getenv("CRIF_USERNAME")
PASSWORD = os.getenv("CRIF_PASSWORD")
CALLBACK_BASE = os.getenv("CALLBACK_BASE_URL")

TEMPLATE_CODE = "UW001"

# ⚠️ Use only FIPs enabled by CRIF for your FIU
FIP_LIST = [
    "HDFC-UAT-FIP",
    "ICICI-UAT-FIP",
    "SBI-UAT-FIP",
    "IBFIP",
    "UBI-FIP",
    "YESB-UAT-FIP",
    "setu-fip",
    "fip@finbank",
    "PNB-UAT-FIP",
    "AUBank-FIP",
    "CRIF-CONNECT-FIP-UAT-ALT",
    "BARB0KIMXXX",
    "dhanagarbank",
    "CRIF-CONNECT-FIP-UAT"
    "finsharebank",
    "sirius@finarkein"
    "FDRLFIP",
    "ACME-FIP"
]
# In-memory store (OK for UAT / POC)
STATE = {}

# ================= AUTH =================
def get_token():
    resp = requests.post(
        f"{BASE_URL}/public/api-user/token",
        json={"userName": USERNAME, "password": PASSWORD}
    )
    resp.raise_for_status()
    return resp.json()["access_token"]

# ================= CONSENT STATUS =================
def get_consent_status(tracking_id):
    ctx = STATE.get(tracking_id)
    if not ctx or "referenceId" not in ctx:
        return None

    payload = {
        "trackingId": tracking_id,
        "referenceId": ctx["referenceId"]
    }

    resp = requests.post(
        f"{BASE_URL}/fiu-ws/consent/status",
        headers={
            "Authorization": f"Bearer {ctx['token']}",
            "Content-Type": "application/json"
        },
        json=payload
    )

    print("CONSENT STATUS PAYLOAD:", payload, flush=True)
    print("CONSENT STATUS RESPONSE:", resp.text, flush=True)

    resp.raise_for_status()
    return resp.json().get("data")

# ================= FETCH JSON =================
def fetch_fi_json(tracking_id):
    ctx = STATE[tracking_id]

    # 1️⃣ Get consent status (THIS IS THE KEY STEP)
    status_data = get_consent_status(tracking_id)

    if not status_data:
        ctx["fi_json"] = {
            "status": "ERROR",
            "message": "Consent status not available"
        }
        return

    if status_data.get("status") != "COMPLETED":
        ctx["fi_json"] = {
            "status": "PENDING",
            "message": f"Consent status: {status_data.get('status')}"
        }
        return

    # 2️⃣ Extract sessionId & accountId
    session_id = status_data.get("sessionId")
    accounts = status_data.get("accounts", [])

    if not session_id or not accounts:
        ctx["fi_json"] = {
            "status": "ERROR",
            "message": "sessionId or accountId missing in consent status"
        }
        return

    account_id = accounts[0]["accountId"]

    # 3️⃣ Fetch JSON (SAME AS POSTMAN)
    payload = {
        "trackingId": tracking_id,
        "referenceId": ctx["referenceId"],
        "sessionId": session_id,
        "accountId": account_id
    }

    print("FINAL FETCH PAYLOAD:", payload, flush=True)

    resp = requests.post(
        f"{BASE_URL}/fiu-ws/fetch/JSON",
        headers={
            "Authorization": f"Bearer {ctx['token']}",
            "Content-Type": "application/json"
        },
        json=payload
    )

    print("FETCH JSON RESPONSE:", resp.text, flush=True)

    ctx["fi_json"] = resp.json()

# ================= UI =================
@app.route("/")
def home():
    print("HOME HIT", flush=True)
    return """
    <h2>Fetch Bank Statement</h2>
    <form method="post" action="/start">
        <input name="mobile" placeholder="Mobile Number" required />
        <button type="submit">Continue</button>
    </form>
    """

# ================= START CONSENT =================
@app.route("/start", methods=["POST"])
def start():
    mobile = request.form["mobile"]
    tracking_id = f"consent-{mobile}"

    print("START CONSENT:", tracking_id, flush=True)

    token = get_token()

    STATE[tracking_id] = {
        "mobile": mobile,
        "token": token
    }

    for fip in FIP_LIST:
        payload = {
            "templateCode": TEMPLATE_CODE,
            "trackingId": tracking_id,
            "phoneNumber": mobile,
            "redirectionBackUrl": f"{CALLBACK_BASE}/callback?trackingId={tracking_id}",
            "fipId": [fip]
        }

        resp = requests.post(
            f"{BASE_URL}/fiu-ws/consent/initiate",
            headers={"Authorization": f"Bearer {token}"},
            json=payload
        )

        print("CONSENT INITIATE FIP:", fip, flush=True)
        print("STATUS:", resp.status_code, flush=True)
        print("BODY:", resp.text, flush=True)

        if resp.status_code == 200:
            data = resp.json()["data"]
            reference_id = data["consents"][0]["referenceId"]

            STATE[tracking_id]["referenceId"] = reference_id

            print("CONSENT INITIATED SUCCESS", flush=True)
            print("Tracking ID :", tracking_id, flush=True)
            print("Reference ID:", reference_id, flush=True)

            return redirect(data["redirectionUrl"])

    return "Consent initiation failed for all FIPs", 400

# ================= CALLBACK =================
@app.route("/callback", methods=["GET"])
def callback():
    tracking_id = request.args.get("trackingId")

    if not tracking_id or tracking_id not in STATE:
        return "Invalid callback", 400

    print("CALLBACK RECEIVED:", tracking_id, flush=True)

    # 🔥 Trigger full fetch flow
    fetch_fi_json(tracking_id)

    return redirect(f"/result/{tracking_id}")

# ================= RESULT =================
@app.route("/result/<tracking_id>")
def result(tracking_id):
    ctx = STATE.get(tracking_id)

    if not ctx or "fi_json" not in ctx:
        return "Data not available yet", 404

    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Bank Statement JSON</title>
        <style>
            body {
            font-family: monospace;
            background: #f5f5f5;
            padding: 20px;
        }
        pre {
            background: #1e1e1e;
            color: #dcdcdc;
            padding: 20px;
            border-radius: 6px;
            overflow-x: auto;
            white-space: pre-wrap;
            word-wrap: break-word;
            font-size: 14px;
        }
        h3 {
            color: #333;
        }
    </style>
</head>
<body>

<h3>Bank Statement JSON (Postman Format)</h3>

<pre id="json"></pre>

<script>
    const data = {{ data | tojson }};
    document.getElementById("json").textContent =
        JSON.stringify(data, null, 2);
</script>

</body>
</html>
""", data=ctx["fi_json"])

# ================= RUN =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
