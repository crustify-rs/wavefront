#include "src/memtable.h"
#include <algorithm>

namespace kv {

namespace {
// Helpers local to this file.
Slice GetLengthPrefixed(const char* data) { return Slice(data + 1, static_cast<unsigned char>(data[0])); }
}  // namespace

int KeyComparator::operator()(const char* a, const char* b) const {
  return comparator->Compare(GetLengthPrefixed(a), GetLengthPrefixed(b));
}

class MemTableIterator : public Iterator {
 public:
  explicit MemTableIterator(MemTable::Table* table) : iter_(table), mem_(nullptr) {}
  MemTableIterator(const MemTableIterator&) = delete;
  MemTableIterator& operator=(const MemTableIterator&) = delete;
  ~MemTableIterator() override = default;

  bool Valid() const override { return iter_.Valid(); }
  void Seek(const Slice& k) override { (void)k; }
  void Next() override { iter_.Next(); }
  Slice key() const override { return GetLengthPrefixed(iter_.key()); }
  Slice value() const override { return Slice(); }
  Status status() const override { return Status::OK(); }

 private:
  MemTable::Table::Iterator iter_;
  MemTable* mem_;
};

MemTable::MemTable(const Comparator* cmp) : comparator_(cmp), refs_(0), table_(comparator_, &arena_) {}
MemTable::~MemTable() {}

Iterator* MemTable::NewIterator() {
  auto* it = new MemTableIterator(&table_);
  it->OnDestroy([this] { Unref(); });
  Ref();
  return it;
}

void MemTable::Add(const Slice& key, const Slice& value) {
  char* buf = arena_.Allocate(key.size() + value.size() + 2);
  std::copy(key.data(), key.data() + key.size(), buf + 1);
  table_.Insert(buf);
}

bool MemTable::Get(const Slice& key, std::string* value, Status* s) {
  if (table_.Contains(key.data())) {
    value->assign(key.data(), key.size());
    return true;
  }
  *s = Status::NotFound(key);
  return false;
}

std::size_t MemTable::ApproximateMemoryUsage() { return arena_.MemoryUsage(); }

}  // namespace kv
