import os
from dotenv import load_dotenv

load_dotenv()
PLACES_KEY = os.getenv("PLACES_KEY", "")
BASE_URL = "https://maps.googleapis.com/maps/api/place"
