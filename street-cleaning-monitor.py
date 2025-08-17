import sys
if sys.version_info < (3, 7):
    print("This script requires Python 3.7 or newer")
    sys.exit(1)

import requests
from shapely.geometry import Point, LineString
from shapely.ops import nearest_points
import json
import os
from datetime import datetime, timedelta
import calendar
import subprocess
import smtplib
from email.mime.text import MIMEText
from aiohttp import ClientSession
from pytile import async_login
from typing import Dict, Optional, Any
import asyncio
import time

def check_dependencies():
    """Check if all required packages are installed"""
    try:
        import requests
        import shapely
    except ImportError as e:
        print(f"Missing required package: {e.name}")
        print("Please install required packages using:")
        print("pip3 install requests shapely")
        sys.exit(1)

def read_findmy_data():
    """Read and parse the Find My items data file"""
    # file_path = os.path.expanduser('~/tmp.json')
    file_path = os.path.expanduser('~/Library/Caches/com.apple.findmy.fmipcore/Items.data')
    try:
        with open(file_path, 'r') as file:
            data = json.load(file)
            return data
    except Exception as e:
        print(f"Error reading Find My data: {e}")
        return None

def get_tile_data(email: str, password: str) -> Optional[Dict[str, Any]]:
    """
    Fetch location data from Tile service
    """
    try:
        # Create a new event loop for the async call
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def fetch_tile():
            async with ClientSession() as session:
                api = await async_login(email, password, session)
                tiles = await api.async_get_tiles()
                
                for tile_uuid, tile in tiles.items():
                    tile_data = vars(tile)
                    if tile_data['_tile_data']['result']['name'] in ['Car', 'Keys']:
                        last_state = tile_data['_tile_data']['result']['last_tile_state']
                        return {
                            'latitude': last_state['latitude'],
                            'longitude': last_state['longitude'],
                            'timestamp': datetime.fromtimestamp(last_state['timestamp'] / 1000),
                            'accuracy': last_state['h_accuracy']
                        }
            return None
            
        # Run the async function in the event loop
        result = loop.run_until_complete(fetch_tile())
        loop.close()
        return result
        
    except Exception as e:
        print(f"Error fetching Tile data: {e}")
        return None

def get_car_location(location_service: str, tile_email: Optional[str] = None, tile_password: Optional[str] = None):
    """
    Extract the most recent car location from either FindMy or Tile data
    
    Args:
        location_service: Service to use ("FindMy" or "Tile")
        tile_email: Email for Tile service (required if using Tile)
        tile_password: Password for Tile service (required if using Tile)
    
    Returns:
        Dictionary containing location data or None if not found
    """
    if location_service == "FindMy":
        data = read_findmy_data()
        if not data:
            return None
        
        # Find the item named "Car"
        for item in data:
            if item.get('name') == 'Car':
                location = item.get('location')
                if location:
                    return {
                        'latitude': location['latitude'],
                        'longitude': location['longitude'],
                        'timestamp': datetime.fromtimestamp(location['timeStamp']/1000),
                        'accuracy': location['horizontalAccuracy']
                    }
    elif location_service == "Tile":
        if not tile_email or not tile_password:
            raise ValueError("Tile email and password are required when using Tile service")
            
        return get_tile_data(tile_email, tile_password)
            
    else:
        raise ValueError(f"Unsupported location service: {location_service}")
            
    return None

def get_street_cleaning_data(api_url):
    """Fetch street cleaning data from SF API"""
    try:
        response = requests.get(api_url)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching data: {e}")
        return None

def find_nearest_street_segment(lat, lon, data, max_distance_meters=50):
    """
    Find the nearest street cleaning segment to the given coordinates.
    Returns the segment data if within max_distance_meters, otherwise None.
    """
    point = Point(lon, lat)
    closest_segment = None
    min_distance = float('inf')
    closest_data = None

    for segment in data:
        try:
            coords = segment['line']['coordinates']
            line = LineString(coords)
            distance = point.distance(line) * 111000  # Approximate conversion to meters
            
            if distance < min_distance:
                min_distance = distance
                closest_segment = line
                closest_data = segment
                
        except (KeyError, ValueError) as e:
            continue

    if min_distance <= max_distance_meters:
        return {
            'segment_data': closest_data,
            'distance_meters': round(min_distance, 2)
        }
    return None

def send_mac_notification(title, message):
    """Send a notification on macOS"""
    apple_script = f'''
    display notification "{message}" with title "{title}"
    '''
    try:
        subprocess.run(['osascript', '-e', apple_script])
        return True
    except Exception as e:
        print(f"Error sending notification: {e}")
        return False

def send_email_alert(subject, body, to_email, from_email, password):
    """Send an email alert"""
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = from_email
        msg['To'] = to_email

        # Connect to Gmail's SMTP server
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(from_email, password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False
def get_next_cleaning_time(segment):
    """Calculate the next cleaning time for a street segment"""
    current_time = datetime.now()
    
    # Parse cleaning schedule
    weekday = segment['weekday'].lower()[:3]
    weekday_num = {
        'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 
        'fri': 4, 'sat': 5, 'sun': 6
    }[weekday]
    
    # Get which weeks of the month this occurs (weeks are 1-based in API)
    cleaning_weeks = [i for i in range(1, 6) if segment[f'week{i}'] == '1']
    
    # Get start hour
    start_hour = int(segment['fromhour'])
    
    # Calculate next occurrence
    current_month = current_time.month
    current_year = current_time.year
    
    # Get all possible dates for next 2 months
    possible_dates = []
    for month_offset in [0, 1]:  # Check this month and next month
        target_month = current_month + month_offset
        target_year = current_year
        if target_month > 12:
            target_month = 1
            target_year += 1
            
        # Get all dates for this weekday in the month
        c = calendar.monthcalendar(target_year, target_month)
        
        # Find all occurrences of the specified weekday
        weekday_occurrences = []
        for week_index, week in enumerate(c):
            if week[weekday_num] != 0:
                weekday_occurrences.append((week_index + 1, week[weekday_num]))
        
        # Match the occurrences with the requested cleaning weeks
        for week_num in cleaning_weeks:
            if week_num <= len(weekday_occurrences):
                # Get the actual date for this occurrence
                week_index, day_num = weekday_occurrences[week_num - 1]
                cleaning_date = datetime(
                    target_year, target_month, day_num,
                    start_hour, 0
                )
                if cleaning_date > current_time:
                    possible_dates.append(cleaning_date)
    print(f"\nDates are {possible_dates}")
    if possible_dates:
        return min(possible_dates)  # Return the nearest future date
    return None
def check_cleaning_alerts(segment):
    """Check if street cleaning is tomorrow or within the next hour"""
    next_cleaning = get_next_cleaning_time(segment)
    print(f"\nNext cleaning is {next_cleaning}")
    if not next_cleaning:
        return
    
    current_time = datetime.now()
    time_until_cleaning = next_cleaning - current_time
    
    alerts = []
    
    # Check if cleaning is tomorrow
    tomorrow = current_time + timedelta(days=1)
    if (next_cleaning.date() == tomorrow.date()):
        alerts.append({
            'type': 'tomorrow',
            'message': (f"Street cleaning tomorrow on {segment['corridor']} "
                       f"between {segment['limits']} at {segment['fromhour']}:00")
        })
    
    # Check if cleaning is within the next hour
    if timedelta(0) <= time_until_cleaning <= timedelta(hours=1):
        alerts.append({
            'type': 'hour',
            'message': (f"Street cleaning in {time_until_cleaning.seconds//60} minutes on "
                       f"{segment['corridor']} between {segment['limits']}")
        })
    
    return alerts

def monitor_street_cleaning(email_config=None, check_interval=300):
    """
    Continuously monitor street cleaning schedule
    check_interval: number of seconds between checks (default 5 minutes)
    """
    print("Starting street cleaning monitor...")
    
    while True:
        try:
            # Get car location and street cleaning info
            car_location = get_car_location("Tile", "johnathanvg@yahoo.ca", "jmkm,V96")
            if not car_location:
                print("Could not find car location")
                time.sleep(check_interval)
                continue
            
            print(f"\nCar location as of {car_location['timestamp']}:")
            print(f"Latitude: {car_location['latitude']}")
            print(f"Longitude: {car_location['longitude']}")
            print(f"Accuracy: ±{car_location['accuracy']} meters")
            
            api_url = (f"https://data.sfgov.org/resource/yhqp-riqs.json?"
                      f"$$app_token=JnG1Ym5MlXgZ6ITEyRIn78bhU&"
                      f"$where=within_circle(line,{car_location['latitude']},"
                      f"{car_location['longitude']},1000)")
            
            data = get_street_cleaning_data(api_url)
            if not data:
                print("Could not fetch street cleaning data")
                time.sleep(check_interval)
                continue
            
            result = find_nearest_street_segment(
                car_location['latitude'],
                car_location['longitude'],
                data
            )
            
            if result:
                segment = result['segment_data']
                print("\nNearest street cleaning segment:")
                print(f"Street: {segment['corridor']}")
                print(f"Between: {segment['limits']}")
                print(f"Schedule: {segment['fullname']}")
                print(f"Time: {segment['fromhour']}:00-{segment['tohour']}:00")
                print(f"Distance from car: {result['distance_meters']} meters")
                
                alerts = check_cleaning_alerts(segment)
                if alerts:
                    for alert in alerts:
                        print(f"\nALERT: {alert['message']}")
                        
                        # Send macOS notification
                        send_mac_notification(
                            "Street Cleaning Alert",
                            alert['message']
                        )
                        
                        # Send email if configured
                        if email_config:
                            send_email_alert(
                                "Street Cleaning Alert",
                                alert['message'],
                                email_config['to_email'],
                                email_config['from_email'],
                                email_config['password']
                            )
            else:
                print("\nNo nearby street cleaning segment found")
            
            # Wait before next check
            print(f"\nNext check in {check_interval//60} minutes...")
            time.sleep(check_interval)
            
        except Exception as e:
            print(f"Error in monitoring loop: {e}")
            time.sleep(check_interval)

def main():
    # Configure email (optional)
    email_config = {
        'to_email': 'johnathanvg@yahoo.ca',
        'from_email': 'vangorpjohnathan@gmail.com',
        'password': 'qffy ytyx nvlp fnqj'  # Gmail App-specific password
    }
    
    # Start monitoring
    try:
        monitor_street_cleaning(email_config)
    except KeyboardInterrupt:
        print("\nStopping street cleaning monitor...")
        sys.exit(0)

if __name__ == "__main__":
    print(f"Python version: {sys.version}")
    check_dependencies()
    main()
