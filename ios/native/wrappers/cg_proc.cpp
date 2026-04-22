// apertium-ios-native/wrappers/cg_proc.cpp
//
// Library-ified replacement for cg3's cg-proc binary.
// Uses cg3's C++ ApertiumApplicator directly — the public C API's
// cg3_applicator_create() returns a generic GrammarApplicator (CG
// stream format) which misparses Apertium-format input.

#include "apertium_core.h"
#include "wrapper_common.h"

// cg3's internal C++ headers live in cg3/src/ — not installed by the
// package's Makefile. We add the src/ dir to the include path in
// build_wrappers so these resolve.
#include "stdafx.hpp"
#include "Grammar.hpp"
#include "TextualParser.hpp"
#include "BinaryGrammar.hpp"
#include "ApertiumApplicator.hpp"

#include <fstream>

extern "C" ApertiumResult apertium_cg_proc(const char* input,
                                           const char* grammar_file,
                                           const char* flags,
                                           const char* tmp_dir) {
  ApertiumResult result{nullptr, nullptr};
  std::string in_path, out_path;
  try {
    if (!grammar_file) throw std::runtime_error("grammar_file is NULL");
    if (!tmp_dir)      throw std::runtime_error("tmp_dir is NULL");
    aix::ensure_exists(grammar_file);

    // Mirror cg-proc.cpp's main loop: parse flags, load grammar via
    // BinaryGrammar, hand off to ApertiumApplicator.
    bool trace = false;
    bool wordform_case = false;
    bool print_word_forms = true;
    bool delimit_lexical_units = true;
    bool surface_readings = false;
    bool only_first = false;
    bool null_flush = false;
    int sections = 0;
    for (const char* c = flags ? flags : ""; *c; ++c) {
      switch (*c) {
        case 't': trace = true; break;
        case 'w': wordform_case = true; break;
        case 'n': print_word_forms = false; break;
        case 'g': delimit_lexical_units = false; break;
        case '1': only_first = true; break;
        case 'z': null_flush = true; break;
        case 'd': /* -d: disambiguation — default mode, no-op */ break;
        case 'r': /* -r RULE — not supported in wrapper; would need an arg */ break;
        case 's': /* -s NUM sections — would need an arg; skip */ break;
        case 'f': /* -f stream format — we always use Apertium */ break;
        default:
          throw std::runtime_error(std::string("unknown cg-proc flag: ") + *c);
      }
    }
    (void)null_flush;  // ApertiumApplicator reads null-flush via setNullFlush

    CG3::Grammar grammar;
    // Detect textual vs binary grammar by reading the first 4 bytes.
    unsigned char sniff[4] = {0};
    {
      std::ifstream g(grammar_file, std::ios::binary);
      g.read(reinterpret_cast<char*>(sniff), 4);
    }
    std::unique_ptr<CG3::IGrammarParser> parser;
    if (CG3::is_cg3b(sniff)) {
      parser.reset(new CG3::BinaryGrammar(grammar, std::cerr));
    } else {
      parser.reset(new CG3::TextualParser(grammar, std::cerr));
    }
    grammar.ux_stderr = &std::cerr;
    if (parser->parse_grammar(grammar_file)) {
      throw std::runtime_error("could not parse grammar");
    }
    grammar.reindex();

    CG3::ApertiumApplicator app(std::cerr);
    app.wordform_case = wordform_case;
    app.print_word_forms = print_word_forms;
    app.delimit_lexical_units = delimit_lexical_units;
    app.surface_readings = surface_readings;
    app.print_only_first = only_first;
    app.setGrammar(&grammar);
    app.setOptions();
    for (int32_t i = 1; i <= sections; ++i) app.sections.push_back(i);
    app.trace = trace;
    app.unicode_tags = true;
    app.unique_tags = false;
    (void)null_flush;  // ApertiumApplicator doesn't expose a null-flush
                       // setter in this revision of cg3; drop silently.

    in_path  = aix::spit_tmp(tmp_dir, "cg_in", input);
    out_path = aix::make_tmp_file(tmp_dir, "cg_out");
    {
      std::ifstream is(in_path, std::ios::binary);
      std::ofstream os(out_path, std::ios::binary);
      app.runGrammarOnText(is, os);
    }

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
