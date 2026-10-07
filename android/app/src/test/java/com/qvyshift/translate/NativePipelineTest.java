package com.qvyshift.translate;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;

import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
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

  @Rule
  public TemporaryFolder tmp = new TemporaryFolder();

  /** A pair dir holding empty files with these names. */
  private File pairWith(String... names) throws IOException {
    File dir = tmp.newFolder("pair");
    for (String n : names) assertTrue(new File(dir, n).createNewFile());
    return dir;
  }

  @Test
  public void transferStagesReadTheRulesTheirBinWasBuiltFrom() throws IOException {
    // The 2022 Debian oci-cat.mode: unfiltered apertium-oci-cat.oci-cat.tNx with the .bins
    // compiled from the alt-filtered oci-cat.tNx, both shipped in the pair.
    File dir = pairWith(
        "apertium-oci-cat.oci-cat.t1x", "oci-cat.t1x", "oci-cat.t1x.bin",
        "apertium-oci-cat.oci-cat.t2x", "oci-cat.t2x", "oci-cat.t2x.bin",
        "apertium-oci-cat.oci-cat.t3x", "oci-cat.t3x", "oci-cat.t3x.bin");
    String p = "'/usr/share/apertium/apertium-oci-cat/";
    String mode = "lt-proc -w " + p + "oci-cat.automorf.bin'"
        + " | apertium-transfer -b " + p + "apertium-oci-cat.oci-cat.t1x' " + p + "oci-cat.t1x.bin'"
        + " | apertium-interchunk " + p + "apertium-oci-cat.oci-cat.t2x' " + p + "oci-cat.t2x.bin'"
        + " | apertium-postchunk " + p + "apertium-oci-cat.oci-cat.t3x' " + p + "oci-cat.t3x.bin'"
        + " | lt-proc $1 " + p + "oci-cat.autogen.bin'";
    List<List<String>> stages = NativePipeline.parseModeLine(mode, dir);
    assertEquals(Arrays.asList("apertium-transfer", "-b",
        dir + "/oci-cat.t1x", dir + "/oci-cat.t1x.bin"), stages.get(1));
    assertEquals(Arrays.asList("apertium-interchunk",
        dir + "/oci-cat.t2x", dir + "/oci-cat.t2x.bin"), stages.get(2));
    assertEquals(Arrays.asList("apertium-postchunk",
        dir + "/oci-cat.t3x", dir + "/oci-cat.t3x.bin"), stages.get(3));
    // Other tools are left alone.
    assertEquals(Arrays.asList("lt-proc", "-w", dir + "/oci-cat.automorf.bin"), stages.get(0));
  }

  @Test
  public void transferStagesKeepTheModesRulesWhenTheBinsSourceIsMissing() throws IOException {
    // Every other pair ships only apertium-<pkg>.X.t1x (eng-spa's genitive.bin has no source).
    File dir = pairWith("apertium-eng-spa.eng-spa.t1x", "eng-spa.t1x.bin",
        "apertium-eng-spa.eng-spa.genitive.t1x", "eng-spa.genitive.bin");
    List<String> t1 = NativePipeline.parseModeLine("apertium-transfer -b"
        + " " + dir + "/apertium-eng-spa.eng-spa.t1x " + dir + "/eng-spa.t1x.bin", dir).get(0);
    assertEquals(dir + "/apertium-eng-spa.eng-spa.t1x", t1.get(2));
    List<String> gen = NativePipeline.parseModeLine("apertium-transfer -n"
        + " " + dir + "/apertium-eng-spa.eng-spa.genitive.t1x " + dir + "/eng-spa.genitive.bin",
        dir).get(0);
    assertEquals(dir + "/apertium-eng-spa.eng-spa.genitive.t1x", gen.get(2));
  }

  @Test
  public void rulesSwapSkipsTheValueOfTransferDashX() throws IOException {
    File dir = pairWith("apertium-x.a-b.t1x", "a-b.t1x", "a-b.t1x.bin", "a-b.autobil.bin");
    String xml = dir + "/apertium-x.a-b.t1x";
    String bin = dir + "/a-b.t1x.bin";
    String bil = dir + "/a-b.autobil.bin";
    for (List<String> opts : Arrays.asList(
        Arrays.asList("-x", bil), Arrays.asList("-bx", bil), Arrays.asList("--extended", bil),
        Arrays.asList("--ext", bil), Arrays.asList("-x" + bil), Arrays.asList("--extended=" + bil))) {
      List<String> stage = new ArrayList<>();
      stage.add("apertium-transfer");
      stage.addAll(opts);
      stage.add(xml);
      stage.add(bin);
      NativePipeline.useRulesXmlForBin(stage);
      assertEquals(opts.toString(), dir + "/a-b.t1x", stage.get(stage.size() - 2));
      assertEquals(opts.toString(), opts, stage.subList(1, 1 + opts.size()));
    }
    // An XML that already is the .bin's source, or a file argument that isn't a .bin.
    assertEquals(dir + "/a-b.t1x", NativePipeline.rulesXmlForBin(dir + "/a-b.t1x", bin));
    assertEquals(xml, NativePipeline.rulesXmlForBin(xml, dir + "/a-b.t1x"));
    assertEquals(xml, NativePipeline.rulesXmlForBin(xml, ".bin"));
  }

  private static String strip(String s) {
    return new String(
        NativePipeline.stripDependencyTags(s.getBytes(StandardCharsets.UTF_8)),
        StandardCharsets.UTF_8);
  }

  @Test
  public void stripsDependencyTagsFromCgProcOutput() {
    // Real hbs-mkd cg-proc output for "Dobar dan." (1.0.12 CI binaries and pair JAR).
    assertEquals("^Dobar<adj><pst><ma><sg><nom><ind>$ ^dan<adj><pst><ma><sg><nom><ind>$^.<sent>$\n",
        strip("^Dobar<adj><pst><ma><sg><nom><ind><#1\u21922>$ "
            + "^dan<adj><pst><ma><sg><nom><ind><#2\u21922>$^.<sent><#3\u21923>$\n"));
    // Multi-digit numbers, a tag that isn't last, non-ASCII lemmas, a multiword's parts.
    assertEquals("^\u0414\u043e\u0431\u0430\u0440<adj><m>$ ^a<n>+b<adv>$",
        strip("^\u0414\u043e\u0431\u0430\u0440<adj><#12\u2192107><m>$ ^a<n><#1\u21920>+b<adv><#2\u21921>$"));
  }

  @Test
  public void keepsEverythingThatIsNotAnUnescapedDependencyTagInALexicalUnit() {
    String[] kept = {
        // Typed by the user: escaped, inside a lexical unit and in a blank.
        "^\\<#1\u21922\\>/\\<#1\u21922\\><n>$ \\<#1\u21922\\> ^a<n>$",
        // An escaped '<' doesn't open a tag, even when an unescaped '>' follows.
        "^a\\<#1\u21922>/b<n>$",
        // A superblank, and a wordbound blank, around a tagless unit.
        "[<#1\u21922>]^dan<n>$[[<#3\u21924>]]^x<n>$[[/]]",
        // Stream syntax inside a superblank isn't a lexical unit.
        "[^a<#1\u21922>$]^dan<n>$",
        // CG syntax-function tags with the same arrow.
        "^dobar<adj><@\u2192N>$ ^dan<n><@N\u2190>$",
        // Near misses.
        "^a<#1\u2192>$^b<#\u21922>$^c<#1\u21922x>$^d<#a\u21922>$^e<#1-2>$^f<1\u21922>$"
            + "^g<# 1\u21922>$^h<#1\u2192\u21922>$^i<#1\u2192 2>$",
        // Outside a lexical unit.
        "<#1\u21922> ^a<n>$ <#2\u21923>",
        // Unterminated: a tag with no '>', a superblank with no ']', a trailing backslash.
        "^a<#1\u21922$ [b<#1\u21922> \\",
    };
    for (String s : kept) assertEquals(s, strip(s));
    // A superblank ends at its ']': a tag in the lexical unit after it is still dropped.
    assertEquals("[\\]x]^dan<n>$", strip("[\\]x]^dan<n><#2\u21920>$"));
  }

  @Test
  public void outputWithoutTheArrowIsPassedThroughUntouched() {
    byte[] plain = "^dan<n>$ \\<x\\> [y]".getBytes(StandardCharsets.UTF_8);
    assertSame(plain, NativePipeline.stripDependencyTags(plain));
    byte[] empty = new byte[0];
    assertSame(empty, NativePipeline.stripDependencyTags(empty));
  }
}
