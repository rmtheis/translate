// apertium-ios-native/wrappers/apertium_transfer.cpp
//
// Library-ified replacement for apertium's apertium-transfer binary.

#include "apertium_core.h"
#include "wrapper_common.h"

#include <apertium/transfer.h>
#include <lttoolbox/file_utils.h>
#include <lttoolbox/input_file.h>
#include <lttoolbox/lt_locale.h>

#include <unicode/ustdio.h>

extern "C" ApertiumResult apertium_transfer(const char* input,
                                            const char* trules_file,
                                            const char* datafile,
                                            const char* biltrans_file,
                                            const char* flags,
                                            const char* tmp_dir) {
  ApertiumResult result{nullptr, nullptr};
  std::string in_path, out_path;
  try {
    if (!trules_file) throw std::runtime_error("trules_file is NULL");
    if (!datafile)    throw std::runtime_error("datafile is NULL");
    if (!tmp_dir)     throw std::runtime_error("tmp_dir is NULL");

    LtLocale::tryToSetLocale();

    in_path  = aix::spit_tmp(tmp_dir, "xfer_in", input);
    out_path = aix::make_tmp_file(tmp_dir, "xfer_out");

    Transfer t;
    for (const char* p = flags ? flags : ""; *p; ++p) {
      switch (*p) {
        case 'b': t.setPreBilingual(true); t.setUseBilingual(false); break;
        case 'n': t.setUseBilingual(false); break;
        case 'c': t.setCaseSensitiveness(true); break;
        case 'w': t.setDictionaryCase(true); break;
        case 't': t.setTrace(true); break;
        case 'T': t.setTrace(true); t.setTraceATT(true); break;
        case 'z': t.setNullFlush(true); break;
        default:
          throw std::runtime_error(std::string("unknown transfer flag: ") + *p);
      }
    }

    aix::ensure_exists(trules_file);
    aix::ensure_exists(datafile);
    const bool has_biltrans = biltrans_file && biltrans_file[0];
    if (has_biltrans) {
      aix::ensure_exists(biltrans_file);
      t.read(trules_file, datafile, biltrans_file);
    } else {
      t.read(trules_file, datafile);
    }

    InputFile in_file;
    in_file.open_or_exit(in_path.c_str());
    UFILE* out_ufile = openOutTextFile(out_path);
    t.transfer(in_file, out_ufile);
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
