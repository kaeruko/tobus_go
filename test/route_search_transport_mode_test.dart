import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/services/route_search_service.dart';
import 'package:toeigo/models/transport_scope.dart';

void main() {
  RouteSearchRequest request({bool busOnly = false, Set<String>? scope}) {
    return RouteSearchRequest(
      origin: const LatLng(35.69, 139.78),
      destination: const LatLng(35.70, 139.79),
      originName: '出発地',
      destinationName: '目的地',
      startTime: DateTime(2026, 9, 26, 10, 0),
      preference: 'shortTime',
      busOnly: busOnly,
      transportScope: scope,
    );
  }

  test('route request sends bus_only false by default', () {
    final body = request().toApiBody();
    expect(body['bus_only'], isFalse);
    expect(body['transport_scope'], ['toei_bus', 'toei_subway']);
  });

  test('route request sends bus_only true when selected', () {
    final body = request(busOnly: true).toApiBody();
    expect(body['bus_only'], isTrue);
    expect(body['transport_scope'], ['toei_bus']);
  });

  test('all seven non-empty transport combinations are serialized', () {
    final ids = TransportServiceId.all.toList();
    final seen = <String>{};
    for (var mask = 1; mask < 8; mask++) {
      final scope = <String>{
        for (var index = 0; index < ids.length; index++)
          if ((mask & (1 << index)) != 0) ids[index],
      };
      final body = request(
        busOnly:
            scope.length == 1 && scope.contains(TransportServiceId.toeiBus),
        scope: scope,
      ).toApiBody();
      seen.add((body['transport_scope'] as List).join(','));
    }
    expect(seen, hasLength(7));
  });

  test('an empty explicit scope is rejected before network access', () {
    expect(() => request(scope: const {}), throwsArgumentError);
  });
}
