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


## Manual GitHub Actions release (Tokyo)

The **Android Release AAB** workflow is separate from CI's validation-only
AAB job. It runs on main by manual dispatch, uses the existing Play upload
key, and does not upload to Google Play. Do not run the local release script
or another release on an unsynchronized checkout in parallel.

Create the GitHub Environment `android-release` in Settings > Environments.
Restrict deployment branches to main. Add the following environment secrets:

- `ANDROID_KEYSTORE_BASE64`: Base64 of the existing Android upload keystore
  (not a newly generated key).
- `ANDROID_STORE_PASSWORD`: existing store password.
- `ANDROID_KEY_PASSWORD`: existing key password.
- `ANDROID_KEY_ALIAS`: existing key alias.
- `GOOGLE_MAPS_ANDROID_API_KEY`: restricted Android Maps key described above.

Add environment variable `ANDROID_UPLOAD_CERT_SHA256` with the SHA-256 of
the **upload key certificate** shown in Google Play Console > App integrity
(not the Play app signing certificate). Never commit or paste secrets in chat.
On the local PC, to encode the existing keystore directly to the clipboard:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes((Resolve-Path 'PATH_TO_EXISTING_KEYSTORE').Path)) | Set-Clipboard
```

Paste only into the matching GitHub secret field, then clear the clipboard.
Keep the original upload keystore securely backed up.

Open Actions > Android Release AAB > Run workflow, select main, enter the
highest versionCode already used in Google Play across all tracks, and
acknowledge that artifacts in this public repository can be downloaded by
signed-in GitHub users. The workflow requires the next pubspec build number
to be greater than the entered value. It cannot independently query Google
Play; verify the value before dispatch. The marketing version is unchanged.

After successful tests, build and checks of the AAB signer and release
manifest, the workflow commits only the new pubspec build number to main
before publishing the AAB and checksum in Artifacts (retained for 7 days).
If main moves while building, the workflow fails rather than overwriting
other changes or publishing the AAB. Start a new run from current main.
If the artifact upload fails after the version commit, the number remains
consumed; do not roll it back. Download the ZIP from a successful run,
verify the SHA-256, then upload the AAB manually to Google Play.

The public artifact contains the distributable AAB (including the restricted
Maps key embedded in the manifest), not the keystore or signing passwords.
If public download is unacceptable, do not run this workflow; use a private
distribution channel instead. The normal CI and TestFlight workflows are
unchanged. Sync the build-number commit into local main before any later
local AAB release. Never reset or clean an in-progress local working tree.
