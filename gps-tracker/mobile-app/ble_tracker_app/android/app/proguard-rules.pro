# Flutter
-keep class io.flutter.** { *; }
-keep class io.flutter.plugins.** { *; }

# Flutter references Play Core split-install for deferred components — not used in this app
-dontwarn com.google.android.play.core.splitcompat.SplitCompatApplication
-dontwarn com.google.android.play.core.splitinstall.**
-dontwarn com.google.android.play.core.tasks.**

# Google Maps
-keep class com.google.android.gms.maps.** { *; }
-keep interface com.google.android.gms.maps.** { *; }

# Google Play Services (required by Maps and location)
-keep class com.google.android.gms.** { *; }
-dontwarn com.google.android.gms.**

# flutter_blue_plus (BLE)
-keep class com.lib.flutter_blue_plus.** { *; }

# mobile_scanner / MLKit
-keep class com.google.mlkit.** { *; }
-dontwarn com.google.mlkit.**

# permission_handler
-keep class com.baseflow.permissionhandler.** { *; }

# Keep enums (commonly broken by R8)
-keepclassmembers enum * {
    public static **[] values();
    public static ** valueOf(java.lang.String);
}

# Keep Parcelables
-keep class * implements android.os.Parcelable {
    public static final android.os.Parcelable$Creator *;
}
