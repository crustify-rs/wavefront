#pragma once
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>
#include "kv/comparator.h"
#include "kv/status.h"
#include "src/memtable.h"

namespace kv {

class Snapshot;
class DB;

// A point-in-time view. Snapshots and their DB point at each other.
class Snapshot {
 public:
  explicit Snapshot(DB* db, unsigned long seq) : db_(db), seq_(seq) {}
  unsigned long sequence() const { return seq_; }
  DB* db() const { return db_; }
 private:
  DB* db_;
  unsigned long seq_;
};

struct Options {
  const Comparator* comparator = BytewiseComparator();
  bool create_if_missing = false;
  std::size_t write_buffer_size = 4 << 20;
};

class DB {
 public:
  static Status Open(const Options& options, std::string_view name, std::unique_ptr<DB>* dbptr);
  DB(const DB&) = delete;
  DB& operator=(const DB&) = delete;
  DB(DB&&) noexcept;
  ~DB();

  Status Put(const Slice& key, const Slice& value);
  Status Put(const std::string& key, const std::string& value);
  std::optional<std::string> Get(const Slice& key) const;
  std::shared_ptr<const Snapshot> GetSnapshot();
  void ReleaseSnapshot(std::weak_ptr<const Snapshot> snap);
  const std::vector<std::shared_ptr<const Snapshot>>& snapshots() const { return snapshots_; }
  const Options& options() const { return options_; }
  void set_name(std::string n) { name_ = std::move(n); }

 private:
  DB(const Options& options, std::string_view name);
  Options options_;
  std::string name_;
  MemTable* mem_;
  std::vector<std::shared_ptr<const Snapshot>> snapshots_;
  std::map<std::string, std::unique_ptr<Iterator>> cursors_;
};

}  // namespace kv
