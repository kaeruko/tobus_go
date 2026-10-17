"""Finite, directional surface-access review, separate from station transfers.

The first tiny reviewed area is the public waiting pavement at Nagamachi-minami
municipal bay 2, on the ward-office side of the road. It does not approve the
ward-office building centroid, the other curb, stairs or any other bay.
"""
from transit_adapters.sendai_subway import Evidence
from walking_access import ReviewedCoordinateAccessRules, ReviewedPoleAccess


# Numeric coordinate equality is not approval of a walking radius. These are
# the existing development limits; station transfer permission remains in the
# separately reviewed directed network links.
COORDINATE_ACCESS_RULES = ReviewedCoordinateAccessRules(600, .01)


def nagamachi_minami_access(network):
    version = network.free_scope.snapshot.feed_versions["sendai_bus"]
    if version != "sha256:53a08400776b3229743b24eb53566eb523b354a5b783dcfffd3e40f39258e6a2":
        raise ValueError("surface access review requires the pinned municipal feed")
    stop_id = "sendai_bus:7111_10"
    pole = network.free_scope.snapshot.stops[stop_id]
    if (pole.lat,pole.lon) != (38.224419,140.876138):
        raise ValueError("surface access pole coordinate changed")
    evidence = Evidence("https://www.kotsu.city.sendai.jp/wp-content/uploads/2026/03/r06_nagamachi_minami.jpg",
        "623fdc87e7f9180adaebf5b2417541ddf8ec8a8ab380b46ef323e0bd5ae0faf7")
    # Each direction is reviewed separately on the existing official bay map:
    # the small south-side waiting pavement adjoins bay 2, with no road crossing.
    # Coordinates are a conservative development registration to the GTFS pole;
    # times/distances are declared planning estimates, not measured survey data.
    polygon = ((38.22436,140.87611),(38.22436,140.87615),
               (38.224405,140.87615),(38.224405,140.87611))
    return (
        ReviewedPoleAccess("origin",stop_id,version,polygon,
            "西2側の市営2番待合歩道から、道路を横断せず7111_10へ。区役所建物内・他標柱は対象外",evidence,1,
            meters=8,label="長町南駅 西2側・市営2番待合歩道"),
        ReviewedPoleAccess("destination",stop_id,version,polygon,
            "7111_10から、道路を横断せず西2側の市営2番待合歩道へ。区役所建物内・他標柱は対象外",evidence,1,
            meters=8,label="長町南駅 西2側・市営2番待合歩道"),
    )
