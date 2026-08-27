package com.qvyshift.translate;

import android.app.Activity;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.ApplicationInfo;
import android.util.Log;

import com.google.android.play.core.review.ReviewManager;
import com.google.android.play.core.review.ReviewManagerFactory;

import java.util.concurrent.TimeUnit;

/**
 * Google Play in-app review prompt, gated so it can never nag.
 *
 * <p>Two gates must both pass before the sheet is ever requested: the app has
 * been launched at least {@link #MIN_LAUNCHES} times, and at least 3 days have
 * passed since the first launch. Both exist to keep the prompt away from
 * people who are still deciding whether they like the app at all — someone who
 * bounces on day one is the most likely to leave a one-star review if asked.
 *
 * <p>Play's API tells us nothing about what the user did with the sheet:
 * {@code launchReviewFlow()} completes identically whether they rated,
 * dismissed it, or Play silently suppressed it against its own server-side
 * quota. So every launch of the flow is treated as a possible dismissal and the
 * app goes quiet for 90 days afterwards.
 *
 * <p>Java rather than Kotlin only because this module has no Kotlin plugin
 * applied; the logic mirrors {@code ReviewPrompt.kt} in the sibling apps.
 */
public final class ReviewPrompt {
    private static final String TAG = ReviewPrompt.class.getSimpleName();

    private static final int MIN_LAUNCHES = 3;
    private static final long MIN_TIME_SINCE_FIRST_LAUNCH_MS = TimeUnit.DAYS.toMillis(3);

    /** Gap after the sheet has been requested once. Play caps repeat displays
     *  server-side too, but that quota is undocumented and can change — this is
     *  the guarantee we actually control. */
    private static final long QUIET_PERIOD_MS = TimeUnit.DAYS.toMillis(90);

    private static final String PREFS_NAME = "review_prompt";
    private static final String LAUNCH_COUNT_KEY = "launchCount";
    private static final String FIRST_LAUNCH_TIME_KEY = "firstLaunchTime";
    private static final String LAST_REQUESTED_TIME_KEY = "lastRequestedTime";

    private ReviewPrompt() {
    }

    /**
     * Records this launch and, if every gate passes, asks Play for the review
     * sheet. Call once per cold start from the launcher activity's
     * {@code onCreate()}; everything after the counter bump is asynchronous, so
     * this does not delay startup.
     */
    public static void onLaunch(final Activity activity) {
        // Never prompt from a debug build — those launches are ours, and a debug
        // package isn't installed from Play, so the flow would no-op anyway
        // while still burning the quiet period. Read the manifest flag rather
        // than BuildConfig.DEBUG so this file drops into a module whether or not
        // it has the buildConfig feature enabled.
        if ((activity.getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
            return;
        }

        final SharedPreferences prefs =
                activity.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        final long now = System.currentTimeMillis();

        if (recordLaunch(prefs, now) < MIN_LAUNCHES) {
            return;
        }

        final long firstLaunchTime = prefs.getLong(FIRST_LAUNCH_TIME_KEY, now);
        if (now - firstLaunchTime < MIN_TIME_SINCE_FIRST_LAUNCH_MS) {
            return;
        }

        // Missing key means we've never asked, so fall back to 0 rather than
        // `now` — otherwise a first-ever qualifying launch would be treated as
        // having just prompted and wait out the whole quiet period.
        final long lastRequestedTime = prefs.getLong(LAST_REQUESTED_TIME_KEY, 0L);
        if (lastRequestedTime != 0L && now - lastRequestedTime < QUIET_PERIOD_MS) {
            return;
        }

        final ReviewManager reviewManager = ReviewManagerFactory.create(activity);
        reviewManager.requestReviewFlow().addOnCompleteListener(reviewInfoTask -> {
            if (!reviewInfoTask.isSuccessful()) {
                // No Play Store, sideloaded build, no network — try again on a
                // later launch rather than spending the quiet period on a sheet
                // the user never saw.
                Log.d(TAG, "Review flow unavailable", reviewInfoTask.getException());
                return;
            }
            // Stamp before launching: this is the last point at which we know
            // anything, since the launch task's completion carries no verdict.
            prefs.edit()
                    .putLong(LAST_REQUESTED_TIME_KEY, System.currentTimeMillis())
                    .apply();
            reviewManager.launchReviewFlow(activity, reviewInfoTask.getResult());
        });
    }

    /** Bumps the launch counter, seeding the first-launch timestamp on the way
     *  through, and returns the new count. */
    private static int recordLaunch(final SharedPreferences prefs, final long now) {
        final SharedPreferences.Editor editor = prefs.edit();
        if (prefs.getLong(FIRST_LAUNCH_TIME_KEY, 0L) == 0L) {
            editor.putLong(FIRST_LAUNCH_TIME_KEY, now);
        }
        // Saturate rather than letting a long-lived install overflow.
        final int launchCount = Math.min(prefs.getInt(LAUNCH_COUNT_KEY, 0) + 1, MIN_LAUNCHES);
        editor.putInt(LAUNCH_COUNT_KEY, launchCount).apply();
        return launchCount;
    }
}
