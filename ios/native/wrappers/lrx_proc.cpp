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
  ApertiumResult result{nullptr, nullptr};
  std::string in_path, out_path;
  try {
    if (!bin_path) throw std::runtime_error("bin_path is NULL");
    if (!tmp_dir)  throw std::runtime_error("tmp_dir is NULL");

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

    FILE* fst = openInBinFile(bin_path);
    p.load(fst);
    std::fclose(fst);
    p.init();

    in_path  = aix::spit_tmp(tmp_dir, "lrx_in", input);
    out_path = aix::make_tmp_file(tmp_dir, "lrx_out");

    InputFile in_file;
    in_file.open_or_exit(in_path.c_str());
    UFILE* out_ufile = openOutTextFile(out_path);
    p.process(in_file, out_ufile);
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
