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
  return aix::run_wrapper([&] {
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

    aix::TmpFile in_tmp = aix::spit_tmp(tmp_dir, "ltm_in", input);
    aix::TmpFile out_tmp(tmp_dir, "ltm_out");

    // Same setup as lt_merge.cc's main(): no dictionary is loaded;
    // quoteMerge/quoteUnmerge only use FSTProcessor's stream reader.
    FSTProcessor fstp;
    fstp.setNullFlush(true);
    fstp.initBiltrans();

    InputFile in_file;
    in_file.open_or_exit(in_tmp.c_str());
    {
      aix::UFilePtr out(openOutTextFile(out_tmp.path()));
      if (unmerge) fstp.quoteUnmerge(in_file, out.get());
      else         fstp.quoteMerge(in_file, out.get());
    }
    return aix::slurp(out_tmp.path());
  });
}
