#pragma once
#include <string>
#include "kv/comparator.h"
#include "kv/iterator.h"
#include "src/arena.h"
#include "src/skiplist.h"

namespace kv {

class MemTable;

// Ordering of the entries a memtable holds.
struct KeyComparator {
  const Comparator* comparator;
  explicit KeyComparator(const Comparator* c) : comparator(c) {}
  int operator()(const char* a, const char* b) const;
};

class MemTableIterator;

class MemTable {
 public:
  explicit MemTable(const Comparator* cmp);
  MemTable(const MemTable&) = delete;
  MemTable& operator=(const MemTable&) = delete;

  void Ref() { ++refs_; }
  void Unref() {
    --refs_;
    if (refs_ <= 0) delete this;
  }

  Iterator* NewIterator();
  void Add(const Slice& key, const Slice& value);
  bool Get(const Slice& key, std::string* value, Status* s);
  std::size_t ApproximateMemoryUsage();

 private:
  friend class MemTableIterator;
  using Table = SkipList<const char*, KeyComparator>;
  ~MemTable();

  KeyComparator comparator_;
  int refs_;
  Arena arena_;
  Table table_;
};

}  // namespace kv
