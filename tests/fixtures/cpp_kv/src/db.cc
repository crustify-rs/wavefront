#include "src/db.h"
#include <algorithm>

namespace kv {

DB::DB(const Options& options, std::string_view name)
    : options_(options), name_(name), mem_(new MemTable(options.comparator)) {
  mem_->Ref();
}

DB::DB(DB&& other) noexcept
    : options_(other.options_), name_(std::move(other.name_)), mem_(other.mem_),
      snapshots_(std::move(other.snapshots_)), cursors_(std::move(other.cursors_)) {
  other.mem_ = nullptr;
}

DB::~DB() {
  if (mem_ != nullptr) mem_->Unref();
}

Status DB::Open(const Options& options, std::string_view name, std::unique_ptr<DB>* dbptr) {
  if (name.empty()) return Status::Corruption("empty name");
  dbptr->reset(new DB(options, name));
  return Status::OK();
}

Status DB::Put(const Slice& key, const Slice& value) {
  mem_->Add(key, value);
  return Status::OK();
}

Status DB::Put(const std::string& key, const std::string& value) { return Put(Slice(key), Slice(value)); }

std::optional<std::string> DB::Get(const Slice& key) const {
  std::string v;
  Status s;
  if (mem_->Get(key, &v, &s)) return v;
  return std::nullopt;
}

std::shared_ptr<const Snapshot> DB::GetSnapshot() {
  auto snap = std::make_shared<const Snapshot>(this, snapshots_.size());
  snapshots_.push_back(snap);
  return snap;
}

void DB::ReleaseSnapshot(std::weak_ptr<const Snapshot> snap) {
  auto s = snap.lock();
  snapshots_.erase(std::remove_if(snapshots_.begin(), snapshots_.end(),
                                  [&](const std::shared_ptr<const Snapshot>& x) { return x == s; }),
                   snapshots_.end());
}

template <>
class SkipList<int, int> {
 public:
  bool Contains(const int& k) const { return k == 0; }
};

int CountKeys(const DB& db) { return static_cast<int>(db.snapshots().size()); }
int CountKeys(const std::vector<const DB*>& dbs) {
  int n = 0;
  for (const DB* d : dbs) n += CountKeys(*d);
  return n;
}

}  // namespace kv
