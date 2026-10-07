// apertium-ios-native/wrappers/apertium_pretransfer.cpp
//
// Library-ified replacement for apertium's apertium-pretransfer binary.
// The apertium header already exposes processStream() in pretransfer.h,
// so we just marshal input/output via tmp files.

#include "apertium_core.h"
#include "wrapper_common.h"

#include <apertium/pretransfer.h>
#include <lttoolbox/file_utils.h>
#include <lttoolbox/input_file.h>
#include <lttoolbox/lt_locale.h>

#include <unicode/ustdio.h>

extern "C" ApertiumResult apertium_pretransfer(const char* input,
                                               const char* flags,
                                               const char* tmp_dir) {
  return aix::run_wrapper([&] {
    if (!tmp_dir) throw std::runtime_error("tmp_dir is NULL");
    LtLocale::tryToSetLocale();

    bool null_flush       = false;
    bool no_surface_forms = false;
    bool compounds        = false;
    for (const char* p = flags ? flags : ""; *p; ++p) {
      switch (*p) {
        case 'z': null_flush = true; break;
        case 'n': no_surface_forms = true; break;
        case 'e': compounds = true; break;
        default:
          throw std::runtime_error(std::string("unknown pretransfer flag: ") + *p);
      }
    }

    aix::TmpFile in_tmp = aix::spit_tmp(tmp_dir, "pre_in", input);
    aix::TmpFile out_tmp(tmp_dir, "pre_out");

    InputFile in_file;
    in_file.open_or_exit(in_tmp.c_str());
    {
      aix::UFilePtr out(openOutTextFile(out_tmp.path()));
      processStream(in_file, out.get(), null_flush, no_surface_forms, compounds);
    }
    return aix::slurp(out_tmp.path());
  });
}
