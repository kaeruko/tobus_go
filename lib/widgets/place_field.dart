import 'package:flutter/cupertino.dart';
import '../core/api_client.dart';

class PlaceField extends StatefulWidget {
  final String label;
  final void Function(double lat, double lon, String desc) onPicked;
  final String? initialText;

  const PlaceField({
    super.key,
    required this.label,
    required this.onPicked,
    this.initialText,
  });

  @override
  State<PlaceField> createState() => _PlaceFieldState();
}

class _PlaceFieldState extends State<PlaceField> {
  final _ctrl = TextEditingController();
  List<Map<String, dynamic>> _preds = [];
  bool _loading = false;
  bool _suppressChange = false;

  @override
  void initState() {
    super.initState();
    if (widget.initialText != null) {
      _ctrl.text = widget.initialText!;
    }
    _ctrl.addListener(_onChanged);
  }

  @override
  void dispose() {
    _ctrl.removeListener(_onChanged);
    _ctrl.dispose();
    super.dispose();
  }

  Future<void> _onChanged() async {
    if (_suppressChange) return; 

    final q = _ctrl.text.trim();
    if (q.isEmpty) {
      setState(() => _preds = []);
      return;
    }

    setState(() => _loading = true);
    try {
      final j = await ApiClient.get('/autocomplete', params: {'q': q});
      final raw = j['predictions'] as List? ?? const [];
      setState(() {
        _loading = false;
        _preds = raw.cast<Map<String, dynamic>>();
      });
    } catch (_) {
      setState(() {
        _loading = false;
        _preds = [];
      });
    }
  }

  Future<void> _pick(Map<String, dynamic> p) async {
    final placeId = p['place_id'] as String?;
    if (placeId == null) return;

    final j = await ApiClient.get('/details', params: {'place_id': placeId});
    final res = j['result'] as Map<String, dynamic>?;
    final loc = (res?['geometry']?['location'] as Map?) ?? {};
    final lat = (loc['lat'] as num?)?.toDouble() ?? 0;
    final lon = (loc['lng'] as num?)?.toDouble() ?? 0;
    final desc =
        p['description']?.toString() ??
        res?['name']?.toString() ??
        widget.label;

    print(
      '[DEBUG] PlaceField onPicked label=${widget.label}, placeId=$placeId, desc=$desc, lat=$lat, lon=$lon',
    );

    // ここで onChanged が走らないようにする
    _suppressChange = true;
    _ctrl.text = desc;
    _suppressChange = false;

    setState(() => _preds = []); // 候補を閉じる
    widget.onPicked(lat, lon, desc); // HomePage 側で _to.text をセット
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
        ),
        if (_loading)
          const Padding(
            padding: EdgeInsets.only(top: 6),
            child: CupertinoActivityIndicator(),
          ),
        if (_preds.isNotEmpty)
          ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: 220), // ← 高さ制限
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
                  final p = _preds[index];
                  final txt = p['description']?.toString() ?? '地点';
                  return CupertinoButton(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 12,
                      vertical: 10,
                    ),
                    alignment: Alignment.centerLeft,
                    onPressed: () => _pick(p),
                    child: Text(
                      txt,
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
