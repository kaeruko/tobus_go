import 'dart:async';

import 'package:flutter/cupertino.dart';

import '../core/api_client.dart';
import '../l10n/app_localizations.dart';

class PlaceField extends StatefulWidget {
  final String label;
  final String value;
  final String displayValue;
  final void Function(String value, String desc) onChanged;
  final void Function(
    String value,
    String desc,
    String nameJa,
    String nameEn,
  )? onResolved;
  final VoidCallback? onCurrentLocationPressed;

  const PlaceField({
    super.key,
    required this.label,
    required this.value,
    required this.displayValue,
    required this.onChanged,
    this.onResolved,
    this.onCurrentLocationPressed,
  });

  @override
  State<PlaceField> createState() => _PlaceFieldState();
}

class _ResolvedPlaceDetail {
  final String name;
  final String? formattedAddress;
  final double lat;
  final double lon;

  const _ResolvedPlaceDetail({
    required this.name,
    required this.formattedAddress,
    required this.lat,
    required this.lon,
  });
}

bool _isGenericJapaneseAddressFragment(String value) {
  final normalized = value.trim();
  return RegExp(
    r'^[0-9０-９一二三四五六七八九十百]+丁目$',
  ).hasMatch(normalized) ||
      RegExp(
        r'^[0-9０-９一二三四五六七八九十百]+番(?:地)?$',
      ).hasMatch(normalized) ||
      RegExp(
        r'^[0-9０-９一二三四五六七八九十百]+号$',
      ).hasMatch(normalized) ||
      RegExp(
        r'^[0-9０-９]+(?:[-‐‑–—−][0-9０-９]+){1,2}$',
      ).hasMatch(normalized);
}

String _shortJapaneseAddress(String formattedAddress) {
  var normalized = formattedAddress.trim();
  normalized = normalized.replaceFirst(
    RegExp(r'^日本[、,]?\s*'),
    '',
  );
  normalized = normalized.replaceFirst(
    RegExp(r'^〒?\s*[0-9０-９]{3}[-‐‑–—−]?[0-9０-９]{4}\s*'),
    '',
  );

  final cityWard = RegExp(
    r'^.*?市.*?区(.+?[0-9０-９一二三四五六七八九十百]+丁目)',
  ).firstMatch(normalized);
  if (cityWard != null) {
    return cityWard.group(1)!.trim();
  }

  final districtTown = RegExp(
    r'^.*?郡.*?[町村](.+?[0-9０-９一二三四五六七八九十百]+丁目)',
  ).firstMatch(normalized);
  if (districtTown != null) {
    return districtTown.group(1)!.trim();
  }

  final municipality = RegExp(
    r'^.*?[市区](.+?[0-9０-９一二三四五六七八九十百]+丁目)',
  ).firstMatch(normalized);
  if (municipality != null) {
    return municipality.group(1)!.trim();
  }

  throw StateError(
    'Generic Japanese address name could not be expanded from '
    'formatted_address: $formattedAddress',
  );
}

String _resolvedPlaceName(
  _ResolvedPlaceDetail detail, {
  required String language,
}) {
  if (language != 'ja' || !_isGenericJapaneseAddressFragment(detail.name)) {
    return detail.name;
  }

  final formattedAddress = detail.formattedAddress?.trim();
  if (formattedAddress == null || formattedAddress.isEmpty) {
    throw StateError(
      'Generic Japanese address name requires formatted_address: '
      'name=${detail.name}',
    );
  }
  return _shortJapaneseAddress(formattedAddress);
}

_ResolvedPlaceDetail _parsePlaceDetail(
  Map<String, dynamic> json, {
  required String language,
}) {
  final result = json['result'];
  if (result is! Map) {
    throw StateError(
      'Place details response is missing result object: language=$language',
    );
  }
  final name = result['name']?.toString().trim();
  if (name == null || name.isEmpty) {
    throw StateError(
      'Place details response is missing a display name: language=$language',
    );
  }
  final formattedAddress = result['formatted_address']?.toString().trim();
  final geometry = result['geometry'];
  if (geometry is! Map) {
    throw StateError(
      'Place details response is missing geometry object: language=$language',
    );
  }
  final location = geometry['location'];
  if (location is! Map) {
    throw StateError(
      'Place details response is missing location object: language=$language',
    );
  }
  final latValue = location['lat'];
  final lonValue = location['lng'];
  if (latValue is! num || lonValue is! num) {
    throw StateError(
      'Place details response has non-numeric coordinates: language=$language',
    );
  }
  final lat = latValue.toDouble();
  final lon = lonValue.toDouble();
  if (!lat.isFinite || !lon.isFinite) {
    throw StateError(
      'Place details response has non-finite coordinates: language=$language',
    );
  }
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) {
    throw RangeError(
      'Place details response has out-of-range coordinates: '
      'language=$language $lat,$lon',
    );
  }
  return _ResolvedPlaceDetail(
    name: name,
    formattedAddress:
        formattedAddress == null || formattedAddress.isEmpty
            ? null
            : formattedAddress,
    lat: lat,
    lon: lon,
  );
}

class _PlaceFieldState extends State<PlaceField> {
  static const _autocompleteDebounce = Duration(milliseconds: 300);

  late final TextEditingController _ctrl;
  Timer? _autocompleteTimer;
  List<Map<String, dynamic>> _preds = [];
  bool _loading = false;
  bool _isSyncing = false;
  String? _errorMessage;
  int _inputGeneration = 0;
  String? _lastLocaleCode;

  String _placeLanguageCode() {
    final languageCode = Localizations.localeOf(context).languageCode;
    switch (languageCode) {
      case 'ja':
      case 'en':
        return languageCode;
      case 'zh':
        // Reuse the same official English/Japanese place data in Chinese UI.
        return 'en';
      default:
        throw StateError(
          'Unsupported place-search language: $languageCode',
        );
    }
  }

  @override
  void initState() {
    super.initState();
    _ctrl = TextEditingController(text: widget.displayValue);
    _ctrl.addListener(_onInputChanged);
    unawaited(_primeBackend());
  }

  Future<void> _primeBackend() async {
    try {
      await ApiClient.warmUp();
    } catch (error, stackTrace) {
      debugPrint('[PlaceField] backend warmup failed: $error');
      debugPrintStack(stackTrace: stackTrace);
    }
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final code = Localizations.localeOf(context).languageCode;
    if (_lastLocaleCode != null && _lastLocaleCode != code) {
      _autocompleteTimer?.cancel();
      ++_inputGeneration;
      _preds = [];
      _loading = false;
      _errorMessage = null;
    }
    _lastLocaleCode = code;
  }

  @override
  void didUpdateWidget(PlaceField oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.displayValue == _ctrl.text) return;

    _isSyncing = true;
    try {
      _ctrl.text = widget.displayValue;
    } finally {
      _isSyncing = false;
    }
  }

  @override
  void dispose() {
    _autocompleteTimer?.cancel();
    _ctrl.removeListener(_onInputChanged);
    _ctrl.dispose();
    super.dispose();
  }

  void _onInputChanged() {
    if (_isSyncing) return;

    final text = _ctrl.text;
    final query = text.trim();
    final generation = ++_inputGeneration;
    _autocompleteTimer?.cancel();

    // Raw text is only a display/query value. It is not a route coordinate until
    // the user selects one autocomplete result and /details resolves it.
    widget.onChanged('', text);

    if (mounted) {
      setState(() {
        _loading = false;
        _preds = [];
        _errorMessage = null;
      });
    }

    // Wait for IME confirmation; pinyin/kana composition is not a search yet.
    if (query.isEmpty || !_ctrl.value.composing.isCollapsed) return;

    _autocompleteTimer = Timer(
      _autocompleteDebounce,
      () => _loadPredictions(query, generation),
    );
  }

  Future<void> _loadPredictions(String query, int generation) async {
    if (!mounted || generation != _inputGeneration) return;

    setState(() {
      _loading = true;
      _errorMessage = null;
    });

    try {
      // If the user starts typing before startup warmup finishes, wait for the
      // same request instead of racing autocomplete against another cold start.
      await ApiClient.warmUp();
      if (!mounted || generation != _inputGeneration) return;
      final json = await ApiClient.get(
        '/autocomplete',
        params: {
          'q': query,
          'lang': _placeLanguageCode(),
        },
      );
      final raw = json['predictions'];
      if (raw is! List) {
        throw StateError('Autocomplete response is missing predictions list');
      }

      final predictions = raw.map<Map<String, dynamic>>((entry) {
        if (entry is! Map) {
          throw StateError('Autocomplete prediction is not an object: $entry');
        }
        return Map<String, dynamic>.from(entry);
      }).toList(growable: false);

      if (!mounted || generation != _inputGeneration) return;
      setState(() {
        _loading = false;
        _preds = predictions;
      });
    } catch (error) {
      if (!mounted || generation != _inputGeneration) return;
      setState(() {
        _loading = false;
        _preds = [];
        _errorMessage = AppLocalizations.of(context).placeSuggestionsFailed(
          error.toString(),
        );
      });
    }
  }

  Future<void> _pick(Map<String, dynamic> prediction) async {
    _autocompleteTimer?.cancel();
    final generation = ++_inputGeneration;

    final placeId = prediction['place_id'];
    if (placeId is! String || placeId.trim().isEmpty) {
      setState(() {
        _preds = [];
        _errorMessage = AppLocalizations.of(context).placeMissingId;
      });
      return;
    }

    setState(() {
      _loading = true;
      _errorMessage = null;
    });

    try {
      final detailResponses = await Future.wait([
        ApiClient.get(
          '/details',
          params: {
            'place_id': placeId,
            'lang': 'ja',
          },
        ),
        ApiClient.get(
          '/details',
          params: {
            'place_id': placeId,
            'lang': 'en',
          },
        ),
      ]);
      final japanese = _parsePlaceDetail(detailResponses[0], language: 'ja');
      final english = _parsePlaceDetail(detailResponses[1], language: 'en');

      if ((japanese.lat - english.lat).abs() > 0.0000001 ||
          (japanese.lon - english.lon).abs() > 0.0000001) {
        throw StateError(
          'Japanese/English place details coordinates disagree: '
          'ja=${japanese.lat},${japanese.lon} '
          'en=${english.lat},${english.lon}',
        );
      }

      final resolvedNameJa = _resolvedPlaceName(
        japanese,
        language: 'ja',
      );
      final resolvedNameEn = _resolvedPlaceName(
        english,
        language: 'en',
      );
      if (!mounted || generation != _inputGeneration) return;
      final displayName = _placeLanguageCode() == 'en'
          ? resolvedNameEn
          : resolvedNameJa;

      if (!mounted || generation != _inputGeneration) return;

      _isSyncing = true;
      try {
        _ctrl.text = displayName;
      } finally {
        _isSyncing = false;
      }

      setState(() {
        _loading = false;
        _preds = [];
        _errorMessage = null;
      });
      final value = '${japanese.lat},${japanese.lon}';
      final resolved = widget.onResolved;
      if (resolved != null) {
        resolved(value, displayName, resolvedNameJa, resolvedNameEn);
      } else {
        widget.onChanged(value, displayName);
      }
    } catch (error) {
      if (!mounted || generation != _inputGeneration) return;
      setState(() {
        _loading = false;
        _preds = [];
        _errorMessage = AppLocalizations.of(context).placeCoordinatesFailed(
          error.toString(),
        );
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(left: 4, bottom: 6),
          child: Text(
            widget.label,
            style: const TextStyle(
              color: CupertinoColors.inactiveGray,
              fontSize: 12,
            ),
          ),
        ),
        CupertinoTextField(
          controller: _ctrl,
          placeholder: AppLocalizations.of(context).placeSearchPlaceholder,
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          suffix: widget.onCurrentLocationPressed != null
              ? CupertinoButton(
                  padding: EdgeInsets.zero,
                  onPressed: widget.onCurrentLocationPressed,
                  child: const Icon(CupertinoIcons.location_fill),
                )
              : null,
          suffixMode: OverlayVisibilityMode.always,
        ),
        if (_loading)
          const Padding(
            padding: EdgeInsets.only(top: 6),
            child: CupertinoActivityIndicator(),
          ),
        if (_errorMessage != null)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(
              _errorMessage!,
              style: const TextStyle(
                color: CupertinoColors.systemRed,
                fontSize: 12,
              ),
            ),
          ),
        if (_preds.isNotEmpty)
          ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: 220),
            child: Container(
              margin: const EdgeInsets.only(top: 6),
              decoration: BoxDecoration(
                color: CupertinoColors.systemGrey6,
                borderRadius: BorderRadius.circular(8),
              ),
              child: ListView.builder(
                padding: EdgeInsets.zero,
                itemCount: _preds.length > 6 ? 6 : _preds.length,
                itemBuilder: (context, index) {
                  final prediction = _preds[index];
                  final text = prediction['description']?.toString() ??
                      AppLocalizations.of(context).unnamedPlace;
                  return CupertinoButton(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 12,
                      vertical: 10,
                    ),
                    alignment: Alignment.centerLeft,
                    onPressed: () => _pick(prediction),
                    child: Text(
                      text,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                  );
                },
              ),
            ),
          ),
      ],
    );
  }
}
