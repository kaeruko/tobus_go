import os

import requests
from google.transit import gtfs_realtime_pb2

feed = gtfs_realtime_pb2.FeedMessage()
token = os.environ["ODPT_API_TOKEN"]
url = "https://api-public.odpt.org/api/v4/gtfs/realtime/ToeiBus"
data = requests.get(
    url,
    params={"acl:consumerKey": token},
    timeout=30,
).content

feed.ParseFromString(data)

for entity in feed.entity:
    if entity.HasField("vehicle"):
        v = entity.vehicle
        print(v.vehicle.id, v.position.latitude, v.position.longitude)
