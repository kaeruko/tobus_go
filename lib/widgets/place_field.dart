import 'package:flutter/cupertino.dart';
import '../core/api_client.dart';

class PlaceField extends StatefulWidget {
  final String label;
  final String value;
  final void Function(String value, String desc) onChanged;

  const PlaceField({
    super.key,
    required this.label,
    required this.value,
    required this.onChanged,
  });

  @override
  State<PlaceField> createState() => _PlaceFieldState();
}

class _PlaceFieldState extends State<PlaceField> {
  late TextEditingController _ctrl;
  List<Map<String, dynamic>> _preds = [];
  bool _loading = false;
  
  @override
  void initState() {
    super.initState();
    _ctrl = TextEditingController(text: widget.value);
    _ctrl.addListener(_onInputChanged);
  }

  @override
  void didUpdateWidget(PlaceField oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.value != _ctrl.text) {
      // External change (e.g. swap), update text and keep selection if possible
      // Note: This might reset cursor position, but acceptable for now.
      _ctrl.text = widget.value;
    }
  }

  @override
  void dispose() {
    _ctrl.removeListener(_onInputChanged);
    _ctrl.dispose();
    super.dispose();
  }

  Future<void> _onInputChanged() async {
    final text = _ctrl.text;
    
    // Notify parent immediately of raw text change (so they can enable search button etc)
    // We pass empty desc for raw input
    // NOTE: If we want to strictly follow "onChanged triggers search", 
    // we might want to debounce or only trigger on selection.
    // But user plan says "onChanged で文字列をそのまま返す".
    // We should allow typing free text.
    // However, to avoid spamming the parent's setter (and re-render loops), 
    // usually we only call onChanged when helpful.
    // But for a controlled component, we MUST call onChanged to update the state.
    // Wait, if we call onChanged, parent updates state, which passes back new value, 
    // which updates _ctrl.text.
    // To avoid cursor jumping, we only update _ctrl.text in didUpdateWidget if it differs effectively.
    
    // For now, let's just implement the autocomplete logic here.
    // We will call widget.onChanged only when user "commits" or types?
    // User instruction: "onChanged で文字列をそのまま返す"
    // So yes, sync content.
    if (widget.value != text) {
        widget.onChanged(text, ''); 
    }

    final q = text.trim();
    if (q.isEmpty) {
      if (mounted) setState(() => _preds = []);
      return;
    }

    // Debounce or just load?
    // For simplicity, just load.
    if (mounted) setState(() => _loading = true);
    try {
      final j = await ApiClient.get('/autocomplete', params: {'q': q});
      final raw = j['predictions'] as List? ?? const [];
      if (mounted) {
        setState(() {
            _loading = false;
            _preds = raw.cast<Map<String, dynamic>>();
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
            _loading = false;
            _preds = [];
        });
      }
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
    
    final name = p['description']?.toString() ?? res?['name']?.toString() ?? '';
    
    // "35.6812,139.7671"
    final val = '$lat,$lon';
    
    setState(() => _preds = []);
    
    // Update text to value (coordinates) because "Destruction is fine"
    // Ideally we'd show `name` but store `val`. 
    // But complying with "Stateless/Single Source of Truth", we show what's in state.
    _ctrl.text = val; 
    
    widget.onChanged(val, name);
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
          // clearButtonMode: OverlayVisibilityMode.editing, 
        ),
        if (_loading)
          const Padding(
            padding: EdgeInsets.only(top: 6),
            child: CupertinoActivityIndicator(),
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
