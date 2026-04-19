/*
 * Copyright (C) 2012 Arink Verma, Jacob Nordfalk
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU General Public License as
 * published by the Free Software Foundation; either version 2 of the
 * License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful, but
 * WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA
 * 02111-1307, USA.
 */
package com.qvyshift.translate;

import org.apertium.Translator;

import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.os.AsyncTask;
import android.os.Bundle;
import android.util.Log;
import android.view.Menu;
import android.view.MenuInflater;
import android.view.MenuItem;
import android.view.inputmethod.InputMethodManager;
import android.webkit.WebView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;

import com.google.android.material.appbar.MaterialToolbar;
import com.google.android.material.textfield.MaterialAutoCompleteTextView;
import com.google.android.material.textfield.TextInputEditText;
import com.google.android.material.textfield.TextInputLayout;

import java.io.StringReader;
import java.io.StringWriter;
import java.util.ArrayList;
import java.util.Collections;

import static com.qvyshift.translate.App.instance;

import org.apertium.pipeline.Program;
import org.apertium.utils.IOUtils;
import org.apertium.utils.Timing;

public class TranslatorActivity extends AppCompatActivity {
  private static final String TAG = "ApertiumActiviy";

  private TextInputLayout inputLayout;
  private TextInputLayout outputLayout;
  private TextInputEditText inputEditText;
  private TextInputEditText outputTextView;
  private MaterialAutoCompleteTextView languagePairDropdown;
  private Button translateButton;

  private String currentModeTitle = null;
  public static final String EXTRA_MODE = "mode";

  @Override
  public void onCreate(Bundle savedInstanceState) {
    super.onCreate(savedInstanceState);
    setContentView(R.layout.simple_layout);

    MaterialToolbar toolbar = findViewById(R.id.toolbar);
    setSupportActionBar(toolbar);

    inputLayout = findViewById(R.id.inputLayout);
    outputLayout = findViewById(R.id.outputLayout);
    inputEditText = findViewById(R.id.inputtext);
    outputTextView = findViewById(R.id.outputText);
    languagePairDropdown = findViewById(R.id.languagePairDropdown);
    translateButton = findViewById(R.id.translateButton);

    translateButton.setOnClickListener(v -> onTranslateClicked());
    languagePairDropdown.setOnItemClickListener((parent, view, position, id) -> {
      String selected = parent.getItemAtPosition(position).toString();
      if (selected.equals(getString(R.string.download_languages))) {
        startActivity(new Intent(this, InstallActivity.class));
        languagePairDropdown.setText(currentModeTitle == null ? "" : currentModeTitle, false);
        return;
      }
      currentModeTitle = selected;
      App.prefs.edit().putString(App.PREF_lastModeTitle, currentModeTitle).commit();
      updateLanguageHints();
    });

    if (translationTask != null) {
      translationTask.activity = this;
    }

    if (savedInstanceState == null) {
      Intent i = getIntent();

      String mode = i.getStringExtra(EXTRA_MODE);
      if (mode != null) {
        currentModeTitle = mode;
      }

      String text = i.getStringExtra(Intent.EXTRA_TEXT);
      if (text != null) {
        inputEditText.setText(text);
        return;
      }

      if (App.prefs.getBoolean(App.PREF_clipBoardGet, true)) {
        android.text.ClipboardManager clipboard = (android.text.ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        CharSequence txt = clipboard.getText();
        String inputText = txt == null ? "" : txt.toString();
        if (inputText.length() > 0) inputEditText.setText(inputText);
      }
    }
  }

  Runnable apertiumInstallationObserver = new Runnable() {
    public void run() {
      if (currentModeTitle == null) {
        currentModeTitle = App.prefs.getString(App.PREF_lastModeTitle, null);
      }
      if (!App.apertiumInstallation.titleToMode.containsKey(currentModeTitle)) {
        currentModeTitle = null;
      }
      if (currentModeTitle == null && App.apertiumInstallation.titleToMode.size() > 0) {
        ArrayList<String> titles = new ArrayList<>(App.apertiumInstallation.titleToMode.keySet());
        Collections.sort(titles);
        currentModeTitle = titles.get(0);
      }

      ArrayList<String> items = new ArrayList<>(App.apertiumInstallation.titleToMode.keySet());
      Collections.sort(items);
      items.add(getString(R.string.download_languages));
      ArrayAdapter<String> adapter = new ArrayAdapter<>(TranslatorActivity.this,
          android.R.layout.simple_list_item_1, items);
      languagePairDropdown.setAdapter(adapter);
      if (currentModeTitle != null) {
        languagePairDropdown.setText(currentModeTitle, false);
      } else {
        languagePairDropdown.setText("", false);
      }
      updateLanguageHints();
    }
  };

  private void updateLanguageHints() {
    String sourceHint = getString(R.string.from);
    String targetHint = getString(R.string.to);
    if (currentModeTitle != null) {
      int arrow = currentModeTitle.indexOf(" \u2192 ");
      int bidir = currentModeTitle.indexOf(" \u21C6 ");
      int split = arrow >= 0 ? arrow : bidir;
      if (split > 0) {
        sourceHint = currentModeTitle.substring(0, split);
        targetHint = currentModeTitle.substring(split + 3);
      }
    }
    inputLayout.setHint(sourceHint);
    outputLayout.setHint(targetHint);
  }

  @Override
  protected void onResume() {
    super.onResume();
    App.apertiumInstallation.observers.add(apertiumInstallationObserver);
    apertiumInstallationObserver.run();
  }

  @Override
  protected void onPause() {
    super.onPause();
    App.apertiumInstallation.observers.remove(apertiumInstallationObserver);
  }

  private void onTranslateClicked() {
    if (App.apertiumInstallation.titleToMode.isEmpty()) {
      startActivity(new Intent(this, InstallActivity.class));
      return;
    }
    InputMethodManager inputManager = (InputMethodManager) this.getSystemService(Context.INPUT_METHOD_SERVICE);
    inputManager.hideSoftInputFromWindow(inputEditText.getApplicationWindowToken(), 0);

    Translator.setCacheEnabled(App.prefs.getBoolean(App.PREF_cacheEnabled, true));
    Translator.setDisplayMarks(App.prefs.getBoolean(App.PREF_displayMark, true));
    Translator.setDelayedNodeLoadingEnabled(true);
    Translator.setParallelProcessingEnabled(false);
    try {
      ApertiumInstallation ai = App.apertiumInstallation;
      String mode = ai.titleToMode.get(currentModeTitle);
      String pkg = ai.modeToPackage.get(mode);
      Translator.setBase(ai.getBasedirForPackage(pkg), ai.getClassLoaderForPackage(pkg));
      Translator.setMode(mode);
      translationTask = new TranslationTask();
      translationTask.activity = this;
      outputTextView.setText("Preparing...");
      translationTask.execute(inputEditText.getText().toString());
    } catch (Exception e) {
      e.printStackTrace();
      App.longToast(e.toString());
    }
    updateUi();
  }

  private void updateUi() {
    boolean ready = translationTask == null;
    translateButton.setEnabled(ready);
    translateButton.setText(ready ? R.string.translate : R.string.translating);
  }

  static TranslationTask translationTask;

  static class TranslationTask extends AsyncTask<String, Object, String> implements Translator.TranslationProgressListener {
    private TranslatorActivity activity;

    @Override
    protected String doInBackground(String... inputText) {
      Runtime rt = Runtime.getRuntime();
      Log.d(TAG, "start mem f=" + rt.freeMemory() / 1000000 + "  t=" + rt.totalMemory() / 1000000 + " m=" + rt.maxMemory() / 1000000);
      IOUtils.timing = new org.apertium.utils.Timing("overall");
      String input = inputText[0];
      try {
        Log.i(TAG, "Translator Run input " + input);
        Timing timing = new Timing("Translator.translate()");
        StringWriter output = new StringWriter();
        String format = "txt";
        Translator.translate(new StringReader(input), output, new Program("apertium-des" + format), new Program("apertium-re" + format), this);
        timing.report();
        Log.i(TAG, "Translator Run output " + output);
        return output.toString();
      } catch (Throwable e) {
        e.printStackTrace();
        Log.e(TAG, "ApertiumActivity.TranslationRun MODE =" + activity.currentModeTitle + ";InputText = " + input);
        return "error: " + e;
      } finally {
        if (IOUtils.timing != null) IOUtils.timing.report();
        IOUtils.timing = null;
        Log.d(TAG, "start mem f=" + rt.freeMemory() / 1000000 + "  t=" + rt.totalMemory() / 1000000 + " m=" + rt.maxMemory() / 1000000);
      }
    }

    public void onTranslationProgress(String task, int progress, int progressMax) {
      publishProgress(task, progress, progressMax);
    }

    @Override
    protected void onProgressUpdate(Object... v) {
      Log.d(TAG, v[0] + " " + v[1] + "/" + v[2]);
      activity.outputTextView.setText("Translating...\n(in stage " + v[1] + " of " + v[2] + ")");
    }

    @Override
    protected void onPostExecute(String output) {
      activity.translationTask = null;
      activity.outputTextView.setText(output);
      if (App.prefs.getBoolean(App.PREF_clipBoardPush, true)) {
        android.text.ClipboardManager clipboard = (android.text.ClipboardManager) activity.getSystemService(Context.CLIPBOARD_SERVICE);
        clipboard.setText(output);
        String PREF_TOASTKEY = "clipboardPasteToast";
        int n = App.prefs.getInt(PREF_TOASTKEY, 0);
        if (n < 3) {
          Toast.makeText(instance, "Text was pasted to clibboard", Toast.LENGTH_SHORT).show();
          App.prefs.edit().putInt(PREF_TOASTKEY, n + 1).commit();
        }
      }
      activity.updateUi();
    }
  }

  @Override
  public boolean onCreateOptionsMenu(Menu menu) {
    MenuInflater inflater = getMenuInflater();
    inflater.inflate(R.menu.simple_option_menu, menu);
    return true;
  }

  @Override
  public boolean onOptionsItemSelected(MenuItem item) {
    int id = item.getItemId();
    if (id == R.id.share) {
      share_text();
      return true;
    } else if (id == R.id.manage) {
      startActivity(new Intent(this, SettingsActivity.class));
      return true;
    } else if (id == R.id.clear) {
      inputEditText.setText("");
      outputTextView.setText("");
      return true;
    } else if (id == R.id.about) {
      AlertDialog.Builder builder = new AlertDialog.Builder(this);
      builder.setTitle(getString(R.string.about));
      WebView wv = new WebView(this);
      Log.d(TAG, getString(R.string.aboutText));
      wv.loadData(getString(R.string.aboutText), "text/html", "UTF-8");
      builder.setView(wv);
      AlertDialog alert = builder.create();
      alert.show();
      return true;
    }
    return super.onOptionsItemSelected(item);
  }

  private void share_text() {
    Log.i(TAG, "ApertiumActivity.share_text Started");
    Intent sharingIntent = new Intent(android.content.Intent.ACTION_SEND);
    sharingIntent.setType("text/plain");
    sharingIntent.putExtra(android.content.Intent.EXTRA_SUBJECT, "Apertium Translate");
    sharingIntent.putExtra(android.content.Intent.EXTRA_TEXT, outputTextView.getText().toString());
    startActivity(Intent.createChooser(sharingIntent, getString(R.string.share_via)));
  }
}
