package com.qvyshift.translate;

import android.app.*;
import android.content.Context;
import android.content.SharedPreferences;
import android.net.ConnectivityManager;
import android.net.NetworkInfo;
import android.os.Build;
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

  /* Version fra http://developer.android.com/training/basics/network-ops/managing.html */
  public static boolean isOnline() {
    ConnectivityManager connMgr = (ConnectivityManager) instance.getSystemService(Context.CONNECTIVITY_SERVICE);
    NetworkInfo networkInfo = connMgr.getActiveNetworkInfo();
    return (networkInfo != null && networkInfo.isConnected());
  }
}
