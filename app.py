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

TEMPLATE_CODE = "UW001"

# Static FIP list (update only if CRIF gives different IDs)
FIP_LIST = [
    "HDFC-UAT-FIP",
    "ICICI-UAT-FIP",
    "SBI-UAT-FIP"
]

# In-memory store (POC only)
STATE = {}

# ================= UTIL =================
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

# ================= START CONSENT =================
@app.route("/start", methods=["POST"])
def start():
    mobile = request.form["mobile"]
    tracking_id = f"track-{mobile}"

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
            "redirectionBackUrl": f"{CALLBACK_BASE}/callback",
            "fipId": [fip]
        }

        resp = requests.post(
            f"{BASE_URL}/fiu-ws/consent/initiate",
            json=payload,
            headers={"Authorization": f"Bearer {token}"}
        )

        if resp.status_code == 200:
            data = resp.json()["data"]
            STATE[tracking_id]["referenceId"] = data["consents"][0]["referenceId"]
            STATE[tracking_id]["fipId"] = fip
            # 🔥 ADD THESE LOGS
            print("===== CONSENT INITIATED =====")
            print("Tracking ID :", tracking_id)
            print("Reference ID:", STATE[tracking_id]["referenceId"])
            print("FIP ID      :", fip)
            print("============================")
            return redirect(data["redirectionUrl"])

    return "Consent initiation failed for all FIPs", 400

# ================= CALLBACK =================
@app.route("/callback", methods=["GET", "POST"])
def callback():
    print("\n===== CALLBACK HIT =====")
    print("Method:", request.method)

    # ---- Browser redirect (GET) ----
    if request.method == "GET":
        tracking_id = request.args.get("trackingId")
        if tracking_id:
            return redirect(f"/wait/{tracking_id}")

        return """
        <h3>Consent approved successfully.</h3>
        <p>You may close this window.</p>
        """

    # ---- CRIF server callback (POST) ----
    data = request.get_json(force=True, silent=True)
    print("POST payload:", data)

    if not data:
        return "OK", 200

    tracking_id = data.get("trackingId")
    STATE.setdefault(tracking_id, {})

    STATE[tracking_id]["sessionId"] = data.get("sessionId")
    STATE[tracking_id]["accountId"] = data.get("accounts", [{}])[0].get("accountId")

    print("Callback stored for:", tracking_id)
    return "OK", 200

# ================= WAIT PAGE (AUTO-POLL) =================
@app.route("/wait/<tracking_id>")
def wait_page(tracking_id):
    return f"""
    <html>
    <head>
        <title>Fetching Statement</title>
        <script>
            async function poll() {{
                const res = await fetch("/statement/{tracking_id}");
                const data = await res.json();

                if (data.status === "PENDING") {{
                    document.getElementById("status").innerText = data.message;
                }} else {{
                    document.body.innerHTML =
                        "<pre>" + JSON.stringify(data, null, 2) + "</pre>";
                }}
            }}

            setInterval(poll, 3000);
            window.onload = poll;
        </script>
    </head>
    <body>
        <h3>Fetching your bank statement…</h3>
        <p id="status">Please wait</p>
    </body>
    </html>
    """

# ================= FETCH STATEMENT =================
@app.route("/statement/<tracking_id>")
def fetch_statement(tracking_id):
    ctx = STATE.get(tracking_id)

    if not ctx:
        return jsonify({
            "status": "PENDING",
            "message": "Consent data not available yet. Please wait."
        }), 202

    required = ["token", "referenceId", "sessionId", "accountId"]
    missing = [k for k in required if k not in ctx]

    if missing:
        return jsonify({
            "status": "PENDING",
            "message": "Waiting for consent completion",
            "missing": missing
        }), 202

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

    return jsonify(resp.json())

# ================= RUN (RENDER COMPATIBLE) =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
