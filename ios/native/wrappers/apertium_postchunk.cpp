// apertium-ios-native/wrappers/apertium_postchunk.cpp
//
// Library-ified replacement for apertium's apertium-postchunk binary.

#include "apertium_core.h"
#include "wrapper_common.h"

#include <apertium/postchunk.h>
#include <lttoolbox/file_utils.h>
#include <lttoolbox/input_file.h>
#include <lttoolbox/lt_locale.h>

#include <unicode/ustdio.h>

extern "C" ApertiumResult apertium_postchunk(const char* input,
                                             const char* t3x_file,
                                             const char* datafile,
                                             const char* flags,
                                             const char* tmp_dir) {
  return aix::run_wrapper([&] {
    if (!t3x_file) throw std::runtime_error("t3x_file is NULL");
    if (!datafile) throw std::runtime_error("datafile is NULL");
    if (!tmp_dir)  throw std::runtime_error("tmp_dir is NULL");

    LtLocale::tryToSetLocale();

    Postchunk pc;
    for (const char* p = flags ? flags : ""; *p; ++p) {
      switch (*p) {
        case 't': pc.setTrace(true); break;
        case 'w': pc.setDictionaryCase(true); break;
        case 'z': pc.setNullFlush(true); break;
        default:
          throw std::runtime_error(std::string("unknown postchunk flag: ") + *p);
      }
    }

    aix::ensure_exists(t3x_file);
    aix::ensure_exists(datafile);
    pc.read(t3x_file, datafile);

    aix::TmpFile in_tmp = aix::spit_tmp(tmp_dir, "pchk_in", input);
    aix::TmpFile out_tmp(tmp_dir, "pchk_out");

    InputFile in_file;
    in_file.open_or_exit(in_tmp.c_str());
    {
      aix::UFilePtr out(openOutTextFile(out_tmp.path()));
      pc.postchunk(in_file, out.get());
    }
    return aix::slurp(out_tmp.path());
  });
}
