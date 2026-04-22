// apertium-ios-native/wrappers/wrapper_common.h
//
// Shared helpers used by every library-ified wrapper. Header-only; pulled
// into one wrapper.cpp per Apertium tool. Don't include from Swift —
// Swift talks to the public C API in apertium_core.h.

#ifndef APERTIUM_IOS_WRAPPER_COMMON_H
#define APERTIUM_IOS_WRAPPER_COMMON_H

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>

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

// Write `input` (with a trailing newline if missing — Apertium's tools
// use newline as an end-of-stream sentinel downstream) to a fresh tmp
// file and return its path.
inline std::string spit_tmp(const std::string& tmp_dir,
                            const char* tag,
                            const char* input) {
  std::string path = make_tmp_file(tmp_dir, tag);
  std::string buf(input ? input : "");
  if (buf.empty() || buf.back() != '\n') buf.push_back('\n');
  spit(path, buf);
  return path;
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

}  // namespace aix

#endif  // APERTIUM_IOS_WRAPPER_COMMON_H
