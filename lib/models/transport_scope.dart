abstract final class TransportServiceId {
  static const toeiBus = 'toei_bus';
  static const toeiSubway = 'toei_subway';
  static const tokyoMetro = 'tokyo_metro';

  static const all = {toeiBus, toeiSubway, tokyoMetro};
  static const legacyDefault = {toeiBus, toeiSubway};
}

Set<String> normalizeTransportScope(
  Set<String>? explicitScope, {
  required bool busOnly,
}) {
  final scope = explicitScope == null
      ? (busOnly
            ? <String>{TransportServiceId.toeiBus}
            : <String>{...TransportServiceId.legacyDefault})
      : <String>{...explicitScope};
  if (scope.isEmpty) {
    throw ArgumentError.value(scope, 'transportScope', 'must not be empty');
  }
  final unsupported = scope.difference(TransportServiceId.all);
  if (unsupported.isNotEmpty) {
    throw ArgumentError.value(
      unsupported,
      'transportScope',
      'contains unsupported transport identifiers',
    );
  }
  if (busOnly &&
      (scope.length != 1 || !scope.contains(TransportServiceId.toeiBus))) {
    throw ArgumentError('busOnly conflicts with transportScope');
  }
  return Set.unmodifiable(scope);
}
