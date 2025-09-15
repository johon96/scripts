import requests
import json

CLIENT_ID = "173069"
CLIENT_SECRET = "YOUR_CLIENT_SECRET"
TOKEN_FILE = "strava_token.json"

# Replace this with the code you get from Strava after authorizing
CODE = "YOUR_AUTH_CODE"

def fetch_token(code):
    response = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code"
        }
    )

    if response.status_code != 200:
        print("Error fetching token:", response.status_code, response.text)
        if "Authorization Error" in response.text or "missing activity:read_permission" in response.text:
            print("\n⚠️  Your token is missing permissions. Please authorize again using this URL:\n")
            print(f"https://www.strava.com/oauth/authorize?client_id={CLIENT_ID}&response_type=code&redirect_uri=http://localhost&approval_prompt=force&scope=activity:read")
        return None

    data = response.json()
    with open(TOKEN_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print(f"✅ Access token saved to {TOKEN_FILE}")
    return data

token_data = fetch_token(CODE)
if token_data:
    print("Access Token:", token_data["access_token"])
    print("Refresh Token:", token_data["refresh_token"])

