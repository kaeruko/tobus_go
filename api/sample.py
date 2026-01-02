import requests
from google.transit import gtfs_realtime_pb2

feed = gtfs_realtime_pb2.FeedMessage()
url = "https://api-public.odpt.org/api/v4/gtfs/realtime/ToeiBus?acl:consumerKey=kxdvpjwm3ezjbaszajewpohbqokbgxnrwy7w0en0hgj1ejkmimt8pyf9zq29xilm"
data = requests.get(url).content

feed.ParseFromString(data)

for entity in feed.entity:
    if entity.HasField("vehicle"):
        v = entity.vehicle
        print(v.vehicle.id, v.position.latitude, v.position.longitude)
