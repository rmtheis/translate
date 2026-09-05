package com.qvyshift.sardu;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import java.io.File;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Serial translation queue with latest-wins semantics: if the user keeps typing (or taps
 * several phrase chips), only the most recent request is delivered to the callback.
 */
public final class Translator {
    private static final String TAG = "Translator";

    public interface Callback {
        void onResult(String output);
        void onError(String message);
    }

    private final PairStore store;
    private final NativePipeline pipeline;
    private final ExecutorService exec = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "apertium");
        t.setDaemon(true);
        return t;
    });
    private final Handler main = new Handler(Looper.getMainLooper());
    private final AtomicLong generation = new AtomicLong();

    public Translator(Context ctx) {
        this.store = PairStore.get(ctx);
        this.pipeline = new NativePipeline(ctx);
    }

    public void translate(String input, Direction direction, Callback cb) {
        final long gen = generation.incrementAndGet();
        exec.execute(() -> {
            if (gen != generation.get()) return; // superseded before it even started
            String out;
            try {
                store.awaitReady();
                File modeFile = store.modeFile(direction);
                long t0 = System.currentTimeMillis();
                out = pipeline.translate(modeFile, store.pairDir(), input, true);
                Log.i(TAG, direction.modeId + ": " + input.length() + " chars in "
                        + (System.currentTimeMillis() - t0) + "ms");
            } catch (Exception e) {
                Log.e(TAG, "translate failed", e);
                final String msg = e.getMessage() == null ? e.toString() : e.getMessage();
                if (gen == generation.get()) main.post(() -> cb.onError(msg));
                return;
            }
            final String result = out.replaceAll("\\s+$", "");
            if (gen == generation.get()) main.post(() -> cb.onResult(result));
        });
    }
}
