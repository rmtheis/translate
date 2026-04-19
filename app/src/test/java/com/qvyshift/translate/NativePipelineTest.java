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
    // $1 dropped
    assertTrue(!stages.get(4).contains("$1"));
    assertEquals("/fake/apertium-dan-nor/dan-nob.autogen.bin", stages.get(4).get(1));
  }

  @Test
  public void emptyStagesIgnored() {
    List<List<String>> stages = NativePipeline.parseModeLine(" | lt-proc data/x.bin | ", pairDir);
    assertEquals(1, stages.size());
    assertEquals("lt-proc", stages.get(0).get(0));
  }
}
