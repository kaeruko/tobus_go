import UIKit
import Flutter
import GoogleMaps  // ← 追加

@main
@objc class AppDelegate: FlutterAppDelegate {
  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    // Google Maps API Key setup
    GMSServices.provideAPIKey("AIzaSyA4PyYy4K1z3SfWwyPlI2YKI7wyG-XVL6s")


    GeneratedPluginRegistrant.register(with: self)
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }
}
