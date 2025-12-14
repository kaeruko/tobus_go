class AppClock {
  AppClock._internal();

  static final AppClock instance = AppClock._internal();

  Duration _offset = Duration.zero;

  Duration get offset => _offset;

  DateTime now() {
    return DateTime.now().add(_offset);
  }

  void setOffset(Duration offset) {
    _offset = offset;
  }

  void resetOffset() {
    _offset = Duration.zero;
  }
}

final appClock = AppClock.instance;
