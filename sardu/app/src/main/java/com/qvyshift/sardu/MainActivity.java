package com.qvyshift.sardu;

import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.MenuItem;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.widget.EditText;
import android.widget.TextView;
import android.widget.Toast;

import androidx.activity.EdgeToEdge;
import androidx.activity.SystemBarStyle;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;

import com.google.android.material.appbar.MaterialToolbar;
import com.google.android.material.button.MaterialButton;
import com.google.android.material.chip.Chip;
import com.google.android.material.chip.ChipGroup;
import com.google.android.material.dialog.MaterialAlertDialogBuilder;

public class MainActivity extends AppCompatActivity {
    private static final String PREFS = "sardu";
    private static final String PREF_DIRECTION = "direction";
    /** Pause after the last keystroke before auto-translating. */
    private static final long DEBOUNCE_MS = 600;

    private Direction direction = Direction.ITA_TO_SRD;
    private Translator translator;
    private SharedPreferences prefs;

    private TextView sourceLang, targetLang, outputText;
    private EditText inputText;
    private MaterialButton translateButton;
    private ChipGroup phraseChips;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable autoTranslate = this::translateNow;
    /** Set while we programmatically replace the input (chip tap, swap) to avoid a double run. */
    private boolean suppressWatcher;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // Transparent bars, light icons: the red app bar extends under the status bar.
        EdgeToEdge.enable(this,
                SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
                SystemBarStyle.auto(android.graphics.Color.TRANSPARENT,
                        android.graphics.Color.TRANSPARENT));
        setContentView(R.layout.activity_main);
        setUpEdgeToEdge();

        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        translator = new Translator(this);
        direction = Direction.valueOf(
                prefs.getString(PREF_DIRECTION, Direction.ITA_TO_SRD.name()));

        MaterialToolbar toolbar = findViewById(R.id.toolbar);
        toolbar.setOnMenuItemClickListener(this::onMenuItem);

        sourceLang = findViewById(R.id.sourceLang);
        targetLang = findViewById(R.id.targetLang);
        inputText = findViewById(R.id.inputText);
        outputText = findViewById(R.id.outputText);
        translateButton = findViewById(R.id.translateButton);
        phraseChips = findViewById(R.id.phraseChips);

        findViewById(R.id.swapButton).setOnClickListener(v -> swap());
        sourceLang.setOnClickListener(v -> swap());
        targetLang.setOnClickListener(v -> swap());
        translateButton.setOnClickListener(v -> {
            hideKeyboard();
            translateNow();
        });
        findViewById(R.id.pasteButton).setOnClickListener(v -> paste());
        findViewById(R.id.copyButton).setOnClickListener(v -> copyOutput());
        findViewById(R.id.shareButton).setOnClickListener(v -> shareOutput());

        inputText.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int a, int b, int c) {}
            @Override public void onTextChanged(CharSequence s, int a, int b, int c) {}
            @Override public void afterTextChanged(Editable s) {
                if (suppressWatcher) return;
                handler.removeCallbacks(autoTranslate);
                if (s.toString().trim().isEmpty()) {
                    outputText.setText("");
                } else {
                    handler.postDelayed(autoTranslate, DEBOUNCE_MS);
                }
            }
        });
        inputText.setOnEditorActionListener((v, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_DONE) {
                hideKeyboard();
                translateNow();
                return true;
            }
            return false;
        });

        applyDirection();

        if (savedInstanceState == null) {
            Intent i = getIntent();
            if (Intent.ACTION_SEND.equals(i.getAction())) {
                String shared = i.getStringExtra(Intent.EXTRA_TEXT);
                if (shared != null) setInput(shared, true);
            }
        } else {
            // Input survives via the EditText's own state; just redo the translation.
            if (!inputText.getText().toString().trim().isEmpty()) translateNow();
        }
    }

    @Override
    protected void onDestroy() {
        handler.removeCallbacks(autoTranslate);
        super.onDestroy();
    }

    /** Light status-bar icons over the red app bar; keep content clear of the nav bar. */
    private void setUpEdgeToEdge() {
        android.view.View scroll = findViewById(R.id.scroll);
        final int basePadding = scroll.getPaddingBottom();
        ViewCompat.setOnApplyWindowInsetsListener(scroll, (v, insets) -> {
            Insets bars = insets.getInsets(WindowInsetsCompat.Type.systemBars()
                    | WindowInsetsCompat.Type.ime());
            v.setPadding(v.getPaddingLeft(), v.getPaddingTop(), v.getPaddingRight(),
                    basePadding + bars.bottom);
            return insets;
        });
    }

    private boolean onMenuItem(MenuItem item) {
        if (item.getItemId() == R.id.action_about) {
            showAbout();
            return true;
        }
        return false;
    }

    private void applyDirection() {
        sourceLang.setText(direction.sourceLabel);
        targetLang.setText(direction.targetLabel);
        buildPhraseChips();
    }

    private void swap() {
        direction = direction.reversed();
        prefs.edit().putString(PREF_DIRECTION, direction.name()).apply();
        // Move the translation into the input so the user can translate it back.
        String out = outputText.getText().toString();
        applyDirection();
        if (!out.isEmpty() && !out.contains("*")) {
            setInput(out, true);
        } else if (!inputText.getText().toString().trim().isEmpty()) {
            translateNow();
        }
    }

    private void buildPhraseChips() {
        phraseChips.removeAllViews();
        String[] items = getResources().getStringArray(
                direction == Direction.ITA_TO_SRD ? R.array.phrases_it : R.array.phrases_sc);
        for (String phrase : items) {
            Chip chip = new Chip(this);
            chip.setText(phrase);
            chip.setCheckable(false);
            chip.setEnsureMinTouchTargetSize(false);
            chip.setOnClickListener(v -> {
                hideKeyboard();
                setInput(phrase, true);
            });
            phraseChips.addView(chip);
        }
        findViewById(R.id.phrasesScroll).scrollTo(0, 0);
    }

    private void setInput(String text, boolean translate) {
        suppressWatcher = true;
        inputText.setText(text);
        inputText.setSelection(text.length());
        suppressWatcher = false;
        handler.removeCallbacks(autoTranslate);
        if (translate) translateNow();
    }

    private void translateNow() {
        handler.removeCallbacks(autoTranslate);
        String input = inputText.getText().toString();
        if (input.trim().isEmpty()) {
            outputText.setText("");
            return;
        }
        translateButton.setEnabled(false);
        translateButton.setText(R.string.translating);
        translator.translate(input, direction, new Translator.Callback() {
            @Override public void onResult(String output) {
                outputText.setText(output);
                resetButton();
            }
            @Override public void onError(String message) {
                outputText.setText(getString(R.string.error_prefix, message));
                resetButton();
            }
        });
    }

    private void resetButton() {
        translateButton.setEnabled(true);
        translateButton.setText(R.string.translate);
    }

    private void paste() {
        ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        ClipData clip = cm.getPrimaryClip();
        if (clip == null || clip.getItemCount() == 0) return;
        CharSequence text = clip.getItemAt(0).coerceToText(this);
        if (text == null || text.length() == 0) return;
        setInput(text.toString(), true);
    }

    private void copyOutput() {
        CharSequence text = outputText.getText();
        if (text == null || text.length() == 0) return;
        ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        cm.setPrimaryClip(ClipData.newPlainText("translation", text));
        Toast.makeText(this, R.string.copied, Toast.LENGTH_SHORT).show();
    }

    private void shareOutput() {
        CharSequence text = outputText.getText();
        if (text == null || text.length() == 0) return;
        Intent send = new Intent(Intent.ACTION_SEND)
                .setType("text/plain")
                .putExtra(Intent.EXTRA_TEXT, text.toString());
        startActivity(Intent.createChooser(send, getString(R.string.share)));
    }

    private void hideKeyboard() {
        InputMethodManager imm = (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
        if (imm != null) imm.hideSoftInputFromWindow(inputText.getWindowToken(), 0);
    }

    private void showAbout() {
        String version;
        try {
            version = getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
        } catch (Exception e) {
            version = "?";
        }
        new MaterialAlertDialogBuilder(this)
                .setTitle(R.string.app_name)
                .setMessage(getString(R.string.about_body, version))
                .setPositiveButton(android.R.string.ok, null)
                .show();
    }
}
