// apertium-ios-native/wrappers/wrapper_common.h
//
// Shared helpers used by every library-ified wrapper. Header-only; pulled
// into one wrapper.cpp per Apertium tool. Don't include from Swift —
// Swift talks to the public C API in apertium_core.h.

#ifndef APERTIUM_IOS_WRAPPER_COMMON_H
#define APERTIUM_IOS_WRAPPER_COMMON_H

#include "apertium_core.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
#include <utility>
#include <vector>

#include <unicode/ustdio.h>

namespace aix {

inline std::string slurp(const std::string& path) {
  std::ifstream f(path, std::ios::binary);
  std::stringstream ss;
  ss << f.rdbuf();
  return ss.str();
}

inline void spit(const std::string& path, const std::string& data) {
  std::ofstream f(path, std::ios::binary);
  f.write(data.data(), static_cast<std::streamsize>(data.size()));
}

inline std::string make_tmp_file(const std::string& tmp_dir, const char* tag) {
  std::string tmpl = tmp_dir + "/apertium_" + tag + "_XXXXXX";
  std::vector<char> buf(tmpl.begin(), tmpl.end());
  buf.push_back('\0');
  int fd = ::mkstemp(buf.data());
  if (fd < 0) {
    throw std::runtime_error(std::string("mkstemp failed for ") + buf.data());
  }
  ::close(fd);
  return std::string(buf.data());
}

inline char* dup_cstr(const std::string& s) {
  char* p = static_cast<char*>(std::malloc(s.size() + 1));
  if (!p) return nullptr;
  std::memcpy(p, s.data(), s.size());
  p[s.size()] = '\0';
  return p;
}

inline void ensure_exists(const std::string& path) {
  struct stat sb;
  if (::stat(path.c_str(), &sb) == -1) {
    throw std::runtime_error("file not found: " + path);
  }
}

inline void rm_quiet(const std::string& path) {
  if (!path.empty()) std::remove(path.c_str());
}

// --- Stage resources ---------------------------------------------------------
// Every stage runs in the app's one long-lived process, and upstream code
// throws with files still open (lttoolbox's "Malformed input stream", a
// truncated .bin, HFST's header checks). Whatever a failed stage leaves open
// stays open for the rest of the session, until open() fails and lttoolbox
// exits the app ("Cannot open file ... for writing"). So a wrapper holds every
// file it opens in one of these owners, or in lttoolbox's InputFile, which
// closes itself, and lets the stack release them on success and failure
// alike. Declare the tmp files before the streams on them, so the streams
// close first.

struct FileCloser {
  void operator()(FILE* f) const {
    if (f != stdin) std::fclose(f);  // openInBinFile("-") returns stdin
  }
};
using FilePtr = std::unique_ptr<FILE, FileCloser>;

struct UFileCloser {
  void operator()(UFILE* f) const { u_fclose(f); }
};
using UFilePtr = std::unique_ptr<UFILE, UFileCloser>;

// A tmp file under tmp_dir, deleted when it goes out of scope.
class TmpFile {
 public:
  TmpFile(const std::string& tmp_dir, const char* tag)
      : path_(make_tmp_file(tmp_dir, tag)) {}
  TmpFile(TmpFile&& other) noexcept : path_(std::move(other.path_)) {
    other.path_.clear();
  }
  TmpFile(const TmpFile&) = delete;
  TmpFile& operator=(const TmpFile&) = delete;
  TmpFile& operator=(TmpFile&&) = delete;
  ~TmpFile() { rm_quiet(path_); }

  const std::string& path() const { return path_; }
  const char* c_str() const { return path_.c_str(); }

 private:
  std::string path_;
};

// Write `input` (with a trailing newline if missing — Apertium's tools
// use newline as an end-of-stream sentinel downstream) to a fresh tmp
// file.
inline TmpFile spit_tmp(const std::string& tmp_dir,
                        const char* tag,
                        const char* input) {
  TmpFile file(tmp_dir, tag);
  std::string buf(input ? input : "");
  if (buf.empty() || buf.back() != '\n') buf.push_back('\n');
  spit(file.path(), buf);
  return file;
}

// Run a wrapper's body, which returns the stage's output, and package the
// outcome. Every exception becomes the error string: one that isn't a
// std::exception (HFST's HfstException isn't) would otherwise cross the
// extern "C" boundary and terminate the app.
template <typename Body>
ApertiumResult run_wrapper(Body&& body) {
  ApertiumResult result{nullptr, nullptr};
  try {
    result.output = dup_cstr(body());
    if (!result.output) result.error = dup_cstr("dup_cstr failed");
  } catch (const std::exception& e) {
    result.error = dup_cstr(e.what());
  } catch (...) {
    result.error = dup_cstr("unknown exception (not a std::exception)");
  }
  return result;
}

}  // namespace aix

#endif  // APERTIUM_IOS_WRAPPER_COMMON_H
