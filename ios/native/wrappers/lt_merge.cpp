// apertium-ios-native/wrappers/lt_merge.cpp
//
// Library-ified replacement for lttoolbox's lt-merge binary. nob-nno.mode
// runs it twice: plain lt-merge after merge-quotes.rlx (folds the LUs
// between the MERGE_BEG and MERGE_END tags into one <MERGED> LU) and
// `lt-merge --unmerge` after generation (restores the original surface).

#include "apertium_core.h"
#include "wrapper_common.h"

#include <lttoolbox/file_utils.h>
#include <lttoolbox/fst_processor.h>
#include <lttoolbox/input_file.h>
#include <lttoolbox/lt_locale.h>

#include <unicode/ustdio.h>

extern "C" ApertiumResult apertium_lt_merge(const char* input,
                                            const char* flags,
                                            const char* tmp_dir) {
  ApertiumResult result{nullptr, nullptr};
  std::string in_path, out_path;
  try {
    if (!tmp_dir) throw std::runtime_error("tmp_dir is NULL");

    LtLocale::tryToSetLocale();

    bool unmerge = false;
    for (const char* c = flags ? flags : ""; *c; ++c) {
      switch (*c) {
        case 'u': unmerge = true; break;
        case 'z': break;  // lt-merge always null-flushes; accept the CLI flag
        default:
          throw std::runtime_error(std::string("unknown lt-merge flag: ") + *c);
      }
    }

    in_path  = aix::spit_tmp(tmp_dir, "ltm_in", input);
    out_path = aix::make_tmp_file(tmp_dir, "ltm_out");

    // Same setup as lt_merge.cc's main(): no dictionary is loaded;
    // quoteMerge/quoteUnmerge only use FSTProcessor's stream reader.
    FSTProcessor fstp;
    fstp.setNullFlush(true);
    fstp.initBiltrans();

    InputFile in_file;
    in_file.open_or_exit(in_path.c_str());
    UFILE* out_ufile = openOutTextFile(out_path);
    if (unmerge) fstp.quoteUnmerge(in_file, out_ufile);
    else         fstp.quoteMerge(in_file, out_ufile);
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
