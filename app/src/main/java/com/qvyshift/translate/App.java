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
import com.google.android.play.core.assetpacks.AssetPackLocation;
import com.google.android.play.core.assetpacks.AssetPackManager;
import com.google.android.play.core.assetpacks.AssetPackManagerFactory;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;

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
    //BugSenseHandler.sendException(ex);
  }
  public static ApertiumInstallation apertiumInstallation;

  @Override
  public void onCreate() {
    super.onCreate();
    prefs = PreferenceManager.getDefaultSharedPreferences(this);

    // If you want to use BugSense for your fork, register with
    // them and place your own API key in /assets/bugsense.txt
    /*
    if (!BuildConfig.DEBUG) try {
      byte[] buffer = new byte[16];
      int n = getAssets().open("bugsense.txt").read(buffer);
      String key = new String(buffer, 0, n).trim();

      Log.d("TAG", "Using bugsense key '" + key + "'");
      BugSenseHandler.initAndStartSession(this, key);
    } catch (IOException e) {
      Log.d("TAG", "No bugsense keyfile found");
    }*/

    instance = this;
    handler = new Handler();

    // The '2' suffix is legacy — users may already have pairs installed under this path.
    File packagesDir = new File(getFilesDir(), "packages2");
    apertiumInstallation = new ApertiumInstallation(packagesDir);
    apertiumInstallation.rescanForPackages();
    installBundledPairs(packagesDir);
    installFromAssetPacks(packagesDir);
  }

  private void installFromAssetPacks(File packagesDir) {
    AssetPackManager apm = AssetPackManagerFactory.getInstance(this);
    boolean installedAny = false;
    for (PairCatalog.Pair p : PairCatalog.ENABLED) {
      if (new File(packagesDir, p.pkg).isDirectory()) continue;
      String packName = PairCatalog.packNameFor(p);
      AssetPackLocation loc = apm.getPackLocation(packName);
      if (loc == null || loc.assetsPath() == null) continue;
      File jar = new File(loc.assetsPath(), "pairs/" + p.pkg + ".jar");
      if (!jar.exists()) {
        Log.w("TAG", "Pack " + packName + " delivered but JAR missing: " + jar);
        continue;
      }
      try {
        apertiumInstallation.installJar(jar, p.pkg);
        installedAny = true;
        Log.i("TAG", "Installed pair " + p.pkg + " from pack " + packName);
      } catch (IOException e) {
        Log.e("TAG", "Failed installing pair " + p.pkg, e);
      }
    }
    if (installedAny) apertiumInstallation.rescanForPackages();
  }

  private static final String BUNDLED_PAIRS_DIR = "pairs";

  private void installBundledPairs(File packagesDir) {
    String[] bundled;
    try {
      bundled = getAssets().list(BUNDLED_PAIRS_DIR);
    } catch (IOException e) {
      Log.e("TAG", "Failed to list bundled pair assets", e);
      return;
    }
    if (bundled == null || bundled.length == 0) return;

    boolean installedAny = false;
    for (String assetName : bundled) {
      if (!assetName.endsWith(".jar")) continue;
      String pkg = assetName.substring(0, assetName.length() - 4);
      if (new File(packagesDir, pkg).isDirectory()) continue;

      File tmpJar = new File(getCacheDir(), pkg + ".jar");
      try (InputStream in = getAssets().open(BUNDLED_PAIRS_DIR + "/" + assetName);
           FileOutputStream out = new FileOutputStream(tmpJar)) {
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) != -1) out.write(buf, 0, n);
      } catch (IOException e) {
        Log.e("TAG", "Failed to extract bundled pair " + assetName, e);
        continue;
      }
      try {
        apertiumInstallation.installJar(tmpJar, pkg);
        installedAny = true;
        Log.i("TAG", "Installed bundled pair " + pkg);
      } catch (IOException e) {
        Log.e("TAG", "Failed to install bundled pair " + pkg, e);
      } finally {
        tmpJar.delete();
      }
    }
    if (installedAny) apertiumInstallation.rescanForPackages();
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
