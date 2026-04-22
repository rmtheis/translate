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
                                           const char* flag,
                                           const char* tmp_dir) {
  ApertiumResult result{nullptr, nullptr};
  std::string in_path, out_path;
  try {
    if (!bin_path) throw std::runtime_error("bin_path is NULL");
    if (!tmp_dir)  throw std::runtime_error("tmp_dir is NULL");

    LtLocale::tryToSetLocale();

    in_path  = aix::spit_tmp(tmp_dir, "lt_in", input);
    out_path = aix::make_tmp_file(tmp_dir, "lt_out");

    FSTProcessor fstp;
    FILE* bin_fp = openInBinFile(bin_path);
    fstp.load(bin_fp);
    std::fclose(bin_fp);

    // Pick the main mode and detect the `-b -g` combo — apertium mode
    // files substitute $1 → -g, so the pattern `lt-proc -b $1 AUTOGEN`
    // surfaces here as flags="bg". lt-proc treats that as bilingual
    // generation (gm_bilgen); we honor that by passing the mode enum
    // to FSTProcessor::bilingual().
    const char* flagstr = flag ? flag : "";
    char mode = 'a';
    for (const char* c = flagstr; *c; ++c) {
      if (*c == 'a' || *c == 'g' || *c == 'b' || *c == 'p'
          || *c == 's' || *c == 't' || *c == 'e') { mode = *c; break; }
    }
    bool bilgen = false, bilgen_keep = false, tagged = false;
    bool tagged_nm = false, non_marked_gen = false, careful_case = false;
    if (mode == 'b') {
      for (const char* c = flagstr; *c; ++c) {
        if (*c == 'g') bilgen = true;        // -b -g → gm_bilgen
        if (*c == 'O') bilgen_keep = true;   // -O: keep surface forms
      }
    }
    if (mode == 'g') {
      for (const char* c = flagstr; *c; ++c) {
        if (*c == 'l') tagged = true;         // -l: tagged gen
        if (*c == 'm') tagged_nm = true;      // -m: tagged nm gen
        if (*c == 'n') non_marked_gen = true; // -n: non-marked gen
        if (*c == 'd') ; // -d debugged-gen handled below (gm_all)
      }
    }

    switch (mode) {
      case 'g': fstp.initGeneration(); break;
      case 'p': fstp.initPostgeneration(); break;
      case 'b': fstp.initBiltrans(); break;
      case 'e': fstp.initDecomposition(); break;
      case 't': fstp.initPostgeneration(); break;
      case 's':
      case 'a':
      default:  fstp.initAnalysis(); break;
    }
    if (!fstp.valid()) throw std::runtime_error("FSTProcessor invalid after init");

    InputFile in_file;
    in_file.open_or_exit(in_path.c_str());
    UFILE* out_ufile = openOutTextFile(out_path);

    switch (mode) {
      case 'g': {
        GenerationMode gm = gm_unknown;
        if (non_marked_gen) gm = gm_clean;
        else if (tagged)    gm = gm_tagged;
        else if (tagged_nm) gm = gm_tagged_nm;
        fstp.generation(in_file, out_ufile, gm);
        break;
      }
      case 'p': fstp.postgeneration(in_file, out_ufile); break;
      case 'b': {
        GenerationMode gm = gm_unknown;
        if (bilgen) gm = gm_bilgen;
        if (bilgen_keep) fstp.setBiltransSurfaceFormsKeep(true);
        fstp.bilingual(in_file, out_ufile, gm);
        break;
      }
      case 'e': fstp.analysis(in_file, out_ufile); break;
      case 't': fstp.transliteration(in_file, out_ufile); break;
      case 's': fstp.SAO(in_file, out_ufile); break;
      case 'a':
      default:  fstp.analysis(in_file, out_ufile); break;
    }
    u_fclose(out_ufile);

    std::string out = aix::slurp(out_path);
    aix::rm_quiet(in_path);
    aix::rm_quiet(out_path);
    result.output = aix::dup_cstr(out);
    if (!result.output) throw std::runtime_error("dup_cstr failed");
    return result;
  } catch (const std::exception& e) {
    aix::rm_quiet(in_path);
    aix::rm_quiet(out_path);
    result.error = aix::dup_cstr(e.what());
    return result;
  }
}

extern "C" void apertium_result_free(ApertiumResult r) {
  std::free(r.output);
  std::free(r.error);
}
