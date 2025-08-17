import requests
from datetime import datetime, timedelta, timezone
import json
import os

# -------- CONFIG --------
CLIENT_ID = "YOUR_CLIENT_ID"
CLIENT_SECRET = "YOUR_CLIENT_SECRET"
TOKEN_FILE = "strava_token.json"
NUM_DAYS = 7
# ------------------------

def load_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            return json.load(f)
    return None

def save_token(token_data):
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f)

def refresh_access_token(refresh_token):
    response = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token
        }
    )
    data = response.json()
    save_token(data)
    return data["access_token"], data["refresh_token"]

# Load token or refresh
token_data = load_token()
if token_data is None:
    raise Exception("You need to authorize once manually to get a refresh_token!")

access_token = token_data["access_token"]
refresh_token = token_data["refresh_token"]
expires_at = token_data.get("expires_at", 0)

if datetime.now(timezone.utc).timestamp() > expires_at:
    access_token, refresh_token = refresh_access_token(refresh_token)

# -------- Fetch Runs --------
today = datetime.utcnow()
after = int((today - timedelta(days=NUM_DAYS)).timestamp())

url = "https://www.strava.com/api/v3/athlete/activities"
params = {"after": after, "per_page": 50}
headers = {"Authorization": f"Bearer {access_token}"}

response = requests.get(url, headers=headers, params=params)
activities = response.json()

for act in activities:
    if act["type"] != "Run":
        continue
    
    # Run summary
    date = act["start_date_local"][:10]
    distance_km = round(act["distance"] / 1000, 2)
    moving_time = str(timedelta(seconds=act["moving_time"]))
    avg_pace = round((act["moving_time"] / 60) / distance_km, 2)
    avg_hr = act.get("average_heartrate", "N/A")
    elev_gain = act.get("total_elevation_gain", 0)

    print(f"Date: {date}")
    print(f"Total: {distance_km} km | {moving_time} | Avg Pace: {avg_pace} min/km | Avg HR: {avg_hr} | Elev Gain: {elev_gain}m")
    
    # Optional: fetch detailed splits
    splits_url = f"https://www.strava.com/api/v3/activities/{act['id']}/streams"
    splits_params = {"keys": "distance,heartrate,altitude,time", "key_by_type": "true"}
    splits_resp = requests.get(splits_url, headers=headers, params=splits_params)
    splits_data = splits_resp.json()
    
    distance_stream = splits_data.get("distance", {}).get("data", [])
    hr_stream = splits_data.get("heartrate", {}).get("data", [])
    elev_stream = splits_data.get("altitude", {}).get("data", [])
    time_stream = splits_data.get("time", {}).get("data", [])
    
    if distance_stream and hr_stream and elev_stream and time_stream:
        print("Split/km | Pace | HR | Elev Gain")
        km_count = int(distance_stream[-1] // 1000) + 1
        for km in range(km_count):
            start_m = km * 1000
            end_m = (km + 1) * 1000
            indices = [i for i, d in enumerate(distance_stream) if start_m <= d < end_m]
            if not indices:
                continue
            t_start = time_stream[indices[0]]
            t_end = time_stream[indices[-1]]
            pace = round((t_end - t_start) / 60, 2)
            hr_avg = round(sum(hr_stream[i] for i in indices) / len(indices), 1)
            elev_gain_km = round(elev_stream[indices[-1]] - elev_stream[indices[0]], 1)
            print(f"{km+1} | {pace} | {hr_avg} | {elev_gain_km}")
    print("\n" + "-"*40 + "\n")

