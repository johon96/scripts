import requests
from datetime import datetime, timedelta

# -------- CONFIG --------
ACCESS_TOKEN = "YOUR_STRAVA_ACCESS_TOKEN"
NUM_DAYS = 7  # Look back window
# ------------------------

# Compute date range
today = datetime.utcnow()
after = int((today - timedelta(days=NUM_DAYS)).timestamp())

# Get activities
url = "https://www.strava.com/api/v3/athlete/activities"
params = {"after": after, "per_page": 50}
headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

response = requests.get(url, headers=headers, params=params)
activities = response.json()

for act in activities:
    if act["type"] != "Run":
        continue
    
    # Run summary
    date = act["start_date_local"][:10]
    distance_km = round(act["distance"] / 1000, 2)
    moving_time = str(timedelta(seconds=act["moving_time"]))
    avg_pace = round((act["moving_time"] / 60) / distance_km, 2)  # min/km
    avg_hr = act.get("average_heartrate", "N/A")
    elev_gain = act.get("total_elevation_gain", 0)

    print(f"Date: {date}")
    print(f"Total: {distance_km} km | {moving_time} | Avg Pace: {avg_pace} min/km | Avg HR: {avg_hr} | Elev Gain: {elev_gain}m")
    
    # Optional: fetch detailed splits if available
    splits_url = f"https://www.strava.com/api/v3/activities/{act['id']}/streams"
    splits_params = {"keys": "distance,heartrate,altitude,time", "key_by_type": "true"}
    splits_resp = requests.get(splits_url, headers=headers, params=splits_params)
    splits_data = splits_resp.json()
    
    # Build per-km breakdown
    distance_stream = splits_data.get("distance", {}).get("data", [])
    hr_stream = splits_data.get("heartrate", {}).get("data", [])
    elev_stream = splits_data.get("altitude", {}).get("data", [])
    time_stream = splits_data.get("time", {}).get("data", [])
    
    if distance_stream and hr_stream and elev_stream and time_stream:
        print("Split/km | Pace | HR | Elev Gain")
        km_count = int(distance_stream[-1] // 1000) + 1
        for km in range(km_count):
            # Find all points in this km
            start_m = km * 1000
            end_m = (km + 1) * 1000
            indices = [i for i, d in enumerate(distance_stream) if start_m <= d < end_m]
            if not indices:
                continue
            t_start = time_stream[indices[0]]
            t_end = time_stream[indices[-1]]
            pace = round((t_end - t_start) / 60, 2)  # min/km
            hr_avg = round(sum(hr_stream[i] for i in indices) / len(indices), 1)
            elev_gain_km = round(elev_stream[indices[-1]] - elev_stream[indices[0]], 1)
            print(f"{km+1} | {pace} | {hr_avg} | {elev_gain_km}")
    print("\n" + "-"*40 + "\n")

