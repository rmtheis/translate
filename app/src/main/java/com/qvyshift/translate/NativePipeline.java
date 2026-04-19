package com.qvyshift.translate;

import android.content.Context;
import android.util.Log;

import java.io.BufferedReader;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
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
    return applyMarkerPref(runPipeline(stages, input), displayMarks);
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
        Log.d(TAG, "stage " + i + ": " + argv);

        final Process source = prev;
        final Process dest = p;
        if (source == null) {
          // Feed the user's input to the first stage's stdin.
          try (OutputStream os = dest.getOutputStream()) {
            os.write(input.getBytes(StandardCharsets.UTF_8));
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
        }
      }
      return sb.toString();
    } finally {
      for (Process p : running) {
        if (p.isAlive()) p.destroyForcibly();
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
