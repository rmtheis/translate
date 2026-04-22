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
  ApertiumResult result{nullptr, nullptr};
  std::string in_path, out_path;
  try {
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

    in_path  = aix::spit_tmp(tmp_dir, "pre_in", input);
    out_path = aix::make_tmp_file(tmp_dir, "pre_out");

    InputFile in_file;
    in_file.open_or_exit(in_path.c_str());
    UFILE* out_ufile = openOutTextFile(out_path);
    processStream(in_file, out_ufile, null_flush, no_surface_forms, compounds);
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
