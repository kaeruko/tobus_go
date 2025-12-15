import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../core/app_clock.dart';

/// 1分ごとに現在時刻を発行するStream
Stream<DateTime> _minuteTick() async* {
  yield appClock.now();
  yield* Stream.periodic(
    // const Duration(minutes: 1),
    const Duration(seconds: 20),
    (_) => appClock.now(),
  );
}

/// 1分ごとに更新される現在時刻を提供するProvider
/// これをwatchすることで、時間経過によるスケジュール自動更新が可能になる
final minuteTickerProvider = StreamProvider<DateTime>((ref) {
  return _minuteTick();
});
