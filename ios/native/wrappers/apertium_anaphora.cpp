// apertium-ios-native/wrappers/apertium_anaphora.cpp
//
// Library-ified replacement for apertium-anaphora.
// Unlike most other tools, apertium-anaphora has no Processor class —
// its full logic sits in main(). We re-host that loop here, running
// against InputFile/UFILE just like the original.

#include "apertium_core.h"
#include "wrapper_common.h"

#include <parse_arx.h>
#include <parse_biltrans.h>
#include <pattern_arx.h>
#include <score.h>

#include <lttoolbox/input_file.h>
#include <lttoolbox/lt_locale.h>
#include <lttoolbox/ustring.h>

#include <unicode/ustdio.h>

#include <vector>

namespace {

void run_anaphora(InputFile& input, UFILE* output,
                  ParseArx& arx_file, bool null_flush, bool debug_flag) {
  UString input_stream, final_ref, sl_form, tl_form, sl_lemma, tl_lemma;
  std::vector<UString> sl_tags, tl_tags;
  Scoring score_module;
  unsigned gen_id = 0;
  int flag_LU = 0;

  UChar32 c = input.get();
  while (c != U_EOF) {
    if (null_flush && c == '\0') {
      u_fputc(c, output);
      u_fflush(output);
      input_stream.clear();
      sl_form.clear(); tl_form.clear();
      sl_tags.clear(); tl_tags.clear();
      sl_lemma.clear(); tl_lemma.clear();
      gen_id = 0;
      score_module.clear();
      final_ref.clear();
      flag_LU = 0;
    } else if (c == '\\') {
      if (flag_LU == 0) {
        u_fputc(c, output);
        c = input.get();
        u_fputc(c, output);
      } else {
        input_stream.push_back(c);
        u_fputc(c, output);
        c = input.get();
        u_fputc(c, output);
        input_stream.push_back(c);
      }
    } else {
      if (flag_LU == 0) {
        u_fputc(c, output);
        if (c == '^') flag_LU = 1;
      } else if (flag_LU == 1) {
        if (c == '$') {
          gen_id++;
          u_fputc('/', output);
          flag_LU = 0;
          ParseLexicalUnit LU(input_stream);
          tl_form = LU.get_tl_form();
          tl_tags = LU.get_tl_tags();
          sl_form = LU.get_sl_form();
          sl_tags = LU.get_sl_tags();
          sl_lemma = LU.get_sl_lemma();
          tl_lemma = LU.get_tl_lemma();
          if (!tl_form.empty()) {
            int r = score_module.add_word(gen_id, sl_form, sl_tags, tl_form,
                                          sl_lemma, tl_lemma, arx_file,
                                          debug_flag);
            if (r == 1) {
              final_ref = score_module.get_antecedent(debug_flag);
              write(final_ref, output);
            }
          }
          input_stream.clear();
        } else {
          input_stream.push_back(c);
        }
        u_fputc(c, output);
      }
    }
    c = input.get();
  }
}

}  // namespace

extern "C" ApertiumResult apertium_anaphora(const char* input,
                                            const char* arx_file_path,
                                            const char* flags,
                                            const char* tmp_dir) {
  ApertiumResult result{nullptr, nullptr};
  std::string in_path, out_path;
  try {
    if (!arx_file_path) throw std::runtime_error("arx_file is NULL");
    if (!tmp_dir)       throw std::runtime_error("tmp_dir is NULL");

    LtLocale::tryToSetLocale();
    aix::ensure_exists(arx_file_path);

    bool null_flush = false, debug_flag = false;
    for (const char* c = flags ? flags : ""; *c; ++c) {
      switch (*c) {
        case 'z': null_flush = true; break;
        case 'd': debug_flag = true; break;
        default:
          throw std::runtime_error(std::string("unknown anaphora flag: ") + *c);
      }
    }

    ParseArx arx;
    // parseDoc returns non-zero on failure; the upstream main() exits
    // in that case, so we throw instead.
    if (arx.parseDoc(const_cast<char*>(arx_file_path)) != 0) {
      throw std::runtime_error(std::string("failed to parse ARX file: ")
                               + arx_file_path);
    }

    in_path  = aix::spit_tmp(tmp_dir, "anaphora_in", input);
    out_path = aix::make_tmp_file(tmp_dir, "anaphora_out");

    InputFile in_file;
    in_file.open_or_exit(in_path.c_str());
    UFILE* out_ufile = u_fopen(out_path.c_str(), "w", nullptr, nullptr);
    if (!out_ufile) throw std::runtime_error("u_fopen failed for " + out_path);
    run_anaphora(in_file, out_ufile, arx, null_flush, debug_flag);
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
