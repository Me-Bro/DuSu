import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Optional release signing: create android-twa/keystore.properties (git-ignored) with
//   storeFile=..  storePassword=..  keyAlias=..  keyPassword=..
// If absent, `assembleRelease` still runs but the APK is unsigned (use debug for testing).
val keystorePropsFile = rootProject.file("keystore.properties")
val keystoreProps = Properties().apply { if (keystorePropsFile.exists()) load(keystorePropsFile.inputStream()) }

android {
    namespace = "com.dusu.app"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.dusu.app"     // distinct from com.dusu.launcher — installs side-by-side
        minSdk = 23                        // androidbrowserhelper 2.7.0 requires >=23 (was 21)
        targetSdk = 36                     // Play Store requires API 36 for new apps/updates (Aug 2026)
        versionCode = 1
        versionName = "1.0"
    }

    if (keystorePropsFile.exists()) {
        signingConfigs {
            create("release") {
                storeFile = file(keystoreProps["storeFile"] as String)
                storePassword = keystoreProps["storePassword"] as String
                keyAlias = keystoreProps["keyAlias"] as String
                keyPassword = keystoreProps["keyPassword"] as String
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            if (keystorePropsFile.exists()) signingConfig = signingConfigs.getByName("release")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    // Trusted Web Activity support: ships the LauncherActivity that renders the site
    // full-screen on the device's Chrome engine (so Web Speech STT/TTS keep working).
    // Was pinned to 2.5.0 to avoid the AGP 8.9.1 / compileSdk 36 bump 2.7.x requires —
    // but Play Store now mandates targeting API 36 for new apps regardless (Aug 2026),
    // so that's moot; upgraded to match.
    implementation("com.google.androidbrowserhelper:androidbrowserhelper:2.7.0")
    implementation("androidx.core:core-ktx:1.13.1")   // NotificationCompat for reminders
}
