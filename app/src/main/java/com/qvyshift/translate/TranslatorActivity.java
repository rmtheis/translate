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

import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.os.AsyncTask;
import android.os.Bundle;
import android.text.Html;
import android.text.method.LinkMovementMethod;
import android.util.Log;
import android.view.Menu;
import android.view.MenuInflater;
import android.view.MenuItem;
import android.view.View;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageButton;
import android.widget.TextView;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;

import com.google.android.material.appbar.MaterialToolbar;
import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.google.android.material.switchmaterial.SwitchMaterial;
import com.google.android.material.textfield.MaterialAutoCompleteTextView;
import com.google.android.material.textfield.TextInputEditText;
import com.google.android.material.textfield.TextInputLayout;

import java.io.File;
import java.util.ArrayList;
import java.util.Collections;

public class TranslatorActivity extends AppCompatActivity {
  private static final String TAG = "ApertiumActiviy";

  private TextInputLayout inputLayout;
  private TextInputLayout outputLayout;
  private TextInputEditText inputEditText;
  private TextInputEditText outputTextView;
  private MaterialAutoCompleteTextView languagePairDropdown;
  private Button translateButton;
  private ImageButton swapButton;
  private PairListAdapter pairAdapter;

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
    swapButton = findViewById(R.id.swapButton);

    translateButton.setOnClickListener(v -> onTranslateClicked());
    swapButton.setOnClickListener(v -> onSwapClicked());
    findViewById(R.id.sourceCopyButton).setOnClickListener(v -> copyFrom(inputEditText));
    findViewById(R.id.sourcePasteButton).setOnClickListener(v -> pasteInto(inputEditText));
    findViewById(R.id.targetCopyButton).setOnClickListener(v -> copyFrom(outputTextView));
    findViewById(R.id.targetPasteButton).setOnClickListener(v -> pasteInto(outputTextView));
    pairAdapter = new PairListAdapter(this);
    languagePairDropdown.setAdapter(pairAdapter);
    languagePairDropdown.setOnItemClickListener((parent, view, position, id) -> {
      PairListAdapter.Item item = pairAdapter.getItem(position);
      if (item == null || item.kind != PairListAdapter.Kind.PAIR) return;
      if (!item.installed) {
        Toast.makeText(this, R.string.pair_not_installed, Toast.LENGTH_SHORT).show();
        languagePairDropdown.setText(currentModeTitle == null ? "" : currentModeTitle, false);
        return;
      }
      currentModeTitle = item.modeTitle;
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

      pairAdapter.setInstalledTitles(App.apertiumInstallation.titleToMode.keySet());
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
    updateSwapButton();
  }

  private String getReverseTitle(String title) {
    if (title == null) return null;
    int arrow = title.indexOf(" \u2192 ");
    if (arrow < 0) return null;
    String src = title.substring(0, arrow);
    String tgt = title.substring(arrow + 3);
    return tgt + " \u2192 " + src;
  }

  private boolean hasReverseMode() {
    String reverse = getReverseTitle(currentModeTitle);
    return reverse != null && App.apertiumInstallation.titleToMode.containsKey(reverse);
  }

  private void updateSwapButton() {
    swapButton.setAlpha(hasReverseMode() ? 1.0f : 0.4f);
  }

  private void onSwapClicked() {
    if (!hasReverseMode()) {
      Toast.makeText(this, R.string.one_way_only, Toast.LENGTH_SHORT).show();
      return;
    }
    String reverse = getReverseTitle(currentModeTitle);
    currentModeTitle = reverse;
    App.prefs.edit().putString(App.PREF_lastModeTitle, currentModeTitle).commit();
    languagePairDropdown.setText(currentModeTitle, false);

    CharSequence oldInput = inputEditText.getText();
    CharSequence oldOutput = outputTextView.getText();
    inputEditText.setText(oldOutput);
    outputTextView.setText(oldInput);

    updateLanguageHints();
  }

  private void pasteInto(EditText field) {
    ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
    ClipData clip = cm.getPrimaryClip();
    if (clip == null || clip.getItemCount() == 0) return;
    CharSequence text = clip.getItemAt(0).coerceToText(this);
    if (text == null) return;
    field.setText(text);
    field.setSelection(field.length());
  }

  private void copyFrom(EditText field) {
    CharSequence text = field.getText();
    if (text == null || text.length() == 0) return;
    ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
    cm.setPrimaryClip(ClipData.newPlainText("translation", text));
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

    try {
      ApertiumInstallation ai = App.apertiumInstallation;
      String mode = ai.titleToMode.get(currentModeTitle);
      String pkg = ai.modeToPackage.get(mode);
      File pairBaseDir = new File(ai.getBasedirForPackage(pkg));
      File modeFile = NativePipeline.findModeFile(pairBaseDir, mode);
      if (modeFile == null) {
        App.longToast("Mode file not found for " + mode);
        return;
      }
      translationTask = new TranslationTask();
      translationTask.activity = this;
      translationTask.pipeline = new NativePipeline(this);
      translationTask.modeFile = modeFile;
      translationTask.pairBaseDir = pairBaseDir;
      translationTask.displayMarks = App.prefs.getBoolean(App.PREF_displayMark, true);
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

  static class TranslationTask extends AsyncTask<String, Object, String> {
    private TranslatorActivity activity;
    private NativePipeline pipeline;
    private File modeFile;
    private File pairBaseDir;
    private boolean displayMarks;

    @Override
    protected String doInBackground(String... inputText) {
      String input = inputText[0];
      try {
        Log.i(TAG, "translating (" + input.length() + " chars) via " + modeFile);
        long t0 = System.currentTimeMillis();
        String output = pipeline.translate(modeFile, pairBaseDir, input, displayMarks);
        Log.i(TAG, "translated in " + (System.currentTimeMillis() - t0) + "ms");
        return output;
      } catch (Throwable e) {
        Log.e(TAG, "translate failed for mode=" + modeFile, e);
        return "error: " + e;
      }
    }

    @Override
    protected void onPostExecute(String output) {
      activity.translationTask = null;
      activity.outputTextView.setText(output);
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
    if (id == R.id.manage) {
      showSettingsDialog();
      return true;
    }
    return super.onOptionsItemSelected(item);
  }

  private void showSettingsDialog() {
    View content = getLayoutInflater().inflate(R.layout.dialog_about_settings, null);

    TextView basedOn = content.findViewById(R.id.basedOnText);
    basedOn.setText(Html.fromHtml(
        "Based on the <a href=\"https://github.com/apertium\">Apertium</a> project<br/>"
            + "<a href=\"https://github.com/rmtheis/translate\">github.com/rmtheis/translate</a><br/>"
            + "Licensed under <a href=\"https://www.gnu.org/licenses/gpl-3.0.html\">GPLv3</a>"));
    basedOn.setMovementMethod(LinkMovementMethod.getInstance());

    SwitchMaterial displayMarkSwitch = content.findViewById(R.id.displayMarkSwitch);
    displayMarkSwitch.setChecked(App.prefs.getBoolean(App.PREF_displayMark, true));
    displayMarkSwitch.setOnCheckedChangeListener((buttonView, isChecked) ->
        App.prefs.edit().putBoolean(App.PREF_displayMark, isChecked).apply());

    new MaterialAlertDialogBuilder(this)
        .setView(content)
        .setPositiveButton(android.R.string.ok, null)
        .show();
  }
}
