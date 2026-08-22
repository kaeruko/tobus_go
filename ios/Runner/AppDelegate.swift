import UIKit
import Flutter
import GoogleMaps
import Firebase

@main
@objc class AppDelegate: FlutterAppDelegate {
  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {

    FirebaseApp.configure()

    guard
      let rawMapsApiKey = Bundle.main.object(forInfoDictionaryKey: "GoogleMapsApiKey") as? String
    else {
      fatalError("GoogleMapsApiKey is missing from Info.plist")
    }

    let mapsApiKey = rawMapsApiKey.trimmingCharacters(in: .whitespacesAndNewlines)
    guard
      !mapsApiKey.isEmpty,
      mapsApiKey != "$(GOOGLE_MAPS_IOS_API_KEY)"
    else {
      fatalError("GOOGLE_MAPS_IOS_API_KEY is not configured")
    }

    GMSServices.provideAPIKey(mapsApiKey)

    GeneratedPluginRegistrant.register(with: self)
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }
}
