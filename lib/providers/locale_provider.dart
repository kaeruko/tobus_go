import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Presentation-only preference: transit requests and caches stay language-neutral.
final localeProvider = AsyncNotifierProvider<LocaleNotifier, Locale?>(
  LocaleNotifier.new,
);

class LocaleNotifier extends AsyncNotifier<Locale?> {
  static const preferenceKey = 'app_language';
  static const supportedLanguageCodes = {'ja', 'en', 'zh'};

  @override
  Future<Locale?> build() async {
    final prefs = await SharedPreferences.getInstance();
    final code = prefs.getString(preferenceKey);
    return supportedLanguageCodes.contains(code) ? Locale(code!) : null;
  }

  Future<void> setLocale(Locale? locale) async {
    if (locale != null &&
        !supportedLanguageCodes.contains(locale.languageCode)) {
      throw ArgumentError.value(locale, 'locale', 'Unsupported app language');
    }
    await future;
    final prefs = await SharedPreferences.getInstance();
    final saved = locale == null
        ? await prefs.remove(preferenceKey)
        : await prefs.setString(preferenceKey, locale.languageCode);
    if (!saved) throw StateError('Language preference was not saved');
    state = AsyncData(locale == null ? null : Locale(locale.languageCode));
  }
}
