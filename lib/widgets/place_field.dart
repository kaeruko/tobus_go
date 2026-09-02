import 'dart:async';

import 'package:flutter/cupertino.dart';

import '../core/api_client.dart';

class PlaceField extends StatefulWidget {
  final String label;
  final String value;
  final String displayValue;
  final void Function(String value, String desc) onChanged;
  final VoidCallback? onCurrentLocationPressed;

  const PlaceField({
    super.key,
    required this.label,
    required this.value,
    required this.displayValue,
    required this.onChanged,
    this.onCurrentLocationPressed,
  });

  @override
  State<PlaceField> createState() => _PlaceFieldState();
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

    if (query.isEmpty) return;

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
      final json = await ApiClient.get('/autocomplete', params: {'q': query});
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
        _errorMessage = '場所候補を取得できませんでした: $error';
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
        _errorMessage = '場所候補に place_id がありません';
      });
      return;
    }

    setState(() {
      _loading = true;
      _errorMessage = null;
    });

    try {
      final json = await ApiClient.get(
        '/details',
        params: {'place_id': placeId},
      );
      final result = json['result'];
      if (result is! Map) {
        throw StateError('Place details response is missing result object');
      }
      final geometry = result['geometry'];
      if (geometry is! Map) {
        throw StateError('Place details response is missing geometry object');
      }
      final location = geometry['location'];
      if (location is! Map) {
        throw StateError('Place details response is missing location object');
      }

      final latValue = location['lat'];
      final lonValue = location['lng'];
      if (latValue is! num || lonValue is! num) {
        throw StateError('Place details response has non-numeric coordinates');
      }
      final lat = latValue.toDouble();
      final lon = lonValue.toDouble();
      if (!lat.isFinite || !lon.isFinite) {
        throw StateError('Place details response has non-finite coordinates');
      }
      if (lat < -90 || lat > 90 || lon < -180 || lon > 180) {
        throw RangeError('Place details response has out-of-range coordinates: $lat,$lon');
      }

      final predictionName = prediction['description']?.toString().trim();
      final detailName = result['name']?.toString().trim();
      final name = (predictionName != null && predictionName.isNotEmpty)
          ? predictionName
          : detailName;
      if (name == null || name.isEmpty) {
        throw StateError('Place details response is missing a display name');
      }

      if (!mounted || generation != _inputGeneration) return;

      _isSyncing = true;
      try {
        _ctrl.text = name;
      } finally {
        _isSyncing = false;
      }

      setState(() {
        _loading = false;
        _preds = [];
        _errorMessage = null;
      });
      widget.onChanged('$lat,$lon', name);
    } catch (error) {
      if (!mounted || generation != _inputGeneration) return;
      setState(() {
        _loading = false;
        _preds = [];
        _errorMessage = '場所の座標を取得できませんでした: $error';
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
          placeholder: '場所名・住所で検索',
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
                  final text = prediction['description']?.toString() ?? '地点';
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
