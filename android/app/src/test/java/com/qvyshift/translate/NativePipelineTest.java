package com.qvyshift.translate;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.io.File;
import java.util.List;

public class NativePipelineTest {

  private final File pairDir = new File("/data/user/0/com.qvyshift.translate/files/packages2/apertium-eng-spa");

  @Test
  public void rewritesDebianAbsolutePathsToPairDirBasename() {
    assertEquals(
        pairDir + "/eng-spa.automorf.bin",
        NativePipeline.rewritePath("/usr/share/apertium/apertium-eng-spa/eng-spa.automorf.bin", pairDir));
  }

  @Test
  public void rewritesOldJarRelativePaths() {
    assertEquals(
        pairDir + "/data/en-es.automorf.bin",
        NativePipeline.rewritePath("data/en-es.automorf.bin", pairDir));
  }

  @Test
  public void leavesFlagsAlone() {
    assertEquals("-b", NativePipeline.rewritePath("-b", pairDir));
    assertEquals("--verbose", NativePipeline.rewritePath("--verbose", pairDir));
  }

  @Test
  public void leavesArbitraryAbsolutePathsOutsideUsrShareApertiumAlone() {
    assertEquals("/tmp/scratch", NativePipeline.rewritePath("/tmp/scratch", pairDir));
  }

  @Test
  public void parseSingleStage() {
    List<List<String>> stages = NativePipeline.parseModeLine(
        "lt-proc -w '/usr/share/apertium/apertium-eng-spa/eng-spa.automorf.bin'", pairDir);
    assertEquals(1, stages.size());
    assertEquals(3, stages.get(0).size());
    assertEquals("lt-proc", stages.get(0).get(0));
    assertEquals("-w", stages.get(0).get(1));
    assertEquals(pairDir + "/eng-spa.automorf.bin", stages.get(0).get(2));
  }

  @Test
  public void parseFullEngSpaPipeline() {
    String mode = "lt-proc data/en-es.automorf.bin | apertium-tagger -g $2 data/en-es.prob"
        + " | apertium-pretransfer"
        + " | apertium-transfer -n data/apertium-en-es.en-es.genitive.t1x data/en-es.genitive.bin"
        + " | apertium-transfer data/apertium-en-es.en-es.t1x data/en-es.t1x.bin data/en-es.autobil.bin"
        + " | apertium-interchunk data/apertium-en-es.en-es.t2x data/en-es.t2x.bin"
        + " | apertium-postchunk data/apertium-en-es.en-es.t3x data/en-es.t3x.bin"
        + " | lt-proc $1 data/en-es.autogen.bin"
        + " | lt-proc -p data/en-es.autopgen.bin";
    List<List<String>> stages = NativePipeline.parseModeLine(mode, pairDir);
    assertEquals(9, stages.size());
    assertEquals("lt-proc", stages.get(0).get(0));
    // $2 placeholder should have been dropped
    List<String> tagger = stages.get(1);
    assertEquals("apertium-tagger", tagger.get(0));
    assertTrue("$2 should be stripped: " + tagger, !tagger.contains("$2"));
    // Relative paths should be rewritten to absolute under pair dir
    assertEquals(pairDir + "/data/en-es.automorf.bin", stages.get(0).get(1));
    // $1 should be replaced with "-g" for the generator stage
    List<String> autogen = stages.get(7);
    assertEquals("lt-proc", autogen.get(0));
    assertEquals("-g", autogen.get(1));
    assertEquals(pairDir + "/data/en-es.autogen.bin", autogen.get(2));
    assertEquals(pairDir + "/data/en-es.autopgen.bin", stages.get(8).get(2));
  }

  @Test
  public void parseModernDebianPipelineWithNewTools() {
    // Drawn from apertium-dan-nor's dan-nob.mode which uses cg-proc / lsx-proc / rtx-proc.
    String mode = "lt-proc -e -w '/usr/share/apertium/apertium-dan-nor/dan-nob.automorf.bin'"
        + " | cg-proc '/usr/share/apertium/apertium-dan-nor/dan-nor.seg.rlx.bin'"
        + " | lsx-proc '/usr/share/apertium/apertium-dan-nor/dan-nob.autoseq.bin'"
        + " | rtx-proc '/usr/share/apertium/apertium-dan-nor/dan-nob.rtx.bin'"
        + " | lt-proc $1 '/usr/share/apertium/apertium-dan-nor/dan-nob.autogen.bin'";
    File pairDanNor = new File("/fake/apertium-dan-nor");
    List<List<String>> stages = NativePipeline.parseModeLine(mode, pairDanNor);
    assertEquals(5, stages.size());
    assertEquals("cg-proc", stages.get(1).get(0));
    assertEquals("lsx-proc", stages.get(2).get(0));
    assertEquals("rtx-proc", stages.get(3).get(0));
    assertEquals("/fake/apertium-dan-nor/dan-nob.rtx.bin", stages.get(3).get(1));
    // $1 replaced with -g
    assertTrue(!stages.get(4).contains("$1"));
    assertEquals("-g", stages.get(4).get(1));
    assertEquals("/fake/apertium-dan-nor/dan-nob.autogen.bin", stages.get(4).get(2));
  }

  @Test
  public void applyMarkerPrefNormalizesToAsteriskWhenShowing() {
    // Escaped \@ (bilingual fail)
    assertEquals("*good morning",
        NativePipeline.applyMarkerPref("\\@good morning", true));
    // Mix of escaped \@ and \# in one sentence
    assertEquals("*The *gato *ser *happy",
        NativePipeline.applyMarkerPref("\\@The \\#gato \\#ser \\@happy", true));
    // Unescaped # (seen in real output from the native pipeline)
    assertEquals(" *Querer *agua.",
        NativePipeline.applyMarkerPref(" #Querer #agua.", true));
    // Escaped \* stays *
    assertEquals("*foo",
        NativePipeline.applyMarkerPref("\\*foo", true));
    // No markers — no change
    assertEquals("Hola mundo",
        NativePipeline.applyMarkerPref("Hola mundo", true));
  }

  @Test
  public void applyMarkerPrefStripsWhenHiding() {
    assertEquals("good morning",
        NativePipeline.applyMarkerPref("\\@good morning", false));
    assertEquals("The gato ser happy",
        NativePipeline.applyMarkerPref("\\@The \\#gato \\#ser \\@happy", false));
    assertEquals(" Querer agua.",
        NativePipeline.applyMarkerPref(" #Querer #agua.", false));
    assertEquals("foo",
        NativePipeline.applyMarkerPref("\\*foo", false));
    assertEquals("Hola mundo",
        NativePipeline.applyMarkerPref("Hola mundo", false));
  }

  @Test
  public void applyMarkerPrefIgnoresNonMarkerAsterisks() {
    // Standalone * separated by whitespace — not a marker
    assertEquals("a * b * c", NativePipeline.applyMarkerPref("a * b * c", true));
    assertEquals("a * b * c", NativePipeline.applyMarkerPref("a * b * c", false));
    // @ inside a word (e.g. email-like) — not a marker
    assertEquals("me@example.com", NativePipeline.applyMarkerPref("me@example.com", true));
    assertEquals("me@example.com", NativePipeline.applyMarkerPref("me@example.com", false));
  }

  @Test
  public void applyMarkerPrefHandlesNull() {
    org.junit.Assert.assertNull(NativePipeline.applyMarkerPref(null, true));
    org.junit.Assert.assertNull(NativePipeline.applyMarkerPref(null, false));
  }

  @Test
  public void escapeStreamEscapesExactlyTheDestxtSet() {
    // Same set apertium-destxt escapes: \ [ ] { } ^ $ / @ < >
    assertEquals("Ci vediamo il 5\\/9 a mario\\@gmail.com, costa 10\\$",
        NativePipeline.escapeStream("Ci vediamo il 5/9 a mario@gmail.com, costa 10$"));
    assertEquals("\\^_\\^ \\{x\\} \\[y\\] \\<3 \\> a\\\\b",
        NativePipeline.escapeStream("^_^ {x} [y] <3 > a\\b"));
    // Not stream syntax: left alone (the unknown-word markers are handled on output).
    assertEquals("#tag *s* +39 ~5 50% l'acqua \n",
        NativePipeline.escapeStream("#tag *s* +39 ~5 50% l'acqua \n"));
  }

  @Test
  public void unescapeStreamRoundTripsEscapeStream() {
    String[] samples = {
        "Vai su https://www.regione.sardegna.it e leggi",
        "C:\\Users\\me \\ trailing\\",
        "x < 5 > y [nota] {amico} ^_^ $20 @user",
        "Ciao \uD83D\uDE00 come stai \uD83D\uDC4D\uD83C\uDFFD",
        "",
    };
    for (String s : samples) {
      assertEquals(s, NativePipeline.unescapeStream(NativePipeline.escapeStream(s)));
    }
    org.junit.Assert.assertNull(NativePipeline.unescapeStream(null));
  }

  @Test
  public void unescapeAfterMarkerPrefKeepsMarkersAndRestoresLiterals() {
    // Real srd-ita-style output: an escaped bilingual-miss marker at a word start, and an
    // escaped literal "/" and "@" that came from the (escaped) user input.
    String raw = "\\@Cras 5\\/9 in Casteddu, iscrie a mario\\@gmail.com";
    assertEquals("*Cras 5/9 in Casteddu, iscrie a mario@gmail.com",
        NativePipeline.unescapeStream(NativePipeline.applyMarkerPref(raw, true)));
    assertEquals("Cras 5/9 in Casteddu, iscrie a mario@gmail.com",
        NativePipeline.unescapeStream(NativePipeline.applyMarkerPref(raw, false)));
  }

  @Test
  public void unescapeUndoesTheGeneratorsDoubleEscapeOnUnprocessedWords() {
    // Real cat-eng output: the generator couldn't inflect the (unknown) email address and
    // wrote its still-escaped form through lttoolbox's escaper again.
    assertEquals(" Writes at *joan@correu.cat now\n", NativePipeline.unescapeStream(
        NativePipeline.applyMarkerPref(" Writes at #joan\\\\\\@correu.cat now\n", true)));
    // Real spa-eng output for "cuesta 20$".
    assertEquals("It costs *$20 today", NativePipeline.unescapeStream(
        NativePipeline.applyMarkerPref("It costs #\\\\\\$20 today", true)));
    // Doubled backslashes that aren't in front of a stream character are left alone.
    assertEquals("C:\\Users", NativePipeline.unescapeStream("C:\\\\Users"));
  }

  @Test
  public void caretTailStartHoldsBackCaretsAfterTheLastWord() {
    // lrx-proc mis-reads an escaped ^ in the final blank; that tail bypasses the pipeline.
    assertEquals(10, NativePipeline.caretTailStart("come stai? ^_^"));   // head "come stai?"
    assertEquals(6, NativePipeline.caretTailStart("Grazie ^^"));
    assertEquals(4, NativePipeline.caretTailStart("Ciao\n^^\n"));
    assertEquals(7, NativePipeline.caretTailStart("Ciao \uD83D\uDE00 ^^"));        // emoji is not a word
    assertEquals(5, NativePipeline.caretTailStart("x ^ y ^"));
    assertEquals(0, NativePipeline.caretTailStart("^_^"));                // nothing to translate
    // A ^ before the last word is fine inside the stream: nothing held back.
    assertEquals(-1, NativePipeline.caretTailStart("a ^b"));
    assertEquals(-1, NativePipeline.caretTailStart("^_^ ciao"));
    assertEquals(-1, NativePipeline.caretTailStart("5/9 a mario@gmail.com, 10$"));
    assertEquals(-1, NativePipeline.caretTailStart(""));
  }

  @Test
  public void recognizesStreamErrorsOnStderr() {
    assertTrue(NativePipeline.isStreamError("Error: Malformed input stream."));
    assertTrue(NativePipeline.isStreamError("Error: malformed input stream: bad tag\n"));
    assertTrue(!NativePipeline.isStreamError("Warning: Soft limit of 500 cohorts reached"));
    assertTrue(!NativePipeline.isStreamError(""));
    assertTrue(!NativePipeline.isStreamError(null));
  }

  @Test
  public void emptyStagesIgnored() {
    List<List<String>> stages = NativePipeline.parseModeLine(" | lt-proc data/x.bin | ", pairDir);
    assertEquals(1, stages.size());
    assertEquals("lt-proc", stages.get(0).get(0));
  }
}
