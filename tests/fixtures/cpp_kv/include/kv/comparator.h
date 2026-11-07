#pragma once
#include "kv/slice.h"

namespace kv {

// An ordering over keys, implemented by users.
class Comparator {
 public:
  virtual ~Comparator();
  virtual int Compare(const Slice& a, const Slice& b) const = 0;
  virtual const char* Name() const = 0;
};

const Comparator* BytewiseComparator();

}  // namespace kv
