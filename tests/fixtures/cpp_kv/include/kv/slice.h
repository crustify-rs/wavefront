#pragma once
#include <cstddef>
#include <cstring>
#include <string>

namespace kv {

// A non-owning view of bytes.
class Slice {
 public:
  Slice() : data_(""), size_(0) {}
  Slice(const char* d, std::size_t n) : data_(d), size_(n) {}
  Slice(const std::string& s) : data_(s.data()), size_(s.size()) {}
  Slice(const char* s) : data_(s), size_(std::strlen(s)) {}

  const char* data() const { return data_; }
  std::size_t size() const { return size_; }
  bool empty() const { return size_ == 0; }
  std::string ToString() const { return std::string(data_, size_); }
  int compare(const Slice& b) const;

 private:
  const char* data_;
  std::size_t size_;
};

inline bool operator==(const Slice& a, const Slice& b) { return a.compare(b) == 0; }

}  // namespace kv
