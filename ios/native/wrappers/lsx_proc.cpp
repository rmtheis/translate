// apertium-ios-native/wrappers/lsx_proc.cpp
//
// Library-ified replacement for apertium-separable's lsx-proc binary.

#include "apertium_core.h"
#include "wrapper_common.h"

#include <lsx_processor.h>

#include <lttoolbox/file_utils.h>
#include <lttoolbox/input_file.h>
#include <lttoolbox/lt_locale.h>

#include <unicode/ustdio.h>

extern "C" ApertiumResult apertium_lsx_proc(const char* input,
                                            const char* bin_path,
                                            const char* flags,
                                            const char* tmp_dir) {
  return aix::run_wrapper([&] {
    if (!bin_path) throw std::runtime_error("bin_path is NULL");
    if (!tmp_dir)  throw std::runtime_error("tmp_dir is NULL");
    aix::ensure_exists(bin_path);  // openInBinFile exits the app on a missing file

    LtLocale::tryToSetLocale();

    LSXProcessor p;
    for (const char* c = flags ? flags : ""; *c; ++c) {
      switch (*c) {
        case 'p': p.setPostgenMode(true); break;
        case 'r': p.setRepeatMode(true); break;
        case 'w': p.setDictionaryCaseMode(true); break;
        case 'z': p.setNullFlush(true); break;
        default:
          throw std::runtime_error(std::string("unknown lsx-proc flag: ") + *c);
      }
    }

    {
      aix::FilePtr fst(openInBinFile(bin_path));
      p.load(fst.get());
    }

    aix::TmpFile in_tmp = aix::spit_tmp(tmp_dir, "lsx_in", input);
    aix::TmpFile out_tmp(tmp_dir, "lsx_out");

    InputFile in_file;
    in_file.open_or_exit(in_tmp.c_str());
    {
      aix::UFilePtr out(openOutTextFile(out_tmp.path()));
      p.process(in_file, out.get());
    }
    return aix::slurp(out_tmp.path());
  });
}
