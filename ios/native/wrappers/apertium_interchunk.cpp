// apertium-ios-native/wrappers/apertium_interchunk.cpp
//
// Library-ified replacement for apertium's apertium-interchunk binary.

#include "apertium_core.h"
#include "wrapper_common.h"

#include <apertium/interchunk.h>
#include <lttoolbox/file_utils.h>
#include <lttoolbox/input_file.h>
#include <lttoolbox/lt_locale.h>

#include <unicode/ustdio.h>

extern "C" ApertiumResult apertium_interchunk(const char* input,
                                              const char* t2x_file,
                                              const char* datafile,
                                              const char* flags,
                                              const char* tmp_dir) {
  return aix::run_wrapper([&] {
    if (!t2x_file) throw std::runtime_error("t2x_file is NULL");
    if (!datafile) throw std::runtime_error("datafile is NULL");
    if (!tmp_dir)  throw std::runtime_error("tmp_dir is NULL");

    LtLocale::tryToSetLocale();

    Interchunk ic;
    for (const char* p = flags ? flags : ""; *p; ++p) {
      switch (*p) {
        case 't': ic.setTrace(true); break;
        case 'w': ic.setDictionaryCase(true); break;
        case 'z': ic.setNullFlush(true); break;
        default:
          throw std::runtime_error(std::string("unknown interchunk flag: ") + *p);
      }
    }

    aix::ensure_exists(t2x_file);
    aix::ensure_exists(datafile);
    ic.read(t2x_file, datafile);

    aix::TmpFile in_tmp = aix::spit_tmp(tmp_dir, "ichk_in", input);
    aix::TmpFile out_tmp(tmp_dir, "ichk_out");

    InputFile in_file;
    in_file.open_or_exit(in_tmp.c_str());
    {
      aix::UFilePtr out(openOutTextFile(out_tmp.path()));
      ic.interchunk(in_file, out.get());
    }
    return aix::slurp(out_tmp.path());
  });
}
