package com.qvyshift.sardu;

import android.app.Application;

/** Kicks off pair extraction early so the first translation doesn't pay for it. */
public class App extends Application {
    @Override
    public void onCreate() {
        super.onCreate();
        PairStore.get(this).ensureInstalledAsync();
    }
}
