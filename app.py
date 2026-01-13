import os
import requests
from flask import Flask, request, redirect, jsonify, render_template_string
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

BASE_URL = "https://flex-uat.crif.com/orchestrator"
USERNAME = os.getenv("CRIF_USERNAME")
PASSWORD = os.getenv("CRIF_PASSWORD")
CALLBACK_BASE = os.getenv("CALLBACK_BASE_URL")

TEMPLATE_CODE = "UW001"

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

STATE = {}  # in-memory store

# ------------------------------------------------
def get_token():
    resp = requests.post(
        f"{BASE_URL}/public/api-user/token",
        json={"userName": USERNAME, "password": PASSWORD}
    )
    resp.raise_for_status()
    return resp.json()["access_token"]

# ------------------------------------------------
@app.route("/")
def home():
    return """
    <h2>Fetch Bank Statement</h2>
    <form method="post" action="/start">
        <input name="mobile" placeholder="Mobile Number" required />
        <button type="submit">Continue</button>
    </form>
    """

# ------------------------------------------------
@app.route("/start", methods=["POST"])
def start():
    mobile = request.form["mobile"]
    tracking_id = f"consent-{mobile}"

    token = get_token()

    STATE[tracking_id] = {
        "token": token,
        "mobile": mobile
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
            json=payload,
            headers={"Authorization": f"Bearer {token}"}
        )

        if resp.status_code == 200:
            data = resp.json()["data"]
            reference_id = data["consents"][0]["referenceId"]

            STATE[tracking_id]["referenceId"] = reference_id

            print("Consent initiated:", tracking_id, reference_id, flush=True)

            return redirect(data["redirectionUrl"])

    return "Consent initiation failed", 400

# ------------------------------------------------
@app.route("/callback", methods=["GET"])
def callback():
    tracking_id = request.args.get("trackingId")

    if not tracking_id or tracking_id not in STATE:
        return "Invalid callback", 400

    print("Consent approved for:", tracking_id, flush=True)

    # 🔥 Run fetch JSON immediately
    fetch_fi_json(tracking_id)

    return redirect(f"/result/{tracking_id}")

# ------------------------------------------------
def fetch_fi_json(tracking_id):
    ctx = STATE[tracking_id]

    payload = {
        "trackingId": tracking_id,
        "referenceId": ctx["referenceId"],
        "sessionId": "",
        "accountId": ""
    }

    resp = requests.post(
        f"{BASE_URL}/fiu-ws/fetch/JSON",
        headers={
            "Authorization": f"Bearer {ctx['token']}",
            "Content-Type": "application/json"
        },
        json=payload
    )

    print("Fetch JSON response:", resp.text, flush=True)

    try:
        STATE[tracking_id]["fi_json"] = resp.json()
    except Exception:
        STATE[tracking_id]["fi_json"] = {"error": resp.text}

# ------------------------------------------------
@app.route("/result/<tracking_id>")
def result(tracking_id):
    ctx = STATE.get(tracking_id)

    if not ctx or "fi_json" not in ctx:
        return "Data not available", 404

    return render_template_string("""
        <h3>Bank Statement JSON</h3>
        <pre>{{ data }}</pre>
    """, data=jsonify(ctx["fi_json"]).get_data(as_text=True))

# ------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
