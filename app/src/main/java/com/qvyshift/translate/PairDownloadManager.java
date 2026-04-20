package com.qvyshift.translate;

import android.content.Context;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.os.Build;
import android.util.Log;

import com.google.android.play.core.assetpacks.AssetPackLocation;
import com.google.android.play.core.assetpacks.AssetPackManager;
import com.google.android.play.core.assetpacks.AssetPackManagerFactory;
import com.google.android.play.core.assetpacks.AssetPackState;
import com.google.android.play.core.assetpacks.AssetPackStateUpdateListener;
import com.google.android.play.core.assetpacks.model.AssetPackStatus;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;

/**
 * Thin wrapper around {@link AssetPackManager} that fetches per-pair on-demand asset
 * packs and unpacks their shipped {@code apertium-<pair>.jar} into the app's
 * installation dir so {@link ApertiumInstallation} can see them. A single Play Core
 * listener is registered once; individual download requests attach a {@link Listener}
 * that gets progress, completion, and failure callbacks on the main thread.
 *
 * <p><b>Update semantics:</b> every install writes a {@code <pkg>.version} sidecar
 * recording the app versionCode at install time. On startup {@link #refreshStalePacks}
 * silently re-fetches any pack whose marker doesn't match the current app version,
 * so pair content tracks app updates without user intervention.
 */
public class PairDownloadManager {
  private static final String TAG = "PairDownload";

  public interface Listener {
    void onProgress(int percent, long bytesSoFar, long totalBytes);
    void onReady();
    void onFailed(int errorCode);
    void onCancelled();
  }

  private final Context ctx;
  private final AssetPackManager apm;
  private final File packagesDir;
  private final int currentAppVersion;
  private final Map<String, Listener> listenersByPack = new HashMap<>();

  public PairDownloadManager(Context ctx, File packagesDir) {
    this.ctx = ctx.getApplicationContext();
    this.packagesDir = packagesDir;
    this.currentAppVersion = readAppVersionCode(this.ctx);
    this.apm = AssetPackManagerFactory.getInstance(this.ctx);
    this.apm.registerListener(stateListener);
  }

  /**
   * Walk enabled pairs and, for any pack already delivered on disk that hasn't been
   * extracted yet (fresh install, or reinstall with Play-cached packs), unpack its
   * JAR into {@link ApertiumInstallation}. Runs on the caller's thread; fast — no
   * network. Stale packs (extracted under an older app version) are left alone
   * here — {@link #refreshStalePacks} handles them asynchronously.
   */
  public boolean installAlreadyDelivered() {
    boolean installedAny = false;
    for (PairCatalog.Pair p : PairCatalog.ENABLED) {
      if (new File(packagesDir, p.pkg).isDirectory()) continue;
      if (installIfDelivered(p)) installedAny = true;
    }
    return installedAny;
  }

  /**
   * For every pair that was installed under an older app version, kick off a silent
   * Play fetch to pull that pack's updated content. When the fetch completes our
   * state listener re-extracts the new JAR over the old install and rewrites the
   * marker. UI isn't involved; if the user picks a stale pair before the refresh
   * finishes, they'll briefly run on the old content and auto-upgrade next launch.
   */
  public void refreshStalePacks() {
    for (PairCatalog.Pair p : PairCatalog.ENABLED) {
      if (!new File(packagesDir, p.pkg).isDirectory()) continue;
      if (readMarker(p) == currentAppVersion) continue;
      String packName = PairCatalog.packNameFor(p);
      synchronized (listenersByPack) {
        if (listenersByPack.containsKey(packName)) continue;
        listenersByPack.put(packName, silentRefreshListener);
      }
      Log.i(TAG, "refreshing stale pair " + p.pkg + " (marker="
          + readMarker(p) + ", appVer=" + currentAppVersion + ")");
      apm.fetch(Collections.singletonList(packName));
    }
  }

  /** True if the pair's pack is extracted on disk (staleness not considered). */
  public boolean isInstalled(PairCatalog.Pair p) {
    return new File(packagesDir, p.pkg).isDirectory();
  }

  public void fetch(PairCatalog.Pair p, Listener l) {
    if (isInstalled(p)) {
      App.handler.post(l::onReady);
      return;
    }
    String packName = PairCatalog.packNameFor(p);
    synchronized (listenersByPack) {
      listenersByPack.put(packName, l);
    }
    apm.fetch(Collections.singletonList(packName));
  }

  public long totalEnabledBytes() {
    long total = 0;
    for (PairCatalog.Pair p : PairCatalog.ENABLED) {
      if (!isInstalled(p)) total += p.sizeKb * 1024L;
    }
    return total;
  }

  private boolean installIfDelivered(PairCatalog.Pair p) {
    String packName = PairCatalog.packNameFor(p);
    AssetPackLocation loc = apm.getPackLocation(packName);
    if (loc == null || loc.assetsPath() == null) return false;
    File jar = new File(loc.assetsPath(), p.pkg + ".jar");
    if (!jar.exists()) {
      Log.w(TAG, "pack " + packName + " delivered but JAR missing: " + jar);
      return false;
    }
    try {
      App.apertiumInstallation.installJar(jar, p.pkg);
      writeMarker(p);
      Log.i(TAG, "installed " + p.pkg + " from pack " + packName + " @ v" + currentAppVersion);
      return true;
    } catch (IOException e) {
      Log.e(TAG, "failed installing " + p.pkg, e);
      return false;
    }
  }

  private File markerFile(PairCatalog.Pair p) {
    return new File(packagesDir, p.pkg + ".version");
  }

  private int readMarker(PairCatalog.Pair p) {
    File f = markerFile(p);
    if (!f.isFile()) return -1;
    try {
      String s = new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8).trim();
      return Integer.parseInt(s);
    } catch (IOException | NumberFormatException e) {
      return -1;
    }
  }

  private void writeMarker(PairCatalog.Pair p) {
    try (FileOutputStream fos = new FileOutputStream(markerFile(p))) {
      fos.write(String.valueOf(currentAppVersion).getBytes(StandardCharsets.UTF_8));
    } catch (IOException e) {
      Log.w(TAG, "failed writing version marker for " + p.pkg, e);
    }
  }

  private static int readAppVersionCode(Context ctx) {
    try {
      PackageInfo pi = ctx.getPackageManager().getPackageInfo(ctx.getPackageName(), 0);
      return Build.VERSION.SDK_INT >= Build.VERSION_CODES.P
          ? (int) pi.getLongVersionCode() : pi.versionCode;
    } catch (PackageManager.NameNotFoundException e) {
      return 0;
    }
  }

  private final Listener silentRefreshListener = new Listener() {
    @Override public void onProgress(int percent, long bytesSoFar, long totalBytes) {}
    @Override public void onReady() { Log.i(TAG, "stale pair refreshed silently"); }
    @Override public void onFailed(int errorCode) {
      Log.w(TAG, "stale pair refresh failed: " + errorCode);
    }
    @Override public void onCancelled() {}
  };

  private final AssetPackStateUpdateListener stateListener = new AssetPackStateUpdateListener() {
    @Override
    public void onStateUpdate(AssetPackState state) {
      String packName = state.name();
      Listener l;
      synchronized (listenersByPack) {
        l = listenersByPack.get(packName);
      }
      if (l == null) return;

      switch (state.status()) {
        case AssetPackStatus.DOWNLOADING:
        case AssetPackStatus.TRANSFERRING: {
          long soFar = state.bytesDownloaded();
          long total = state.totalBytesToDownload();
          int pct = total > 0 ? (int) (100L * soFar / total) : 0;
          l.onProgress(pct, soFar, total);
          break;
        }
        case AssetPackStatus.COMPLETED: {
          synchronized (listenersByPack) {
            listenersByPack.remove(packName);
          }
          PairCatalog.Pair p = findByPackName(packName);
          if (p == null) {
            l.onFailed(-1);
            return;
          }
          new Thread(() -> {
            boolean ok = installIfDelivered(p);
            App.handler.post(() -> {
              if (ok) {
                App.apertiumInstallation.rescanForPackages();
                l.onReady();
              } else {
                l.onFailed(-1);
              }
            });
          }, "pair-unpack-" + packName).start();
          break;
        }
        case AssetPackStatus.FAILED:
          synchronized (listenersByPack) {
            listenersByPack.remove(packName);
          }
          l.onFailed(state.errorCode());
          break;
        case AssetPackStatus.CANCELED:
          synchronized (listenersByPack) {
            listenersByPack.remove(packName);
          }
          l.onCancelled();
          break;
        case AssetPackStatus.WAITING_FOR_WIFI:
        case AssetPackStatus.PENDING:
        case AssetPackStatus.NOT_INSTALLED:
        case AssetPackStatus.UNKNOWN:
        default:
          break;
      }
    }
  };

  private static PairCatalog.Pair findByPackName(String packName) {
    for (PairCatalog.Pair p : PairCatalog.ENABLED) {
      if (PairCatalog.packNameFor(p).equals(packName)) return p;
    }
    return null;
  }

  public static String humanSize(long bytes) {
    if (bytes < 1024) return bytes + " B";
    double kb = bytes / 1024.0;
    if (kb < 1024) return String.format(java.util.Locale.US, "%.0f KB", kb);
    double mb = kb / 1024.0;
    return String.format(java.util.Locale.US, "%.1f MB", mb);
  }
}
