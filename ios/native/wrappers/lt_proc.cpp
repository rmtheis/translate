// apertium-ios-native/wrappers/lt_proc.cpp
//
// Library-ified replacement for lttoolbox's lt-proc binary.

#include "apertium_core.h"
#include "wrapper_common.h"

#include <lttoolbox/file_utils.h>
#include <lttoolbox/fst_processor.h>
#include <lttoolbox/input_file.h>
#include <lttoolbox/lt_locale.h>

#include <unicode/ustdio.h>

extern "C" ApertiumResult apertium_lt_proc(const char* input,
                                           const char* bin_path,
                                           const char* flags,
                                           int max_analyses,
                                           int max_weight_classes,
                                           int compound_max_elements,
                                           const char* tmp_dir) {
  return aix::run_wrapper([&] {
    if (!bin_path) throw std::runtime_error("bin_path is NULL");
    if (!tmp_dir)  throw std::runtime_error("tmp_dir is NULL");
    aix::ensure_exists(bin_path);  // openInBinFile exits the app on a missing file

    LtLocale::tryToSetLocale();

    const std::string fl = flags ? flags : "";
    for (char c : fl) {
      if (!std::strchr("abcdeglmnoOpxstzwCIW", c))
        throw std::runtime_error(std::string("unknown lt-proc flag: ") + c);
    }
    auto has = [&](char c) { return fl.find(c) != std::string::npos; };

    // Mode selection, step for step as in lt_proc.cc's main(): the checks run
    // in this fixed order whatever the command-line order, so `$1 -b` (-g -b)
    // is bilingual generation like `-b -g`. Where lt-proc prints its usage
    // and exits, fail the stage.
    FSTProcessor fstp;
    GenerationMode bilmode = gm_unknown;
    char cmd = 0;
    auto usage = [] {
      throw std::runtime_error("conflicting lt-proc mode flags");
    };
    if (has('a')) cmd = 'a';
    if (has('b')) {
      if (cmd) usage();
      cmd = 'b';
    }
    if (has('o')) {
      if (cmd && cmd != 'b') usage();
      if (!cmd) cmd = 'b';
      fstp.setBiltransSurfaceForms(true);
    }
    if (has('O')) {
      if (cmd && cmd != 'b') usage();
      if (!cmd) cmd = 'b';
      fstp.setBiltransSurfaceFormsKeep(true);
    }
    if (has('g')) {
      if (cmd && cmd != 'b') usage();
      if (!cmd) cmd = 'g';
      else if (cmd == 'b') bilmode = gm_bilgen;
    }
    if (has('e')) {
      if (cmd) usage();
      cmd = 'e';
    }
    if (has('p')) {
      if (cmd) usage();
      cmd = 'p';
    }
    if (has('x') || has('t')) {
      if (cmd) usage();
      cmd = 't';
    }
    if (has('s')) {
      if (cmd) usage();
      cmd = 's';
    }
    if (has('d')) { if (!cmd) cmd = 'g'; bilmode = gm_all; }
    if (has('l')) { if (!cmd) cmd = 'g'; bilmode = gm_tagged; }
    if (has('m')) { if (!cmd) cmd = 'g'; bilmode = gm_tagged_nm; }
    if (has('n')) { if (!cmd) cmd = 'g'; bilmode = gm_clean; }
    if (has('C')) { if (!cmd) cmd = 'g'; bilmode = gm_carefulcase; }

    fstp.setCaseSensitiveMode(has('c'));         // -c
    fstp.setUseDefaultIgnoredChars(!has('I'));   // -I
    fstp.setDisplayWeightsMode(has('W'));        // -W
    fstp.setNullFlush(has('z'));                 // -z
    fstp.setDictionaryCaseMode(has('w'));        // -w
    if (max_analyses > 0)          fstp.setMaxAnalysesValue(max_analyses);             // -N
    if (max_weight_classes > 0)    fstp.setMaxWeightClassesValue(max_weight_classes);  // -L
    if (compound_max_elements > 0) fstp.setCompoundMaxElements(compound_max_elements); // -M

    {
      aix::FilePtr bin(openInBinFile(bin_path));
      fstp.load(bin.get());
    }

    switch (cmd) {
      case 'g': fstp.initGeneration(); break;
      case 'p': case 't': fstp.initPostgeneration(); break;
      case 'b': fstp.initBiltrans(); break;
      case 'e': fstp.initDecomposition(); break;
      case 's': case 'a': default: fstp.initAnalysis(); break;
    }
    if (!fstp.valid()) throw std::runtime_error("FSTProcessor invalid after init");

    aix::TmpFile in_tmp = aix::spit_tmp(tmp_dir, "lt_in", input);
    aix::TmpFile out_tmp(tmp_dir, "lt_out");
    InputFile in_file;
    in_file.open_or_exit(in_tmp.c_str());
    {
      aix::UFilePtr out(openOutTextFile(out_tmp.path()));
      switch (cmd) {
        case 'g': fstp.generation(in_file, out.get(), bilmode); break;
        case 'p': fstp.postgeneration(in_file, out.get()); break;
        case 's': fstp.SAO(in_file, out.get()); break;
        case 't': fstp.transliteration(in_file, out.get()); break;
        case 'b': fstp.bilingual(in_file, out.get(), bilmode); break;
        case 'e': case 'a': default: fstp.analysis(in_file, out.get()); break;
      }
    }
    return aix::slurp(out_tmp.path());
  });
}

extern "C" void apertium_result_free(ApertiumResult r) {
  std::free(r.output);
  std::free(r.error);
}
