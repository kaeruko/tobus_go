"""Build the current typed API request in synthetic coordinate tests."""
from datetime import datetime
from zoneinfo import ZoneInfo
from route_engine import GeoPoint, RoutePreference, RouteSearchRequest, serialize_route_result


def search_coordinates(engine, *, alat, alon, blat, blon, pref, start_time, date_str=None):
    if date_str is None:
        raise ValueError('explicit fixture date required')
    preferences={'time':RoutePreference.FASTEST,'fewTransfers':RoutePreference.FEWEST_TRANSFERS}
    if pref not in preferences:
        raise ValueError('unsupported v2 fixture preference')
    request=RouteSearchRequest(GeoPoint(alat,alon),GeoPoint(blat,blon),
        datetime.fromisoformat(date_str+'T'+start_time).replace(tzinfo=ZoneInfo('Asia/Tokyo')),
        preferences[pref])
    return serialize_route_result(engine.search(request))
