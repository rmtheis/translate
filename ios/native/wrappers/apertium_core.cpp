// apertium-ios-native/wrappers/apertium_core.cpp
//
// Top-level pipeline composer. Parses an Apertium .mode file and
// dispatches each stage to the matching library-ified wrapper,
// threading the string output of one stage into the next.
//
// Semantic mirror of apertium-android's NativePipeline.java —
// parseModeLine/runPipeline/applyMarkerPref/rewritePath all live here.

#include "apertium_core.h"
#include "wrapper_common.h"

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <regex>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

namespace {

// Shell-style tokenizer. Handles "double", 'single', and bare words.
std::vector<std::string> tokenize(const std::string& line) {
  std::vector<std::string> out;
  std::string cur;
  enum { NONE, SQ, DQ } mode = NONE;
  auto flush = [&]{ if (!cur.empty() || mode != NONE) { out.push_back(cur); cur.clear(); } };
  for (size_t i = 0; i < line.size(); ++i) {
    char c = line[i];
    if (mode == SQ) {
      if (c == '\'') { out.push_back(cur); cur.clear(); mode = NONE; }
      else cur.push_back(c);
    } else if (mode == DQ) {
      if (c == '"') { out.push_back(cur); cur.clear(); mode = NONE; }
      else cur.push_back(c);
    } else {
      if (c == '\'') mode = SQ;
      else if (c == '"') mode = DQ;
      else if (std::isspace(static_cast<unsigned char>(c))) flush();
      else cur.push_back(c);
    }
  }
  if (!cur.empty()) out.push_back(cur);
  return out;
}

std::string basename_of(const std::string& p) {
  auto slash = p.find_last_of('/');
  return slash == std::string::npos ? p : p.substr(slash + 1);
}

// Mirrors NativePipeline.rewritePath. Debian-style
// /usr/share/apertium/apertium-<pkg>/<file> is rewritten to
// <pair_base>/<file>; relative data paths are joined to <pair_base>;
// absolute paths (other than the Debian prefix) pass through.
std::string rewrite_path(const std::string& tok, const std::string& pair_base) {
  if (tok.empty() || tok[0] == '-') return tok;
  static const std::string debian = "/usr/share/apertium/";
  if (tok.rfind(debian, 0) == 0) {
    return pair_base + "/" + basename_of(tok);
  }
  if (tok[0] == '/') return tok;
  auto has_suffix = [&](const char* s){
    size_t n = std::strlen(s);
    return tok.size() >= n && tok.compare(tok.size() - n, n, s) == 0;
  };
  if (tok.find('/') != std::string::npos
      || has_suffix(".bin") || has_suffix(".mode")
      || has_suffix(".t1x") || has_suffix(".t2x") || has_suffix(".t3x")
      || has_suffix(".rlx") || has_suffix(".rtx") || has_suffix(".prob")
      || has_suffix(".arx")) {
    return pair_base + "/" + tok;
  }
  return tok;
}

// Parse one mode-line segment's tokens; do $1/$2 substitution and path
// rewriting. $1 is Apertium's apertium(1) CLI substitution for the
// lt-proc-mode flag (default -g, for "generator"). $2 is typically empty.
std::vector<std::string> rewrite_stage(const std::vector<std::string>& toks,
                                       const std::string& pair_base) {
  std::vector<std::string> out;
  out.reserve(toks.size());
  if (toks.empty()) return out;
  out.push_back(toks[0]);  // tool name, not path-rewritten
  for (size_t i = 1; i < toks.size(); ++i) {
    const std::string& t = toks[i];
    if (t == "$1")      out.push_back("-g");
    else if (t == "$2") continue;
    else                out.push_back(rewrite_path(t, pair_base));
  }
  return out;
}

std::vector<std::vector<std::string>> parse_mode_line(const std::string& line,
                                                      const std::string& pair_base) {
  std::vector<std::vector<std::string>> stages;
  std::string seg;
  std::istringstream ss(line);
  while (std::getline(ss, seg, '|')) {
    // Trim
    size_t a = seg.find_first_not_of(" \t\r\n");
    if (a == std::string::npos) continue;
    size_t b = seg.find_last_not_of(" \t\r\n");
    std::string trimmed = seg.substr(a, b - a + 1);
    auto toks = tokenize(trimmed);
    if (toks.empty()) continue;
    stages.push_back(rewrite_stage(toks, pair_base));
  }
  return stages;
}

// One command-line option of a pipeline tool, as the tool's upstream main()
// declares it. on_ios is false for options no wrapper implements; none of the
// offered directions passes one, and scripts/check-pair-tools.py --ios fails
// CI if a pair update starts to.
struct OptSpec {
  char short_opt;
  const char* long_opt;  // nullptr: no long form
  bool has_arg;
  bool on_ios = true;
};

// The options each tool's CLI accepts, from its upstream main(): lt_proc.cc,
// lt_merge.cc, cg-proc.cpp, hfst-proc.cc, lrx_proc.cc, lsx_proc.cc,
// rtx_proc.cc, apertium_{transfer,interchunk,postchunk,pretransfer,
// posttransfer}.cc, tagger.cc and anaphora.cc. -h/--help and -v/--version are
// left out: the CLIs exit on them without translating. cg-proc has no long
// options: cg3's CMake build never defines HAVE_GETOPT_LONG, so cg-proc reads
// its options with plain getopt(). A tool missing here is an unknown tool.
const std::unordered_map<std::string, std::vector<OptSpec>>& tool_options() {
  static const std::vector<OptSpec> hfst_proc{
    {'q', "quiet", false}, {'s', "silent", false}, {'v', "verbose", false, false},
    {'a', "analysis", false}, {'g', "generation", false},
    {'n', "non-marked-gen", false}, {'d', "debugged-gen", false},
    {'t', "tokenize", false}, {'j', "transliterate", false, false},
    {'p', "apertium", false}, {'x', "xerox", false, false}, {'C', "cg", false, false},
    {'k', "keep-compounds", false}, {'e', "do-compounds", false},
    {'W', "show-weights", false}, {'r', "show-raw-in-cg", false},
    {'N', "analyses", true}, {'l', "weight-classes", true},
    {'c', "case-sensitive", false}, {'w', "dictionary-case", false},
    {'z', "null-flush", false}, {'X', "raw", false},
  };
  static const std::unordered_map<std::string, std::vector<OptSpec>> t{
    {"lt-proc", {
      {'a', "analysis", false}, {'b', "bilingual", false},
      {'c', "case-sensitive", false}, {'d', "debugged-gen", false},
      {'e', "decompose-nouns", false}, {'g', "generation", false},
      {'i', "ignored-chars", true, false}, {'r', "restore-chars", true, false},
      {'l', "tagged-gen", false}, {'m', "tagged-nm-gen", false},
      {'n', "non-marked-gen", false}, {'o', "surf-bilingual", false},
      {'O', "surf-bilingual-keep", false}, {'p', "post-generation", false},
      {'x', "inter-generation", false}, {'s', "sao", false},
      {'t', "transliteration", false}, {'z', "null-flush", false},
      {'w', "dictionary-case", false}, {'C', "careful-case", false},
      {'I', "no-default-ignore", false}, {'W', "show-weights", false},
      {'N', "analyses", true}, {'L', "weight-classes", true},
      {'M', "compound-max-elements", true}}},
    {"lt-merge", {{'u', "unmerge", false}, {'z', "null-flush", false}}},
    {"cg-proc", {
      {'d', nullptr, false}, {'s', nullptr, true, false}, {'f', nullptr, true},
      {'t', nullptr, false}, {'r', nullptr, true, false}, {'n', nullptr, false},
      {'g', nullptr, false}, {'1', nullptr, false}, {'w', nullptr, false},
      {'z', nullptr, false}}},
    {"hfst-proc", hfst_proc},
    {"hfst-apertium-proc", hfst_proc},
    {"lrx-proc", {
      {'t', "trace", false}, {'d', "debug", false},
      {'z', "null-flush", false}, {'m', "max-ent", false}}},
    {"lsx-proc", {
      {'p', "postgen", false}, {'r', "repeat", false},
      {'w', "dictionary-case", false}, {'z', "null-flush", false}}},
    {"rtx-proc", {
      {'a', "anaphora", false}, {'b', "both", false},
      {'e', "everything", false}, {'f', "filter-trace", false},
      {'F', "filter", false}, {'m', "mode", true, false}, {'r', "rules", false},
      {'s', "steps", false}, {'t', "trx", false}, {'T', "tree", false},
      {'z', "null-flush", false}}},
    {"apertium-transfer", {
      {'b', "from-bilingual", false}, {'n', "no-bilingual", false},
      {'x', "extended", true, false}, {'c', "case-sensitive", false},
      {'w', "dictionary-case", false}, {'z', "null-flush", false},
      {'t', "trace", false}, {'T', "trace_att", false}}},
    {"apertium-interchunk", {
      {'t', "trace", false}, {'w', "dictionary-case", false},
      {'z', "null-flush", false}}},
    {"apertium-postchunk", {
      {'t', "trace", false}, {'w', "dictionary-case", false},
      {'z', "null-flush", false}}},
    {"apertium-pretransfer", {
      {'e', "compounds", false}, {'n', "no-surface-forms", false},
      {'z', "null-flush", false}}},
    {"apertium-posttransfer", {{'z', "null-flush", false}}},
    {"apertium-tagger", {
      {'b', "sent-seg", false}, {'d', "debug", false},
      {'e', "skip-on-error", false}, {'f', "first", false},
      {'m', "mark", false}, {'p', "show-superficial", false},
      {'z', "null-flush", false}, {'u', "unigram", true, false},
      {'w', "sliding-window", false}, {'x', "perceptron", false},
      {'g', "tagger", false}, {'r', "retrain", true, false},
      {'s', "supervised", true, false}, {'t', "train", true, false}}},
    {"apertium-anaphora", {{'d', "debug", false}, {'z', "null-flush", false}}},
  };
  return t;
}

// A stage's arguments after option parsing: the options without a value as
// letters in command-line order ("wg" for `-w -g`), the options with a value
// (the last one wins, as the CLIs read them) and the file arguments.
struct Argv {
  std::string flags;
  std::map<char, std::string> values;
  std::vector<std::string> files;
};

// Parse argv[1..] the way getopt_long does on Linux/Android, where the
// Android app runs these CLIs: bundled short options (-bc), a value attached
// (-N1) or in the next word (-N 1, --weight-classes 1, --analyses=1), long
// options by name or unique prefix, options after file arguments, and "--"
// ending the options. An option the tool doesn't define fails the stage, as
// the CLI's usage-and-exit does; so does one that isn't on_ios.
Argv parse_argv(const std::vector<std::string>& argv,
                const std::vector<OptSpec>& spec) {
  Argv a;
  auto store = [&](const OptSpec& o, std::string value) {
    if (!o.on_ios)
      throw std::runtime_error(std::string("option -") + o.short_opt
                               + " is not supported on iOS");
    if (o.has_arg) a.values[o.short_opt] = std::move(value);
    else           a.flags.push_back(o.short_opt);
  };
  for (size_t i = 1; i < argv.size(); ++i) {
    const std::string& t = argv[i];
    if (t == "--") {
      a.files.insert(a.files.end(), argv.begin() + i + 1, argv.end());
      break;
    }
    if (t.size() > 2 && t.compare(0, 2, "--") == 0) {
      size_t eq = t.find('=');
      std::string name = t.substr(2, eq == std::string::npos ? eq : eq - 2);
      const OptSpec* match = nullptr;
      int prefix_matches = 0;
      for (const auto& o : spec) {
        if (!o.long_opt) continue;
        if (name == o.long_opt) { match = &o; prefix_matches = 1; break; }
        if (std::strncmp(o.long_opt, name.c_str(), name.size()) == 0) {
          match = &o;
          ++prefix_matches;
        }
      }
      if (!match || prefix_matches > 1)
        throw std::runtime_error("unknown option --" + name);
      if (!match->has_arg) {
        if (eq != std::string::npos)
          throw std::runtime_error("option --" + name + " takes no value");
        store(*match, "");
      } else if (eq != std::string::npos) {
        store(*match, t.substr(eq + 1));
      } else if (i + 1 < argv.size()) {
        store(*match, argv[++i]);
      } else {
        throw std::runtime_error("option --" + name + " needs a value");
      }
    } else if (t.size() > 1 && t[0] == '-') {
      for (size_t j = 1; j < t.size(); ++j) {
        auto o = std::find_if(spec.begin(), spec.end(),
                              [&](const OptSpec& s) { return s.short_opt == t[j]; });
        if (o == spec.end())
          throw std::runtime_error(std::string("unknown option -") + t[j]);
        if (!o->has_arg) { store(*o, ""); continue; }
        if (j + 1 < t.size())       store(*o, t.substr(j + 1));
        else if (i + 1 < argv.size()) store(*o, argv[++i]);
        else throw std::runtime_error(std::string("option -") + t[j] + " needs a value");
        break;
      }
    } else {
      a.files.push_back(t);
    }
  }
  return a;
}

// Remove count option `c` (lt-proc -N 1, hfst-proc --weight-classes 1) from
// a.values; 0 if it wasn't given. Like the CLIs, reject a count below 1.
int take_count(Argv& a, char c) {
  auto it = a.values.find(c);
  if (it == a.values.end()) return 0;
  int n = std::atoi(it->second.c_str());
  if (n < 1)
    throw std::runtime_error(std::string("invalid count for -") + c + ": " + it->second);
  a.values.erase(it);
  return n;
}

std::string take_file(Argv& a) {
  if (a.files.empty())
    throw std::runtime_error("expected file argument");
  std::string s = a.files.front();
  a.files.erase(a.files.begin());
  return s;
}

std::string opt_file(Argv& a) {
  if (a.files.empty()) return "";
  std::string s = a.files.front();
  a.files.erase(a.files.begin());
  return s;
}

// apertium-transfer/-interchunk/-postchunk take the rules XML and the .bin
// compiled from it; the .bin's pattern matcher returns rule numbers that index
// the XML's <rule>s, so the two must match. Apertium builds X.t1x.bin from
// X.t1x, and a pair with rule variants (alt="oci@aran") ships the
// variant-filtered X.t1x next to the unfiltered apertium-<pkg>.X.t1x. The
// Debian build of apertium-oci-cat (2022, 357b2f07) passes the unfiltered file
// with oci-cat.t1x.bin (155 vs 132 rules; t2x/t3x mismatch too), so transfer
// ran the wrong rule's actions and segfaulted on "L'ostal es grand.". Upstream
// fixed modes.xml in a81f6fd1 (2025-03). When X.tNx exists, read it instead.
std::string rules_xml_for_bin(const std::string& xml, const std::string& bin) {
  static const std::string ext = ".bin";
  if (bin.size() <= ext.size()
      || bin.compare(bin.size() - ext.size(), ext.size(), ext) != 0) {
    return xml;
  }
  std::string src = bin.substr(0, bin.size() - ext.size());
  if (src == xml || ::access(src.c_str(), R_OK) != 0) return xml;
  return src;
}

// cg-proc prints a CG-3 dependency link as a tag, <#N→M>, on every cohort a
// SETPARENT/SETCHILD rule touched. CG-3 added that to the Apertium stream
// format in f5d37748 (2022-01); grammars written before then don't expect it.
// hbs-mkd.rlx's experimental SETPARENT rules fire on adjective + noun ("Dobar
// dan."), apertium-pretransfer then reads the tag's '#' as a multiword split
// (^Dobar#1→2><adj>…<$), and apertium-transfer segfaults on the result. Android
// runs the real binaries and crashes the same way. No stage in the pairs we
// ship reads the tags, so drop them. Only <#digits→digits> inside a lexical
// unit is dropped; escaped characters and [superblanks] pass through.
bool is_dependency_tag(const std::string& s, size_t begin, size_t end) {
  static const std::string arrow = "\xE2\x86\x92";  // U+2192 in UTF-8
  size_t i = begin;
  if (i >= end || s[i] != '#') return false;
  ++i;
  auto digits = [&]() {
    size_t start = i;
    while (i < end && std::isdigit(static_cast<unsigned char>(s[i]))) ++i;
    return i > start;
  };
  if (!digits()) return false;
  if (s.compare(i, arrow.size(), arrow) != 0) return false;
  i += arrow.size();
  return digits() && i == end;
}

std::string strip_dependency_tags(const std::string& s) {
  if (s.find("\xE2\x86\x92") == std::string::npos) return s;
  std::string out;
  out.reserve(s.size());
  bool in_lu = false;
  for (size_t i = 0; i < s.size(); ++i) {
    char c = s[i];
    if (c == '\\' && i + 1 < s.size()) {
      out.push_back(c);
      out.push_back(s[++i]);
      continue;
    }
    if (!in_lu && c == '[') {
      // Superblank or [[wordbound blank]]: copy through the closing ']'.
      size_t j = i;
      while (j < s.size() && s[j] != ']') j += (s[j] == '\\') ? 2 : 1;
      if (j >= s.size()) j = s.size() - 1;
      out.append(s, i, j - i + 1);
      i = j;
      continue;
    }
    if (c == '^') {
      in_lu = true;
    } else if (c == '$') {
      in_lu = false;
    } else if (c == '<' && in_lu) {
      size_t close = s.find('>', i + 1);
      if (close != std::string::npos && is_dependency_tag(s, i + 1, close)) {
        i = close;
        continue;
      }
    }
    out.push_back(c);
  }
  return out;
}

// ---------- stage dispatch ----------

ApertiumResult dispatch_stage(const std::string& tool, Argv& a,
                              const std::string& in, const char* tmp_dir) {
  if (tool == "lt-proc") {
    int analyses       = take_count(a, 'N');
    int weight_classes = take_count(a, 'L');
    int compound_max   = take_count(a, 'M');
    std::string bin = take_file(a);
    return apertium_lt_proc(in.c_str(), bin.c_str(), a.flags.c_str(),
                            analyses, weight_classes, compound_max, tmp_dir);
  }
  if (tool == "lt-merge") {
    return apertium_lt_merge(in.c_str(), a.flags.c_str(), tmp_dir);
  }
  if (tool == "apertium-tagger") {
    // -g is always set by our wrapper; strip it from the flag passthrough.
    std::string fl = a.flags;
    fl.erase(std::remove(fl.begin(), fl.end(), 'g'), fl.end());
    std::string prob = take_file(a);
    return apertium_tagger_apply(in.c_str(), prob.c_str(), fl.c_str(), tmp_dir);
  }
  if (tool == "apertium-pretransfer") {
    return apertium_pretransfer(in.c_str(), a.flags.c_str(), tmp_dir);
  }
  if (tool == "apertium-posttransfer") {
    return apertium_posttransfer(in.c_str(), a.flags.c_str(), tmp_dir);
  }
  if (tool == "apertium-transfer") {
    std::string trules   = take_file(a);
    std::string datafile = take_file(a);
    std::string biltrans = opt_file(a);
    trules = rules_xml_for_bin(trules, datafile);
    return apertium_transfer(in.c_str(), trules.c_str(), datafile.c_str(),
                             biltrans.empty() ? nullptr : biltrans.c_str(),
                             a.flags.c_str(), tmp_dir);
  }
  if (tool == "apertium-interchunk") {
    std::string t2x  = take_file(a);
    std::string data = take_file(a);
    t2x = rules_xml_for_bin(t2x, data);
    return apertium_interchunk(in.c_str(), t2x.c_str(), data.c_str(),
                               a.flags.c_str(), tmp_dir);
  }
  if (tool == "apertium-postchunk") {
    std::string t3x  = take_file(a);
    std::string data = take_file(a);
    t3x = rules_xml_for_bin(t3x, data);
    return apertium_postchunk(in.c_str(), t3x.c_str(), data.c_str(),
                              a.flags.c_str(), tmp_dir);
  }
  if (tool == "lrx-proc") {
    std::string bin = take_file(a);
    return apertium_lrx_proc(in.c_str(), bin.c_str(), a.flags.c_str(), tmp_dir);
  }
  if (tool == "lsx-proc") {
    std::string bin = take_file(a);
    return apertium_lsx_proc(in.c_str(), bin.c_str(), a.flags.c_str(), tmp_dir);
  }
  if (tool == "rtx-proc") {
    std::string rtx = take_file(a);
    return apertium_rtx_proc(in.c_str(), rtx.c_str(), a.flags.c_str(), tmp_dir);
  }
  if (tool == "cg-proc") {
    // -f 1 is the Apertium stream format, the only one the wrapper speaks.
    auto f = a.values.find('f');
    if (f != a.values.end() && std::atoi(f->second.c_str()) != 1)
      throw std::runtime_error("cg-proc -f " + f->second + " is not supported on iOS");
    std::string grammar = take_file(a);
    ApertiumResult r = apertium_cg_proc(in.c_str(), grammar.c_str(),
                                        a.flags.c_str(), tmp_dir);
    if (r.output) {
      std::string stripped = strip_dependency_tags(r.output);
      if (stripped.size() != std::strlen(r.output)) {
        std::free(r.output);
        r.output = aix::dup_cstr(stripped);
        if (!r.output) r.error = aix::dup_cstr("dup_cstr failed");
      }
    }
    return r;
  }
  if (tool == "apertium-anaphora") {
    std::string arx = take_file(a);
    return apertium_anaphora(in.c_str(), arx.c_str(), a.flags.c_str(), tmp_dir);
  }
  if (tool == "hfst-proc" || tool == "hfst-apertium-proc") {
    int analyses       = take_count(a, 'N');
    int weight_classes = take_count(a, 'l');
    std::string bin = take_file(a);
    return apertium_hfst_proc(in.c_str(), bin.c_str(), a.flags.c_str(),
                              analyses, weight_classes, tmp_dir);
  }
  ApertiumResult r{nullptr, aix::dup_cstr("unknown tool: " + tool)};
  return r;
}

ApertiumResult run_stage(const std::vector<std::string>& stage,
                         const std::string& in,
                         const char* tmp_dir) {
  if (stage.empty()) {
    ApertiumResult r{aix::dup_cstr(in), nullptr};
    return r;
  }
  const std::string& tool = stage[0];
  auto spec = tool_options().find(tool);
  if (spec == tool_options().end()) {
    ApertiumResult r{nullptr, aix::dup_cstr("unknown tool: " + tool)};
    return r;
  }
  try {
    Argv a = parse_argv(stage, spec->second);
    return dispatch_stage(tool, a, in, tmp_dir);
  } catch (const std::exception& e) {
    ApertiumResult r{nullptr, aix::dup_cstr(e.what())};
    return r;
  } catch (...) {
    // The wrappers catch everything themselves (aix::run_wrapper); this is
    // for the dispatch around them.
    ApertiumResult r{nullptr, aix::dup_cstr("unknown exception (not a std::exception)")};
    return r;
  }
}

// Read the first non-empty, non-comment line from the mode file.
std::string read_mode_line(const std::string& path) {
  std::ifstream f(path);
  if (!f) throw std::runtime_error("cannot open mode file: " + path);
  std::string line;
  while (std::getline(f, line)) {
    size_t a = line.find_first_not_of(" \t\r\n");
    if (a == std::string::npos) continue;
    if (line[a] == '#') continue;
    return line.substr(a);
  }
  throw std::runtime_error("empty mode file: " + path);
}

// Mirror NativePipeline.escapeStream: backslash-escape the characters that
// are syntax in Apertium's stream format (lttoolbox's escaped_chars, the set
// apertium-destxt escapes). Mode files start at lt-proc, not at the
// deformatter, so raw user text must be escaped before stage 1: unescaped,
// lt-proc throws "Malformed input stream" at the first / @ $ ... (a date,
// an email, a URL); < silently cuts the text off and [ leaves the rest
// untranslated.
// All of these are ASCII, so walking UTF-8 bytes is safe.
bool is_stream_reserved(char c) {
  switch (c) {
    case '\\': case '[': case ']': case '{': case '}':
    case '^': case '$': case '/': case '@': case '<': case '>':
      return true;
    default:
      return false;
  }
}

std::string escape_stream(const std::string& text) {
  std::string out;
  out.reserve(text.size() + 8);
  for (char c : text) {
    if (is_stream_reserved(c)) out.push_back('\\');
    out.push_back(c);
  }
  return out;
}

// Mirror NativePipeline.unescapeStream: drop the stream escapes that
// survive to the final output (\X -> X), as apertium-retxt does. Runs after
// apply_marker_pref, which recognizes escaped markers (\@word) itself.
std::string unescape_stream(const std::string& text) {
  std::string once;
  once.reserve(text.size());
  for (size_t i = 0; i < text.size(); ++i) {
    if (text[i] == '\\' && i + 1 < text.size()) ++i;
    once.push_back(text[i]);
  }
  // lttoolbox's fallback for a word it can't generate ("#joan@correu.cat",
  // "#$20") writes the still-escaped text through its escaper a second time,
  // so those words keep one level ("\@") after the pass above. Drop a
  // backslash left in front of a stream character; the only casualty is a
  // user-typed backslash directly before one of them.
  std::string out;
  out.reserve(once.size());
  for (size_t i = 0; i < once.size(); ++i) {
    if (once[i] == '\\' && i + 1 < once.size() && once[i + 1] != '\\'
        && is_stream_reserved(once[i + 1])) {
      continue;
    }
    out.push_back(once[i]);
  }
  return out;
}

// Mirror NativePipeline.applyMarkerPref:
// @word / #word / *word (optionally backslash-escaped) at start-of-string
// or after whitespace → normalize to a single * (display_marks=true) or
// strip outright (display_marks=false).
// Hand-rolled iteration because libc++'s std::regex doesn't implement
// ECMAScript lookbehind — using \\?[@#*](?=\S) wouldn't fly either.
std::string apply_marker_pref(const std::string& text, bool display_marks) {
  std::string out;
  out.reserve(text.size());
  auto is_space = [](char c) {
    return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f';
  };
  auto is_marker = [](char c) { return c == '@' || c == '#' || c == '*'; };
  const char* replacement = display_marks ? "*" : "";
  size_t i = 0;
  while (i < text.size()) {
    bool at_boundary = (i == 0) || is_space(text[i - 1]);
    char c = text[i];
    // Optional backslash escape before the marker.
    if (at_boundary && c == '\\' && i + 1 < text.size()
        && is_marker(text[i + 1]) && i + 2 < text.size()
        && !is_space(text[i + 2]) && text[i + 2] != '\0') {
      out.append(replacement);
      i += 2;  // skip \\ + marker; the following non-space char stays
      continue;
    }
    if (at_boundary && is_marker(c) && i + 1 < text.size()
        && !is_space(text[i + 1])) {
      out.append(replacement);
      i += 1;
      continue;
    }
    out.push_back(c);
    ++i;
  }
  return out;
}

}  // namespace

extern "C" ApertiumResult apertium_translate(const char* mode_file_path,
                                             const char* pair_base_dir,
                                             const char* input,
                                             int display_marks,
                                             const char* tmp_dir) {
  ApertiumResult result{nullptr, nullptr};
  try {
    if (!mode_file_path) throw std::runtime_error("mode_file_path is NULL");
    if (!pair_base_dir)  throw std::runtime_error("pair_base_dir is NULL");
    if (!tmp_dir)        throw std::runtime_error("tmp_dir is NULL");

    std::string line = read_mode_line(mode_file_path);
    auto stages = parse_mode_line(line, pair_base_dir);
    if (stages.empty()) {
      result.output = aix::dup_cstr(input ? input : "");
      return result;
    }

    std::string current = escape_stream(input ? input : "");
    const char* trace = std::getenv("APERTIUM_TRACE");
    const bool trace_on = trace && trace[0] && trace[0] != '0';
    for (size_t i = 0; i < stages.size(); ++i) {
      ApertiumResult r = run_stage(stages[i], current, tmp_dir);
      if (r.error) {
        std::string prefix = "stage " + std::to_string(i + 1) + " ("
                           + stages[i][0] + "): ";
        std::string combined = prefix + r.error;
        apertium_result_free(r);
        throw std::runtime_error(combined);
      }
      current = r.output ? r.output : "";
      apertium_result_free(r);
      if (trace_on) {
        std::fprintf(stderr, "[stage %zu %-20s] %s\n",
                     i + 1, stages[i][0].c_str(), current.c_str());
      }
    }

    std::string final_text =
        unescape_stream(apply_marker_pref(current, display_marks != 0));
    result.output = aix::dup_cstr(final_text);
    if (!result.output) throw std::runtime_error("dup_cstr failed");
    return result;
  } catch (const std::exception& e) {
    result.error = aix::dup_cstr(e.what());
    return result;
  } catch (...) {
    // Nothing may cross the extern "C" boundary into Swift: an exception
    // escaping here terminates the app.
    result.error = aix::dup_cstr("unknown exception (not a std::exception)");
    return result;
  }
}
