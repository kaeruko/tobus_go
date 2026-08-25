# Android Google Maps API key

Android release builds must use a Google Maps key owned by the app owner, not a shared/company key.

## Google Cloud setup

Create a dedicated key for Android map rendering and restrict it to:

- API restriction: `Maps SDK for Android`
- Android application restriction:
  - package: `jp.cloxs.toeigo`
  - SHA-1: the certificate fingerprint used for the installed build

For Google Play production, add the SHA-1 shown in Play Console for the Play App Signing certificate. If you also install locally signed release builds, add the upload/release keystore SHA-1 as a separate Android app restriction entry when needed.

Do not reuse this Android key for backend Places requests. The backend uses `GOOGLE_MAPS_API_KEY` and should have its own server-side restricted key.

## Local AAB build

PowerShell:

```powershell
$env:GOOGLE_MAPS_ANDROID_API_KEY='YOUR_RESTRICTED_KEY'
.\scripts\build_aab.ps1 -City tokyo
```

The build script and Gradle release configuration fail explicitly when `GOOGLE_MAPS_ANDROID_API_KEY` is missing. The key is injected into the Android manifest at build time and is not stored in Git.

After rotating away from the previously committed key, revoke that old key in Google Cloud. Removing it from the current repository does not remove it from Git history.
