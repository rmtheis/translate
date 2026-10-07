// apertium-ios-native/wrappers/lrx_proc.cpp
//
// Library-ified replacement for apertium-lex-tools's lrx-proc binary.

#include "apertium_core.h"
#include "wrapper_common.h"

#include <lrx_processor.h>

#include <lttoolbox/file_utils.h>
#include <lttoolbox/input_file.h>
#include <lttoolbox/lt_locale.h>

#include <unicode/ustdio.h>

extern "C" ApertiumResult apertium_lrx_proc(const char* input,
                                            const char* bin_path,
                                            const char* flags,
                                            const char* tmp_dir) {
  return aix::run_wrapper([&] {
    if (!bin_path) throw std::runtime_error("bin_path is NULL");
    if (!tmp_dir)  throw std::runtime_error("tmp_dir is NULL");
    aix::ensure_exists(bin_path);  // openInBinFile exits the app on a missing file

    LtLocale::tryToSetLocale();

    LRXProcessor p;
    for (const char* c = flags ? flags : ""; *c; ++c) {
      switch (*c) {
        case 't': p.setTraceMode(true); break;
        case 'd': p.setDebugMode(true); break;
        case 'z': p.setNullFlush(true); break;
        case 'm': /* no-op for backwards compatibility */ break;
        default:
          throw std::runtime_error(std::string("unknown lrx-proc flag: ") + *c);
      }
    }

    {
      aix::FilePtr fst(openInBinFile(bin_path));
      p.load(fst.get());
    }
    p.init();

    aix::TmpFile in_tmp = aix::spit_tmp(tmp_dir, "lrx_in", input);
    aix::TmpFile out_tmp(tmp_dir, "lrx_out");

    InputFile in_file;
    in_file.open_or_exit(in_tmp.c_str());
    {
      aix::UFilePtr out(openOutTextFile(out_tmp.path()));
      p.process(in_file, out.get());
    }
    return aix::slurp(out_tmp.path());
  });
}
