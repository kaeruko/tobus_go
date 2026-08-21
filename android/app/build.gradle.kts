import java.util.Properties

plugins {
    id("com.android.application")
    // Tokyo still uses the existing Firebase project. Route-only flavors have
    // their Google Services processing disabled below and never fall back to it.
    id("com.google.gms.google-services")
    id("kotlin-android")
    id("dev.flutter.flutter-gradle-plugin")
}

val keystoreProperties = Properties()
val keystorePropertiesFile = rootProject.file("key.properties")
val hasReleaseSigning = keystorePropertiesFile.exists()
if (hasReleaseSigning) {
    keystoreProperties.load(keystorePropertiesFile.inputStream())
}

fun requiredSigningProperty(name: String): String {
    return keystoreProperties.getProperty(name)
        ?: throw GradleException("android/key.properties is missing required key: $name")
}

android {
    namespace = "jp.cloxs.toeigo"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_11.toString()
    }

    defaultConfig {
        // Keep the published Tokyo identifier unchanged.
        applicationId = "jp.cloxs.toeigo"
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    flavorDimensions += "city"
    productFlavors {
        create("tokyo") {
            dimension = "city"
            applicationId = "jp.cloxs.toeigo"
            resValue("string", "app_name", "都営でGO")
        }
        create("nagoya") {
            dimension = "city"
            applicationId = "jp.cloxs.nagoyago"
            resValue("string", "app_name", "名古屋でGO")
        }
        create("sendai") {
            dimension = "city"
            applicationId = "jp.cloxs.sendaigo"
            resValue("string", "app_name", "仙台でGO")
        }
    }

    signingConfigs {
        if (hasReleaseSigning) {
            create("release") {
                keyAlias = requiredSigningProperty("keyAlias")
                keyPassword = requiredSigningProperty("keyPassword")
                storeFile = file(requiredSigningProperty("storeFile"))
                storePassword = requiredSigningProperty("storePassword")
            }
        }
    }

    buildTypes {
        release {
            if (hasReleaseSigning) {
                signingConfig = signingConfigs.getByName("release")
            }
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }
}

// The repository currently contains only the existing Tokyo Firebase native
// configuration. Nagoya/Sendai are route-only and Firebase is disabled in
// CityProfile, so do not run Google Services for those variants. When a city
// later gets its own Firebase app, add a flavor-specific google-services.json
// and remove that flavor from this guard in the same change.
tasks.configureEach {
    val isRouteOnlyGoogleServicesTask =
        (name.startsWith("processNagoya") || name.startsWith("processSendai")) &&
            name.endsWith("GoogleServices")
    if (isRouteOnlyGoogleServicesTask) {
        enabled = false
    }
}

// Debug flavor builds must work without release keys, but a release artifact
// must never be emitted unsigned by accident.
gradle.taskGraph.whenReady {
    if (!hasReleaseSigning) {
        val requestedReleaseArtifact = allTasks.any { task ->
            val taskName = task.name
            (taskName.startsWith("bundle") || taskName.startsWith("assemble")) &&
                taskName.endsWith("Release")
        }
        if (requestedReleaseArtifact) {
            throw GradleException(
                "Release signing is required. android/key.properties was not found.",
            )
        }
    }
}

flutter {
    source = "../.."
}
