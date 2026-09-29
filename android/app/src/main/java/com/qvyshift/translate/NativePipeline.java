package com.qvyshift.translate;

import android.content.Context;
import android.util.Log;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.InterruptedIOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Runs an Apertium translation pipeline by spawning the cross-compiled C++ binaries
 * from {@code app/src/main/jniLibs/<abi>/}. Replaces the Java-port-only
 * {@link org.apertium.Translator} path, which couldn't handle any modern pair that
 * depends on cg-proc, lsx-proc, rtx-proc, or apertium-anaphora.
 *
 * <p>Android 10+ only permits execution of binaries under the app's native library dir
 * ({@code ApplicationInfo.nativeLibraryDir}). Shipped binaries therefore live in
 * {@code jniLibs/<abi>/} with names {@code lib<tool>.so} (e.g. {@code liblt_proc.so});
 * Gradle extracts them into {@code nativeLibraryDir} at install time. The original
 * {@code .mode} file references binaries by their non-prefixed name
 * ({@code lt-proc}, {@code apertium-transfer}, ...), so we keep a mapping from
 * those friendly names to the corresponding {@code lib*.so} file on disk.
 */
public class NativePipeline {
  private static final String TAG = "NativePipeline";

  /** Map from {@code .mode}-file tool name → jniLibs filename. */
  private static final Map<String, String> TOOL_LIBS = new HashMap<>();
  static {
    TOOL_LIBS.put("lt-proc",                  "liblt_proc.so");
    TOOL_LIBS.put("lt-comp",                  "liblt_comp.so");
    TOOL_LIBS.put("lt-expand",                "liblt_expand.so");
    TOOL_LIBS.put("lt-paradigm",              "liblt_paradigm.so");
    TOOL_LIBS.put("lt-print",                 "liblt_print.so");
    TOOL_LIBS.put("lt-trim",                  "liblt_trim.so");
    TOOL_LIBS.put("apertium-tagger",          "libapertium_tagger.so");
    TOOL_LIBS.put("apertium-pretransfer",     "libapertium_pretransfer.so");
    TOOL_LIBS.put("apertium-posttransfer",    "libapertium_posttransfer.so");
    TOOL_LIBS.put("apertium-transfer",        "libapertium_transfer.so");
    TOOL_LIBS.put("apertium-interchunk",      "libapertium_interchunk.so");
    TOOL_LIBS.put("apertium-postchunk",       "libapertium_postchunk.so");
    TOOL_LIBS.put("apertium-preprocess-transfer", "libapertium_preprocess_transfer.so");
    TOOL_LIBS.put("apertium-anaphora",        "libapertium_anaphora.so");
    TOOL_LIBS.put("lrx-proc",                 "liblrx_proc.so");
    TOOL_LIBS.put("lsx-proc",                 "liblsx_proc.so");
    TOOL_LIBS.put("rtx-proc",                 "librtx_proc.so");
    TOOL_LIBS.put("cg-proc",                  "libcg_proc.so");
    TOOL_LIBS.put("cg-comp",                  "libcg_comp.so");
    TOOL_LIBS.put("hfst-proc",                "libhfst_proc.so");
  }

  /** Matches a single pipeline stage like {@code apertium-transfer -b foo.t1x foo.t1x.bin}. */
  private static final Pattern SHELL_TOKEN = Pattern.compile("'([^']*)'|\"([^\"]*)\"|(\\S+)");

  private final String nativeLibraryDir;

  public NativePipeline(Context ctx) {
    this.nativeLibraryDir = ctx.getApplicationInfo().nativeLibraryDir;
  }

  /** Resolve the .mode file for a mode id under the pair's base dir. */
  public static File findModeFile(File pairBaseDir, String modeId) {
    for (String sub : new String[]{"data/modes", "modes", ""}) {
      File f = sub.isEmpty()
          ? new File(pairBaseDir, modeId + ".mode")
          : new File(new File(pairBaseDir, sub), modeId + ".mode");
      if (f.isFile()) return f;
    }
    return null;
  }

  /**
   * Parse a {@code .mode} file and run its pipeline over {@code input}. Paths in the
   * mode file that start with {@code /usr/share/apertium/apertium-<pkg>/} or any
   * absolute path are rewritten to sit under {@code pairBaseDir}.
   *
   * @param modeFile       the {@code .mode} file shipped with the pair
   * @param pairBaseDir    directory where the pair's {@code .bin} / rule files live on-device
   * @param input          source text to translate
   * @param displayMarks   if true, unknown words get a leading * in the output; if false, the
   *                       unknown-word markers are stripped entirely
   * @return translated text
   */
  public String translate(File modeFile, File pairBaseDir, String input, boolean displayMarks)
      throws IOException {
    String modeLine = readFirstNonEmptyLine(modeFile);
    if (modeLine == null) throw new IOException("empty mode file: " + modeFile);
    List<List<String>> stages = parseModeLine(modeLine, pairBaseDir);
    // An escaped "^" in the text after the last word trips lrx-proc (apertium-lex-tools reads
    // it as the start of a lexical unit and consumes the rest of the stream: the tail is lost
    // and U+FFFF leaks out). Nothing after the last word gets translated anyway, so that tail
    // bypasses the pipeline and is re-attached verbatim.
    int tail = caretTailStart(input);
    String head = tail < 0 ? input : input.substring(0, tail);
    if (tail >= 0 && head.trim().isEmpty()) return input;
    String raw = runPipeline(stages, escapeStream(head));
    String out = unescapeStream(applyMarkerPref(raw, displayMarks));
    return tail < 0 ? out : stripTrailingLineBreaks(out) + input.substring(tail);
  }

  /**
   * Start of the trailing text that must bypass the pipeline, or -1 if none: from the first
   * {@code ^} after the last letter or digit, together with the whitespace before it.
   */
  static int caretTailStart(String text) {
    int afterLastWord = 0;
    for (int i = 0; i < text.length(); ) {
      int cp = text.codePointAt(i);
      i += Character.charCount(cp);
      if (Character.isLetterOrDigit(cp)) afterLastWord = i;
    }
    int start = text.indexOf('^', afterLastWord);
    if (start < 0) return -1;
    while (start > afterLastWord && Character.isWhitespace(text.charAt(start - 1))) start--;
    return start;
  }

  /** Drop the line break(s) the pipeline echoes back for the newline fed to stage 0. */
  private static String stripTrailingLineBreaks(String s) {
    int end = s.length();
    while (end > 0 && (s.charAt(end - 1) == '\n' || s.charAt(end - 1) == '\r')) end--;
    return s.substring(0, end);
  }

  /**
   * Characters that are syntax in Apertium's stream format: lttoolbox's {@code escaped_chars},
   * the same set {@code apertium-destxt} escapes. The mode files start at {@code lt-proc}, not
   * at the deformatter, so raw user text has to be escaped here. Unescaped, lt-proc stops with
   * "Malformed input stream" at the first {@code /}, {@code @}, {@code $}, ... (a date like 5/9,
   * an email address, a URL) and everything after it is lost; {@code <} cuts the text off and
   * {@code [} leaves the rest untranslated, without even an error.
   */
  private static final String STREAM_RESERVED = "\\[]{}^$/@<>";

  /** Backslash-escape the stream metacharacters in raw text, as apertium-destxt does. */
  static String escapeStream(String text) {
    StringBuilder sb = new StringBuilder(text.length() + 8);
    for (int i = 0; i < text.length(); i++) {
      char c = text.charAt(i);
      if (STREAM_RESERVED.indexOf(c) >= 0) sb.append('\\');
      sb.append(c);
    }
    return sb.toString();
  }

  /**
   * Remove the stream escapes that survive to the final stage's output ({@code \X} → {@code X}),
   * as apertium-retxt does. Run after {@link #applyMarkerPref}, which recognizes the escaped
   * unknown-word markers ({@code \@word}) itself.
   */
  static String unescapeStream(String text) {
    if (text == null || text.indexOf('\\') < 0) return text;
    StringBuilder once = new StringBuilder(text.length());
    for (int i = 0; i < text.length(); i++) {
      char c = text.charAt(i);
      if (c == '\\' && i + 1 < text.length()) c = text.charAt(++i);
      once.append(c);
    }
    // lttoolbox's fallback for a word it can't generate ("#joan@correu.cat", "#$20") writes the
    // still-escaped text through its escaper a second time, so those words keep one level
    // ("\@") after the pass above. Drop a backslash left in front of a stream character; the
    // only casualty is a user-typed backslash directly before one of them.
    StringBuilder out = new StringBuilder(once.length());
    for (int i = 0; i < once.length(); i++) {
      char c = once.charAt(i);
      if (c == '\\' && i + 1 < once.length() && once.charAt(i + 1) != '\\'
          && STREAM_RESERVED.indexOf(once.charAt(i + 1)) >= 0) {
        continue;
      }
      out.append(c);
    }
    return out.toString();
  }

  /**
   * Post-process Apertium output to honor the legacy "mark unknown words" toggle.
   *
   * <p>Apertium's generator flags words it couldn't fully process with three markers:
   * {@code @word} (no bilingual translation), {@code #word} (bilingual matched but the
   * morphological generator couldn't inflect the result), and {@code *word} (analyzer
   * didn't know the source word). Individual stages may emit the marker escaped
   * ({@code \@}, {@code \#}, {@code \*}) or plain depending on where in the pipeline they
   * were inserted. We match either form at word boundaries (start of string or after
   * whitespace, immediately preceding a non-whitespace char) and normalize to a single
   * asterisk when {@code displayMarks} is true, or strip them outright when false.
   */
  private static final java.util.regex.Pattern UNKNOWN_WORD_MARKER =
      java.util.regex.Pattern.compile("(?:^|(?<=\\s))\\\\?[@#*](?=\\S)");

  static String applyMarkerPref(String text, boolean displayMarks) {
    if (text == null) return null;
    return UNKNOWN_WORD_MARKER.matcher(text).replaceAll(displayMarks ? "*" : "");
  }

  static List<List<String>> parseModeLine(String modeLine, File pairBaseDir) {
    List<List<String>> stages = new ArrayList<>();
    for (String raw : modeLine.split("\\|")) {
      List<String> tokens = tokenize(raw.trim());
      if (tokens.isEmpty()) continue;
      // Mode files use $1 / $2 as placeholders apertium(1) substitutes from its CLI args.
      // $1 is the lt-proc-mode flag (default -g for "generator"); $2 is usually empty.
      List<String> rewritten = new ArrayList<>(tokens.size());
      rewritten.add(tokens.get(0));
      for (int i = 1; i < tokens.size(); i++) {
        String t = tokens.get(i);
        if (t.equals("$1")) {
          rewritten.add("-g");
        } else if (t.equals("$2")) {
          // skip — empty substitution
        } else {
          rewritten.add(rewritePath(t, pairBaseDir));
        }
      }
      stages.add(rewritten);
    }
    return stages;
  }

  static String rewritePath(String token, File pairBaseDir) {
    if (token.startsWith("-") || token.isEmpty()) return token;
    if (token.startsWith("/usr/share/apertium/")) {
      // Debian layout: /usr/share/apertium/apertium-<pkg>/<file> → pair dir root
      return new File(pairBaseDir, new File(token).getName()).getAbsolutePath();
    }
    if (token.startsWith("/")) return token;
    // Relative path (old-format JAR layout like "data/<file>.bin"). Resolve against pair base.
    if (token.contains("/") || token.endsWith(".bin") || token.endsWith(".mode")
        || token.endsWith(".t1x") || token.endsWith(".t2x") || token.endsWith(".t3x")
        || token.endsWith(".rlx") || token.endsWith(".rtx") || token.endsWith(".prob")) {
      return new File(pairBaseDir, token).getAbsolutePath();
    }
    return token;
  }

  private static List<String> tokenize(String cmd) {
    List<String> out = new ArrayList<>();
    Matcher m = SHELL_TOKEN.matcher(cmd);
    while (m.find()) {
      if (m.group(1) != null) out.add(m.group(1));
      else if (m.group(2) != null) out.add(m.group(2));
      else out.add(m.group(3));
    }
    return out;
  }

  private String runPipeline(List<List<String>> stages, String input) throws IOException {
    if (stages.isEmpty()) return input;

    List<Process> running = new ArrayList<>(stages.size());
    List<StderrCapture> stderrs = new ArrayList<>(stages.size());
    try {
      Process prev = null;
      for (int i = 0; i < stages.size(); i++) {
        List<String> stage = stages.get(i);
        String toolName = stage.get(0);
        String libName = TOOL_LIBS.get(toolName);
        if (libName == null) {
          throw new IOException("no native binary mapping for tool '" + toolName + "'");
        }
        File exe = new File(nativeLibraryDir, libName);
        if (!exe.canExecute()) {
          throw new IOException("native binary not executable: " + exe);
        }

        List<String> argv = new ArrayList<>(stage.size());
        argv.add(exe.getAbsolutePath());
        argv.addAll(stage.subList(1, stage.size()));
        ProcessBuilder pb = new ProcessBuilder(argv).redirectErrorStream(false);
        pb.environment().put("LD_LIBRARY_PATH", nativeLibraryDir);

        Process p = pb.start();
        running.add(p);
        // Drain stderr from the start: a stage that writes a lot of diagnostics must never
        // block on a full pipe, and its first lines are what we report if the stage fails.
        stderrs.add(new StderrCapture(p.getErrorStream(), "apertium-stderr-" + i));
        Log.d(TAG, "stage " + i + ": " + argv);

        final Process source = prev;
        final Process dest = p;
        if (source == null) {
          // Feed the user's input to the first stage's stdin. The trailing newline is
          // load-bearing: without it lt-proc emits U+FFFF as an end-of-stream sentinel,
          // which renders as a "tofu" box in the output TextInputEditText.
          try (OutputStream os = dest.getOutputStream()) {
            os.write(input.getBytes(StandardCharsets.UTF_8));
            if (input.isEmpty() || input.charAt(input.length() - 1) != '\n') {
              os.write('\n');
            }
          }
        } else {
          // Pipe previous stage's stdout to this stage's stdin on a background thread.
          Thread t = new Thread(() -> {
            try (InputStream in = source.getInputStream();
                 OutputStream out = dest.getOutputStream()) {
              byte[] buf = new byte[8192];
              int n;
              while ((n = in.read(buf)) != -1) out.write(buf, 0, n);
            } catch (IOException e) {
              Log.w(TAG, "pipe error between stages", e);
            }
          }, "apertium-pipe-" + i);
          t.setDaemon(true);
          t.start();
        }
        prev = p;
      }

      // Drain the final stage's stdout.
      StringBuilder sb = new StringBuilder();
      try (BufferedReader r = new BufferedReader(
          new InputStreamReader(prev.getInputStream(), StandardCharsets.UTF_8))) {
        char[] buf = new char[4096];
        int n;
        while ((n = r.read(buf)) != -1) sb.append(buf, 0, n);
      }
      for (Process p : running) {
        try {
          p.waitFor();
        } catch (InterruptedException e) {
          Thread.currentThread().interrupt();
          throw new InterruptedIOException("interrupted while waiting for the Apertium pipeline");
        }
      }
      checkStages(stages, running, stderrs);
      return sb.toString();
    } finally {
      for (Process p : running) {
        if (p.isAlive()) p.destroyForcibly();
      }
    }
  }

  /** Exit status of a stage killed by SIGPIPE (128 + 13): a casualty of a later stage dying. */
  private static final int EXIT_SIGPIPE = 141;

  /**
   * Fail the translation if any stage exited non-zero or reported a malformed stream. A failed
   * stage has already cut the text short (lt-proc flushes what it had before bailing out), so
   * returning the output would silently show a truncated translation. Reports the stage that
   * actually failed: stages upstream of a crash die of SIGPIPE and are skipped as casualties.
   */
  private static void checkStages(List<List<String>> stages, List<Process> running,
                                  List<StderrCapture> stderrs) throws IOException {
    int n = running.size();
    int[] codes = new int[n];
    String[] errs = new String[n];
    boolean[] failed = new boolean[n];
    for (int i = 0; i < n; i++) {
      codes[i] = running.get(i).exitValue();
      errs[i] = stderrs.get(i).text();
      failed[i] = codes[i] != 0 || isStreamError(errs[i]);
    }
    int culprit = -1;
    for (int i = 0; i < n && culprit < 0; i++) {
      if (failed[i] && codes[i] != EXIT_SIGPIPE) culprit = i;
    }
    for (int i = 0; i < n && culprit < 0; i++) {
      if (failed[i]) culprit = i;
    }
    if (culprit < 0) return;

    StringBuilder msg = new StringBuilder()
        .append("Apertium stage ").append(culprit + 1)
        .append(" (").append(stages.get(culprit).get(0)).append(") failed");
    if (codes[culprit] != 0) msg.append(" with exit code ").append(codes[culprit]);
    String firstLine = errs[culprit].split("\n", 2)[0].trim();
    if (!firstLine.isEmpty()) msg.append(": ").append(firstLine);
    Log.w(TAG, msg + (errs[culprit].isEmpty() ? "" : "\n" + errs[culprit]));
    throw new IOException(msg.toString());
  }

  /** lttoolbox, apertium and hfst all report bad stream syntax as "... malformed input stream". */
  static boolean isStreamError(String stderr) {
    return stderr != null && stderr.toLowerCase(Locale.ROOT).contains("malformed input stream");
  }

  /**
   * Drains one stage's stderr on a daemon thread, keeping the first {@link #MAX_BYTES} for
   * the error report. Draining (rather than leaving stderr unread) also means a stage that
   * writes many warnings can't fill the pipe and hang the whole pipeline.
   */
  private static final class StderrCapture {
    private static final int MAX_BYTES = 2048;
    private final ByteArrayOutputStream head = new ByteArrayOutputStream();
    private final Thread thread;

    StderrCapture(InputStream in, String name) {
      thread = new Thread(() -> {
        byte[] buf = new byte[1024];
        try (InputStream is = in) {
          int r;
          while ((r = is.read(buf)) != -1) {
            synchronized (head) {
              int room = MAX_BYTES - head.size();
              if (room > 0) head.write(buf, 0, Math.min(r, room));
            }
          }
        } catch (IOException ignored) {
          // Stage destroyed mid-read; what we captured is all there is.
        }
      }, name);
      thread.setDaemon(true);
      thread.start();
    }

    /** Captured text; waits briefly for the drain thread to reach EOF after the stage exits. */
    String text() {
      try {
        thread.join(2000);
      } catch (InterruptedException e) {
        Thread.currentThread().interrupt();
      }
      synchronized (head) {
        return new String(head.toByteArray(), StandardCharsets.UTF_8).trim();
      }
    }
  }

  private static String readFirstNonEmptyLine(File modeFile) throws IOException {
    try (BufferedReader r = new BufferedReader(
        new InputStreamReader(new java.io.FileInputStream(modeFile), StandardCharsets.UTF_8))) {
      String line;
      while ((line = r.readLine()) != null) {
        String trimmed = line.trim();
        if (!trimmed.isEmpty() && !trimmed.startsWith("#")) return trimmed;
      }
    }
    return null;
  }
}
