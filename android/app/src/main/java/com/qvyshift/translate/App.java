package com.qvyshift.translate;

import android.app.*;
import android.content.SharedPreferences;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.preference.PreferenceManager;
import android.util.Log;
import android.widget.Toast;

import java.io.File;

public class App extends Application {
  public static boolean isSdk() {
    return Build.PRODUCT.contains("sdk");//.equals(Build.PRODUCT) || "google_sdk".equals(Build.PRODUCT);
  }
  public static App instance;
  public static Handler handler;
  public static SharedPreferences prefs;

  public static final String PREF_lastModeTitle = "lastModeTitle";
  public static final String PREF_displayMark = "displayMark";

  public static void reportError(Exception ex) {
    ex.printStackTrace();
    longToast("Error: " + ex);
    longToast("The error will be reported to the developers. sorry for the inconvenience.");
  }

  public static ApertiumInstallation apertiumInstallation;
  public static PairDownloadManager pairDownloadManager;

  @Override
  public void onCreate() {
    super.onCreate();
    prefs = PreferenceManager.getDefaultSharedPreferences(this);
    instance = this;
    handler = new Handler();

    // The '2' suffix is legacy — users may already have pairs installed under this path.
    File packagesDir = new File(getFilesDir(), "packages2");
    apertiumInstallation = new ApertiumInstallation(packagesDir);
    apertiumInstallation.rescanForPackages();

    pairDownloadManager = new PairDownloadManager(this, packagesDir);
    // Some packs may already be delivered from a prior session (Play keeps them cached
    // across reinstalls). Pull them into the installation dir before we show any UI.
    if (pairDownloadManager.installAlreadyDelivered()) {
      apertiumInstallation.rescanForPackages();
    }
    // Any pair extracted under an older app versionCode gets a silent Play fetch +
    // re-extract. No blocking — UI keeps showing the pair as installed throughout
    // and auto-upgrades when the fetch's state listener fires COMPLETED.
    pairDownloadManager.refreshStalePacks();

    // Start the Play Billing connection and the price lookup as soon as the first screen is up,
    // so the dialog can show "Donate • <Play's localized price>" from its first frame. Not right
    // here: on Android 14 the connection never completes when started from Application.onCreate
    // until an activity makes a billing call (seen with billing 9.1.0 in Loyalty Card Wallet).
    registerActivityLifecycleCallbacks(new ActivityLifecycleCallbacks() {
      @Override public void onActivityResumed(Activity activity) {
        unregisterActivityLifecycleCallbacks(this);
        SupportPurchase.get(App.this);
      }
      @Override public void onActivityCreated(Activity activity, Bundle savedInstanceState) {}
      @Override public void onActivityStarted(Activity activity) {}
      @Override public void onActivityPaused(Activity activity) {}
      @Override public void onActivityStopped(Activity activity) {}
      @Override public void onActivitySaveInstanceState(Activity activity, Bundle outState) {}
      @Override public void onActivityDestroyed(Activity activity) {}
    });
  }

  public static void longToast(final String txt) {
    Log.d("TAG", txt);
    handler.post(new Runnable() {
      @Override
      public void run() {
        Toast.makeText(instance, txt, Toast.LENGTH_LONG).show();
      }
    });
  }
}
