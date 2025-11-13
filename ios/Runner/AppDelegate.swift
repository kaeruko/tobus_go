import UIKit
import Flutter
import GoogleMaps  // ← 追加

@main
@objc class AppDelegate: FlutterAppDelegate {
  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    // Info.plist の GMSApiKey を読み出して Maps SDK に渡す
    if let key = Bundle.main.object(forInfoDictionaryKey: "GMSApiKey") as? String {
      GMSServices.provideAPIKey(key)
      print("### GMSApiKey prefix=\(key.prefix(7))  bundle=\(Bundle.main.bundleIdentifier ?? "?")")
    } else {
      fatalError("GMSApiKey not found in Info.plist")
    }

    GeneratedPluginRegistrant.register(with: self)
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }
}
