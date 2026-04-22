// apertium-ios-native/wrappers/apertium_posttransfer.cpp
//
// Library-ified replacement for apertium's apertium-posttransfer binary.
// processStream() was defined as a static function inside
// apertium_posttransfer.cc (no public header), so we reproduce the
// tiny state machine inline here. It collapses consecutive spaces.

#include "apertium_core.h"
#include "wrapper_common.h"

#include <lttoolbox/file_utils.h>
#include <lttoolbox/input_file.h>
#include <lttoolbox/lt_locale.h>

#include <unicode/ustdio.h>

namespace {

void posttransfer_stream(InputFile& in, UFILE* out, bool null_flush) {
  bool last_space = false;
  while (!in.eof()) {
    UChar32 c = in.get();
    if (c == U_EOF) break;
    if (!last_space || c != ' ') {
      u_fputc(c, out);
      if (c == '\0' && null_flush) u_fflush(out);
    }
    last_space = (c == ' ');
  }
}

}  // namespace

extern "C" ApertiumResult apertium_posttransfer(const char* input,
                                                const char* flags,
                                                const char* tmp_dir) {
  ApertiumResult result{nullptr, nullptr};
  std::string in_path, out_path;
  try {
    if (!tmp_dir) throw std::runtime_error("tmp_dir is NULL");
    LtLocale::tryToSetLocale();

    bool null_flush = false;
    for (const char* p = flags ? flags : ""; *p; ++p) {
      switch (*p) {
        case 'z': null_flush = true; break;
        default:
          throw std::runtime_error(std::string("unknown posttransfer flag: ") + *p);
      }
    }

    in_path  = aix::spit_tmp(tmp_dir, "post_in", input);
    out_path = aix::make_tmp_file(tmp_dir, "post_out");

    InputFile in_file;
    in_file.open_or_exit(in_path.c_str());
    UFILE* out_ufile = openOutTextFile(out_path);
    posttransfer_stream(in_file, out_ufile, null_flush);
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
