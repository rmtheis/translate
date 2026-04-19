package com.qvyshift.translate;

import android.content.Context;
import android.util.Log;

import com.google.android.play.core.assetpacks.AssetPackLocation;
import com.google.android.play.core.assetpacks.AssetPackManager;
import com.google.android.play.core.assetpacks.AssetPackManagerFactory;
import com.google.android.play.core.assetpacks.AssetPackState;
import com.google.android.play.core.assetpacks.AssetPackStateUpdateListener;
import com.google.android.play.core.assetpacks.AssetPackStates;
import com.google.android.play.core.assetpacks.model.AssetPackStatus;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Thin wrapper around {@link AssetPackManager} that fetches per-pair on-demand asset
 * packs and unpacks their shipped {@code apertium-<pair>.jar} into the app's
 * installation dir so {@link ApertiumInstallation} can see them. A single Play Core
 * listener is registered once; individual download requests attach a {@link Listener}
 * that gets progress, completion, and failure callbacks on the main thread.
 */
public class PairDownloadManager {
  private static final String TAG = "PairDownload";

  public interface Listener {
    /** 0..100 while downloading or transferring. */
    void onProgress(int percent, long bytesSoFar, long totalBytes);
    /** Pack has been delivered and its JAR unpacked into the installation dir. */
    void onReady();
    /** Terminal failure (error code from {@link AssetPackState#errorCode()}). */
    void onFailed(int errorCode);
    /** User-initiated cancel from Play Core. */
    void onCancelled();
  }

  private final Context ctx;
  private final AssetPackManager apm;
  private final File packagesDir;
  private final Map<String, Listener> listenersByPack = new HashMap<>();

  public PairDownloadManager(Context ctx, File packagesDir) {
    this.ctx = ctx.getApplicationContext();
    this.packagesDir = packagesDir;
    this.apm = AssetPackManagerFactory.getInstance(this.ctx);
    this.apm.registerListener(stateListener);
  }

  /**
   * Walk enabled pairs and, for any pack already delivered on disk (e.g. a previous
   * fetch completed, or user reinstalled app with packs cached by Play), unpack its
   * JAR into {@link ApertiumInstallation}. Runs on the caller's thread; fast — no
   * network. Returns true if any pair was freshly unpacked.
   */
  public boolean installAlreadyDelivered() {
    boolean installedAny = false;
    for (PairCatalog.Pair p : PairCatalog.ENABLED) {
      if (new File(packagesDir, p.pkg).isDirectory()) continue;
      if (installIfDelivered(p)) installedAny = true;
    }
    return installedAny;
  }

  /** True if the pair's on-demand pack has been downloaded and the JAR unpacked. */
  public boolean isInstalled(PairCatalog.Pair p) {
    return new File(packagesDir, p.pkg).isDirectory();
  }

  /**
   * Kick off a fetch for a single pair. The Listener gets progress callbacks until
   * either {@link Listener#onReady()} (pack delivered AND JAR unpacked) or
   * {@link Listener#onFailed(int)} fires. Calling fetch() for a pair that's
   * already installed immediately returns onReady().
   */
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

  /** Total size of every enabled pair's pack (sum of {@code sizeKb}), in bytes. */
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
      Log.i(TAG, "installed " + p.pkg + " from pack " + packName);
      return true;
    } catch (IOException e) {
      Log.e(TAG, "failed installing " + p.pkg, e);
      return false;
    }
  }

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
          // Unpack the JAR on a worker thread; installJar does zip extraction.
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
          // No-op — the UI stays in its "downloading" state.
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

  /**
   * Human-readable size string for a pair's pack (e.g. "5.4 MB").
   */
  public static String humanSize(long bytes) {
    if (bytes < 1024) return bytes + " B";
    double kb = bytes / 1024.0;
    if (kb < 1024) return String.format(java.util.Locale.US, "%.0f KB", kb);
    double mb = kb / 1024.0;
    return String.format(java.util.Locale.US, "%.1f MB", mb);
  }
}
