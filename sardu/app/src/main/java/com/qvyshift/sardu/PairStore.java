package com.qvyshift.sardu;

import android.content.Context;
import android.content.pm.PackageInfo;
import android.content.res.AssetManager;
import android.util.Log;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.concurrent.CountDownLatch;

/**
 * Copies the bundled Apertium pair (assets/pair/*) into the app's private files dir the
 * first time this versionCode runs. The native tools take file paths, so the data has to
 * live on disk rather than inside the APK.
 *
 * <p>Layout on disk: {@code <filesDir>/pair/<file>} — flat, exactly as shipped by the
 * Debian package, which is the layout {@link NativePipeline#rewritePath} expects when it
 * rewrites the {@code /usr/share/apertium/apertium-srd-ita/...} paths in the .mode files.
 */
public final class PairStore {
    private static final String TAG = "PairStore";
    private static final String ASSET_DIR = "pair";
    private static final String STAMP = ".installed-version";

    private static PairStore instance;

    private final Context app;
    private final File pairDir;
    private final CountDownLatch ready = new CountDownLatch(1);
    private volatile IOException failure;

    private PairStore(Context ctx) {
        this.app = ctx.getApplicationContext();
        this.pairDir = new File(app.getFilesDir(), ASSET_DIR);
    }

    public static synchronized PairStore get(Context ctx) {
        if (instance == null) instance = new PairStore(ctx);
        return instance;
    }

    public File pairDir() { return pairDir; }

    /** Extract on a background thread; safe to call more than once. */
    public synchronized void ensureInstalledAsync() {
        if (ready.getCount() == 0) return;
        Thread t = new Thread(() -> {
            try {
                installIfNeeded();
            } catch (IOException e) {
                Log.e(TAG, "pair install failed", e);
                failure = e;
            } finally {
                ready.countDown();
            }
        }, "pair-install");
        t.setDaemon(true);
        t.start();
    }

    /** Block until extraction is done (call from a worker thread only). */
    public void awaitReady() throws IOException {
        try {
            ready.await();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IOException("interrupted waiting for pair install", e);
        }
        if (failure != null) throw failure;
    }

    public File modeFile(Direction d) {
        return new File(pairDir, d.modeId + ".mode");
    }

    private void installIfNeeded() throws IOException {
        String want = Long.toString(currentVersionCode());
        File stamp = new File(pairDir, STAMP);
        if (stamp.isFile()) {
            String have = new String(Files.readAllBytes(stamp.toPath()), StandardCharsets.UTF_8).trim();
            if (want.equals(have)) {
                Log.d(TAG, "pair already installed for versionCode " + want);
                return;
            }
        }
        long t0 = System.currentTimeMillis();
        // Wipe and re-extract so a pair update never leaves stale files behind.
        deleteRecursively(pairDir);
        if (!pairDir.mkdirs() && !pairDir.isDirectory()) {
            throw new IOException("cannot create " + pairDir);
        }
        AssetManager am = app.getAssets();
        String[] names = am.list(ASSET_DIR);
        if (names == null || names.length == 0) throw new IOException("no bundled pair assets");
        byte[] buf = new byte[64 * 1024];
        for (String name : names) {
            try (InputStream in = am.open(ASSET_DIR + "/" + name);
                 OutputStream out = new FileOutputStream(new File(pairDir, name))) {
                int n;
                while ((n = in.read(buf)) != -1) out.write(buf, 0, n);
            }
        }
        try (OutputStream out = new FileOutputStream(stamp)) {
            out.write(want.getBytes(StandardCharsets.UTF_8));
        }
        Log.i(TAG, "installed " + names.length + " pair files in "
                + (System.currentTimeMillis() - t0) + "ms");
    }

    private long currentVersionCode() {
        try {
            PackageInfo pi = app.getPackageManager().getPackageInfo(app.getPackageName(), 0);
            return android.os.Build.VERSION.SDK_INT >= 28 ? pi.getLongVersionCode() : pi.versionCode;
        } catch (Exception e) {
            return 0;
        }
    }

    private static void deleteRecursively(File f) {
        if (f == null || !f.exists()) return;
        File[] kids = f.listFiles();
        if (kids != null) for (File k : kids) deleteRecursively(k);
        //noinspection ResultOfMethodCallIgnored
        f.delete();
    }
}
