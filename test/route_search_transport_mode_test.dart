import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/services/route_search_service.dart';

void main() {
  RouteSearchRequest request({bool busOnly = false}) {
    return RouteSearchRequest(
      origin: const LatLng(35.69, 139.78),
      destination: const LatLng(35.70, 139.79),
      originName: '出発地',
      destinationName: '目的地',
      startTime: DateTime(2026, 9, 26, 10, 0),
      preference: 'shortTime',
      busOnly: busOnly,
    );
  }

  test('route request sends bus_only false by default', () {
    final body = request().toApiBody();
    expect(body['bus_only'], isFalse);
  });

  test('route request sends bus_only true when selected', () {
    final body = request(busOnly: true).toApiBody();
    expect(body['bus_only'], isTrue);
  });
}
