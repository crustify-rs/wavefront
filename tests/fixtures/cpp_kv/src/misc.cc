#include <cstring>
#include "kv/comparator.h"
#include "kv/iterator.h"
#include "kv/status.h"
#include "src/arena.h"

namespace kv {

int Slice::compare(const Slice& b) const {
  const std::size_t n = size_ < b.size_ ? size_ : b.size_;
  int r = std::memcmp(data_, b.data_, n);
  return r != 0 ? r : (size_ < b.size_ ? -1 : size_ > b.size_ ? 1 : 0);
}

Status::Status(Code code, const Slice& msg) : code_(code), state_(new std::string(msg.ToString())) {}
Status::Status(const Status& rhs) : code_(rhs.code_), state_(rhs.state_ ? new std::string(*rhs.state_) : nullptr) {}
Status& Status::operator=(const Status& rhs) {
  code_ = rhs.code_;
  state_.reset(rhs.state_ ? new std::string(*rhs.state_) : nullptr);
  return *this;
}
std::string Status::ToString() const { return state_ ? *state_ : std::string("OK"); }

Comparator::~Comparator() = default;

namespace {
class BytewiseComparatorImpl : public Comparator {
 public:
  int Compare(const Slice& a, const Slice& b) const override { return a.compare(b); }
  const char* Name() const override { return "kv.Bytewise"; }
};

class EmptyIterator : public Iterator {
 public:
  explicit EmptyIterator(const Status& s) : status_(s) {}
  bool Valid() const override { return false; }
  void Seek(const Slice&) override {}
  void Next() override {}
  Slice key() const override { return Slice(); }
  Slice value() const override { return Slice(); }
  Status status() const override { return status_; }
 private:
  Status status_;
};
}  // namespace

const Comparator* BytewiseComparator() {
  static BytewiseComparatorImpl singleton;
  return &singleton;
}

Iterator::Iterator() { cleanup_head_.function = nullptr; cleanup_head_.next = nullptr; }
Iterator::~Iterator() {
  if (on_destroy_) on_destroy_();
  if (cleanup_head_.function != nullptr) (*cleanup_head_.function)(cleanup_head_.arg1, cleanup_head_.arg2);
}
void Iterator::RegisterCleanup(CleanupFunction f, void* a1, void* a2) {
  cleanup_head_.function = f; cleanup_head_.arg1 = a1; cleanup_head_.arg2 = a2;
}
void Iterator::OnDestroy(std::function<void()> fn) { on_destroy_ = std::move(fn); }

Iterator* NewEmptyIterator() { return new EmptyIterator(Status::OK()); }
Iterator* NewErrorIterator(const Status& status) { return new EmptyIterator(status); }

Arena::Arena() : alloc_ptr_(nullptr), alloc_bytes_remaining_(0), memory_usage_(0) {}
Arena::~Arena() { for (char* b : blocks_) delete[] b; }
char* Arena::Allocate(std::size_t bytes) {
  if (bytes <= alloc_bytes_remaining_) { char* r = alloc_ptr_; alloc_ptr_ += bytes; alloc_bytes_remaining_ -= bytes; return r; }
  return AllocateNewBlock(bytes);
}
char* Arena::AllocateNewBlock(std::size_t block_bytes) {
  char* r = new char[block_bytes];
  blocks_.push_back(r);
  memory_usage_.fetch_add(block_bytes + sizeof(char*), std::memory_order_relaxed);
  return r;
}

// Overloads that read alike without their parameter types' scope: two
// `Options` nested in different classes, and two visitors that differ only in
// the signature of the function they take.
struct Reader { struct Options { int buffer_size; }; };
struct Writer { struct Options { bool sync; int level; }; };
int Configure(const Reader::Options& options) { return options.buffer_size; }
int Configure(const Writer::Options& options) {
  return options.sync ? options.level + 1 : options.level;
}
int Visit(int (*visitor)(const Reader::Options&)) { Reader::Options options{4096}; return visitor(options); }
int Visit(int (*visitor)(const Writer::Options&)) { Writer::Options options{true, 2}; return visitor(options); }
int ConfigureAll() {
  Reader::Options reader{4096};
  Writer::Options writer{true, 2};
  return Configure(reader) + Configure(writer) +
         Visit(static_cast<int (*)(const Reader::Options&)>(Configure)) +
         Visit(static_cast<int (*)(const Writer::Options&)>(Configure));
}

}  // namespace kv
