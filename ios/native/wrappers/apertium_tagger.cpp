// apertium-ios-native/wrappers/apertium_tagger.cpp
//
// Library-ified replacement for apertium's apertium-tagger binary.
// Unlike most other Apertium tools, tagger is main()-shaped: the
// Apertium::apertium_tagger class takes (int& argc, char**& argv) and
// does all its work inside the constructor. Our wrapper synthesizes
// the argv array it expects.

#include "apertium_core.h"
#include "wrapper_common.h"

#include <apertium/tagger.h>
#include <lttoolbox/lt_locale.h>

#include <cstring>
#include <vector>

namespace {

// Build a mutable C-string vector so we can construct the argv the
// apertium_tagger constructor expects (it takes char**& — non-const
// reference, which some of its callees mutate via optind/getopt).
struct Argv {
  std::vector<std::vector<char>> bufs;
  std::vector<char*> ptrs;

  void push(const std::string& s) {
    std::vector<char> buf(s.begin(), s.end());
    buf.push_back('\0');
    bufs.push_back(std::move(buf));
    ptrs.push_back(bufs.back().data());
  }
  void terminate() { ptrs.push_back(nullptr); }
  int argc() const { return static_cast<int>(ptrs.size() - 1); }
  char** argv() { return ptrs.data(); }
};

}  // namespace

extern "C" ApertiumResult apertium_tagger_apply(const char* input,
                                                const char* prob_file,
                                                const char* flags,
                                                const char* tmp_dir) {
  return aix::run_wrapper([&] {
    if (!prob_file) throw std::runtime_error("prob_file is NULL");
    if (!tmp_dir)   throw std::runtime_error("tmp_dir is NULL");

    LtLocale::tryToSetLocale();
    aix::ensure_exists(prob_file);

    aix::TmpFile in_tmp = aix::spit_tmp(tmp_dir, "tag_in", input);
    aix::TmpFile out_tmp(tmp_dir, "tag_out");

    // argv: [apertium-tagger, -g, <user flags>..., prob, input, output]
    // -g selects "apply tagger" mode; the class constructor dispatches
    // to the HMM tagger's g_FILE_Tagger by default.
    Argv argv;
    argv.push("apertium-tagger");
    argv.push("-g");
    for (const char* p = flags ? flags : ""; *p; ++p) {
      // Pass the CLI's options without a value through to the class's own
      // getopt. Unknown flags are rejected up front rather than letting
      // getopt throw an opaque InvalidOption from deep inside the class.
      switch (*p) {
        case 'b': case 'd': case 'e': case 'f': case 'm': case 'p':
        case 'w': case 'x': case 'z':
          argv.push(std::string("-") + *p);
          break;
        default:
          throw std::runtime_error(std::string("unknown tagger flag: ") + *p);
      }
    }
    argv.push(prob_file);
    argv.push(in_tmp.path());
    argv.push(out_tmp.path());
    argv.terminate();

    int argc = argv.argc();
    char** argv_ptr = argv.argv();
    {
      // Constructor does all the work; ~apertium_tagger() is trivial.
      Apertium::apertium_tagger(argc, argv_ptr);
    }
    return aix::slurp(out_tmp.path());
  });
}
