// apertium-ios-native/wrappers/rtx_proc.cpp
//
// Library-ified replacement for apertium-recursive's rtx-proc binary.
// RTXProcessor::process takes FILE* on the input side (not InputFile),
// because rtx reads binary bytecode streams. We pass an fopen()'d tmp.

#include "apertium_core.h"
#include "wrapper_common.h"

#include <rtx_processor.h>

#include <lttoolbox/file_utils.h>
#include <lttoolbox/lt_locale.h>

#include <unicode/ustdio.h>

extern "C" ApertiumResult apertium_rtx_proc(const char* input,
                                            const char* rtx_file,
                                            const char* flags,
                                            const char* tmp_dir) {
  ApertiumResult result{nullptr, nullptr};
  std::string in_path, out_path;
  FILE* in_fp = nullptr;
  try {
    if (!rtx_file) throw std::runtime_error("rtx_file is NULL");
    if (!tmp_dir)  throw std::runtime_error("tmp_dir is NULL");

    LtLocale::tryToSetLocale();
    aix::ensure_exists(rtx_file);

    RTXProcessor p;
    bool print_trees = false, print_text = true;
    for (const char* c = flags ? flags : ""; *c; ++c) {
      switch (*c) {
        case 'a': p.withoutCoref(false); break;  // -a: expect coreference from apertium-anaphora
        case 'b': print_text = true; break;
        case 'e': p.completeTrace(true); break;
        case 'f': p.printFilter(true); break;
        case 'F': p.noFiltering(false); break;
        case 'r': p.printRules(true); break;
        case 's': p.printSteps(true); break;
        case 't': p.mimicChunker(true); break;
        case 'T': print_trees = true; break;
        case 'z': p.setNullFlush(true); break;
        default:
          throw std::runtime_error(std::string("unknown rtx-proc flag: ") + *c);
      }
    }
    p.printTrees(print_trees);
    p.printText(print_text || !print_trees);

    p.read(rtx_file);

    in_path  = aix::spit_tmp(tmp_dir, "rtx_in", input);
    out_path = aix::make_tmp_file(tmp_dir, "rtx_out");
    in_fp = openInBinFile(in_path);  // openInBinFile throws on failure

    UFILE* out_ufile = openOutTextFile(out_path);
    p.process(in_fp, out_ufile);
    u_fclose(out_ufile);

    std::fclose(in_fp); in_fp = nullptr;

    std::string out = aix::slurp(out_path);
    aix::rm_quiet(in_path);
    aix::rm_quiet(out_path);
    result.output = aix::dup_cstr(out);
    if (!result.output) throw std::runtime_error("dup_cstr failed");
    return result;
  } catch (const std::exception& e) {
    if (in_fp) std::fclose(in_fp);
    aix::rm_quiet(in_path);
    aix::rm_quiet(out_path);
    result.error = aix::dup_cstr(e.what());
    return result;
  }
}
